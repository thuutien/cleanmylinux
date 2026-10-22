"""Space Lens: interactive folder size map."""

import colorsys
import threading

from gi.repository import Gdk, GLib, GObject, Gtk, Pango, PangoCairo

from ...core import host, spacelens
from ...core.utils import HOME, human_size, move_to_trash
from ..widgets import (Hero, RoundButton, confirm, css_button, icon, idle, info, label,
                       run_async)


def squarify(items, x, y, w, h):
    """Squarified treemap. items: [(size, obj)] sorted desc. Returns [(obj, x, y, w, h)]."""
    total = sum(s for s, _ in items)
    if total <= 0 or w <= 0 or h <= 0:
        return []
    scale = w * h / total
    rects = []
    items = [(s * scale, o) for s, o in items if s > 0]
    while items:
        short = min(w, h)
        row, rest = [items[0]], items[1:]

        def worst(r):
            area = sum(a for a, _ in r)
            side = area / short
            return max(max(side * side / a, a / (side * side)) for a, _ in r)

        while rest and worst(row + [rest[0]]) <= worst(row):
            row.append(rest.pop(0))
        area = sum(a for a, _ in row)
        side = area / short
        offset = 0
        for a, obj in row:
            length = a / side
            if w >= h:
                rects.append((obj, x, y + offset, side, length))
            else:
                rects.append((obj, x + offset, y, length, side))
            offset += length
        if w >= h:
            x, w = x + side, w - side
        else:
            y, h = y + side, h - side
        items = rest
    return rects


class Treemap(Gtk.DrawingArea):
    __gsignals__ = {"node-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,))}

    def __init__(self):
        super().__init__()
        self.node = None
        self.rects = []
        self.hover = None
        self.set_size_request(300, 260)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._click)
        self.connect("motion-notify-event", self._motion)
        self.connect("leave-notify-event", lambda *_: self._set_hover(None))

    def set_node(self, node):
        self.node = node
        self.queue_draw()

    def _set_hover(self, obj):
        if obj is not self.hover:
            self.hover = obj
            self.set_tooltip_text(f"{obj.name} — {human_size(obj.size)}" if obj else None)
            self.queue_draw()

    def _hit(self, ex, ey):
        for obj, x, y, w, h in self.rects:
            if x <= ex < x + w and y <= ey < y + h:
                return obj
        return None

    def _motion(self, _w, event):
        self._set_hover(self._hit(event.x, event.y))

    def _click(self, _w, event):
        obj = self._hit(event.x, event.y)
        if obj is not None and event.type == Gdk.EventType.BUTTON_PRESS:
            self.emit("node-activated", obj)

    def _draw(self, widget, cr):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        self.rects = []
        if not self.node or self.node.size <= 0:
            return
        items = [(c.size, c) for c in self.node.children[:60]]
        self.rects = squarify(items, 0, 0, width, height)
        layout = widget.create_pango_layout("")
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        for index, (obj, x, y, w, h) in enumerate(self.rects):
            hue = (0.72 + index * 0.085) % 1.0
            light = 0.45 if obj.is_dir else 0.32
            r, g, b = colorsys.hls_to_rgb(hue, light, 0.55 if not obj.is_group else 0.05)
            alpha = 0.95 if obj is self.hover else 0.75
            cr.set_source_rgba(r, g, b, alpha)
            cr.rectangle(x + 1.5, y + 1.5, max(w - 3, 0), max(h - 3, 0))
            cr.fill()
            if w > 60 and h > 34:
                cr.set_source_rgba(1, 1, 1, 0.95)
                layout.set_width(int((w - 14) * Pango.SCALE))
                layout.set_markup(f"<b>{_esc(obj.name)}</b>\n<small>{human_size(obj.size)}</small>", -1)
                cr.move_to(x + 8, y + 6)
                PangoCairo.show_layout(cr, layout)


def _esc(text):
    return GLib.markup_escape_text(text)


class SpaceLensPage(Gtk.Stack):
    page_id = "spacelens"
    title = "Space Lens"
    sidebar_icon = "drive-harddisk-symbolic"

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.root = None
        self.current = None
        self.cancel = threading.Event()
        self.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        # Intro
        self.target = HOME
        chooser = Gtk.Box(spacing=8)
        chooser.set_halign(Gtk.Align.CENTER)
        group = None
        targets = [("Home folder", HOME)] + ([] if host.FLATPAK else [("Whole system disk", "/")])
        for text, path in targets:
            radio = Gtk.RadioButton.new_with_label_from_widget(group, text)
            radio.get_style_context().add_class("option-label")
            radio.connect("toggled", self._radio, path)
            group = group or radio
            chooser.pack_start(radio, False, False, 6)
        other = css_button("Other folder…", "pill flat-pill small", "folder-symbolic")
        other.connect("clicked", self._choose)
        chooser.pack_start(other, False, False, 6)
        scan = RoundButton("Scan")
        scan.connect("clicked", lambda *_: self.start_scan())
        self.add_named(Hero("drive-harddisk-symbolic", "Space Lens",
                            "Get a visual size comparison of your folders and files. "
                            "Click a block to dive into it and find what eats your storage.",
                            scan, chooser), "intro")

        # Progress
        progress = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        progress.set_valign(Gtk.Align.CENTER)
        progress.set_halign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner()
        spinner.set_size_request(72, 72)
        spinner.start()
        progress.pack_start(spinner, False, False, 0)
        progress.pack_start(label("Building your storage map…", "hero-title"), False, False, 0)
        self.progress_label = label("", "hero-subtitle")
        self.progress_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.progress_label.set_max_width_chars(70)
        progress.pack_start(self.progress_label, False, False, 0)
        stop = css_button("Stop", "pill flat-pill")
        stop.set_halign(Gtk.Align.CENTER)
        stop.connect("clicked", lambda *_: self.cancel.set())
        progress.pack_start(stop, False, False, 10)
        self.add_named(progress, "progress")

        # Results
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ("start", "end"):
            getattr(body, f"set_margin_{side}")(28)
        body.set_margin_bottom(20)
        bar = Gtk.Box(spacing=8)
        self.up_button = css_button("", "pill flat-pill small", "go-up-symbolic")
        self.up_button.connect("clicked", lambda *_: self.go(self.current.parent))
        bar.pack_start(self.up_button, False, False, 0)
        self.crumbs = Gtk.Box(spacing=2)
        bar.pack_start(self.crumbs, True, True, 0)
        rescan = css_button("New Scan", "pill flat-pill small", "view-refresh-symbolic")
        rescan.connect("clicked", lambda *_: self.set_visible_child_name("intro"))
        bar.pack_end(rescan, False, False, 0)
        body.pack_start(bar, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        # name, size text, fraction, node, icon
        self.store = Gtk.ListStore(str, str, int, object, str, bool)
        self.view = Gtk.TreeView(model=self.store, headers_visible=False)
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self._toggled)
        self.view.append_column(Gtk.TreeViewColumn("", toggle, active=5))
        col = Gtk.TreeViewColumn("Name")
        pix = Gtk.CellRendererPixbuf()
        col.pack_start(pix, False)
        col.add_attribute(pix, "icon-name", 4)
        text = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.MIDDLE)
        col.pack_start(text, True)
        col.add_attribute(text, "markup", 0)
        col.set_expand(True)
        self.view.append_column(col)
        size_col = Gtk.TreeViewColumn("Size")
        bar_cell = Gtk.CellRendererProgress(text_xalign=1.0)
        bar_cell.set_fixed_size(120, -1)
        size_col.pack_start(bar_cell, False)
        size_col.add_attribute(bar_cell, "value", 2)
        size_col.add_attribute(bar_cell, "text", 1)
        self.view.append_column(size_col)
        self.view.connect("row-activated", self._row_activated)
        scroll = Gtk.ScrolledWindow()
        scroll.get_style_context().add_class("card")
        scroll.set_size_request(340, -1)
        scroll.add(self.view)
        paned.pack1(scroll, False, False)
        self.treemap = Treemap()
        self.treemap.connect("node-activated", lambda _w, node: self._activate(node))
        frame = Gtk.Box()
        frame.get_style_context().add_class("card")
        frame.pack_start(self.treemap, True, True, 0)
        paned.pack2(frame, True, False)
        paned.set_position(380)
        body.pack_start(paned, True, True, 0)

        footer = Gtk.Box(spacing=12)
        self.selection_label = label("", "hero-subtitle", xalign=0)
        footer.pack_start(self.selection_label, True, True, 0)
        self.open_button = css_button("Open Folder", "pill flat-pill small", "document-open-symbolic")
        self.open_button.connect("clicked", lambda *_: Gtk.show_uri_on_window(
            self.window, "file://" + self.current.path, 0))
        self.open_button.set_valign(Gtk.Align.CENTER)
        footer.pack_start(self.open_button, False, False, 0)
        self.remove_button = RoundButton("Remove")
        self.remove_button.set_size_request(96, 96)
        self.remove_button.connect("clicked", self._remove)
        footer.pack_end(self.remove_button, False, False, 0)
        body.pack_start(footer, False, False, 0)
        self.add_named(body, "results")
        self.show_all()
        self.set_visible_child_name("intro")

    def _radio(self, radio, path):
        if radio.get_active():
            self.target = path

    def _choose(self, *_):
        dialog = Gtk.FileChooserNative.new("Choose a folder", self.window,
                                           Gtk.FileChooserAction.SELECT_FOLDER, "Scan", "Cancel")
        if dialog.run() == Gtk.ResponseType.ACCEPT and dialog.get_filename():
            self.target = dialog.get_filename()
            dialog.destroy()
            self.start_scan()
            return
        dialog.destroy()

    def start_scan(self):
        self.cancel = threading.Event()
        self.progress_label.set_text("")
        self.set_visible_child_name("progress")
        report = idle(lambda count, path: self.progress_label.set_text(
            f"{count:,} files · {path.replace(HOME, '~', 1)}"))
        target, cancel = self.target, self.cancel
        run_async(lambda: spacelens.scan(target, report, cancel), self._scanned, self._failed)

    def _failed(self, exc):
        info(self.window, "Scan failed", str(exc), error=True)
        self.set_visible_child_name("intro")

    def _scanned(self, root):
        if self.cancel.is_set():
            self.set_visible_child_name("intro")
            return
        self.root = root
        self.selected = set()
        self.go(root)
        self.set_visible_child_name("results")

    def go(self, node):
        if node is None or not node.is_dir:
            return
        self.current = node
        self.up_button.set_sensitive(node.parent is not None)
        for child in self.crumbs.get_children():
            self.crumbs.remove(child)
        chain = []
        walker = node
        while walker is not None:
            chain.insert(0, walker)
            walker = walker.parent
        for index, crumb in enumerate(chain):
            if index:
                self.crumbs.pack_start(label("›", "crumb-sep"), False, False, 0)
            name = crumb.path.replace(HOME, "Home", 1) if index == 0 else crumb.name
            button = Gtk.Button(label=name, relief=Gtk.ReliefStyle.NONE)
            button.get_style_context().add_class("crumb")
            button.connect("clicked", lambda _b, n=crumb: self.go(n))
            self.crumbs.pack_start(button, False, False, 0)
        self.crumbs.show_all()

        self.store.clear()
        biggest = node.children[0].size if node.children else 1
        for child in node.children:
            icon_name = "folder-symbolic" if child.is_dir else (
                "view-more-symbolic" if child.is_group else "text-x-generic-symbolic")
            name = _esc(child.name)
            if child.is_dir:
                name += f"\n<span alpha='60%' size='small'>{child.count:,} items</span>"
            self.store.append([name, human_size(child.size), int(100 * child.size / max(biggest, 1)),
                               child, icon_name, child in self.selected])
        self.treemap.set_node(node)
        self._update_selection()

    def _toggled(self, _cell, path):
        row = self.store[path]
        node = row[3]
        if node.is_group:
            return
        if node in self.selected:
            self.selected.discard(node)
        else:
            self.selected.add(node)
        row[5] = node in self.selected
        self._update_selection()

    def _update_selection(self):
        size = sum(n.size for n in self.selected)
        self.selection_label.set_markup(
            f"<b>{human_size(self.current.size)}</b> in this folder"
            + (f" · {len(self.selected)} selected ({human_size(size)})" if self.selected else
               " · tick items to remove them"))
        self.remove_button.set_text("Remove", human_size(size) if size else "")
        self.remove_button.set_sensitive(bool(self.selected))

    def _row_activated(self, _view, path, _col):
        self._activate(self.store[path][3])

    def _activate(self, node):
        if node.is_dir:
            self.go(node)

    @staticmethod
    def _ancestors(node):
        node = node.parent
        while node is not None:
            yield node
            node = node.parent

    def _remove(self, *_):
        # Skip items whose parent folder is also selected; it goes to the Trash with it.
        nodes = [n for n in self.selected if not any(a in self.selected for a in self._ancestors(n))]
        size = sum(n.size for n in nodes)
        names = "\n".join(n.path.replace(HOME, "~", 1) for n in nodes[:30])
        if not confirm(self.window, f"Move {len(nodes)} items to the Trash?",
                       f"{human_size(size)} will be moved to the Trash.", "Move to Trash", details=names):
            return
        errors = []
        for node in nodes:
            try:
                move_to_trash(node.path)
                node.remove()
            except Exception as exc:
                errors.append(f"{node.name}: {exc}")
        self.selected = set()
        if any(a.parent is None and a is not self.root for a in [self.current, *self._ancestors(self.current)]):
            self.current = self.root  # the folder we were in was removed
        self.go(self.current)
        if errors:
            info(self.window, "Some items could not be moved", "\n".join(errors[:6]), error=True)
        self.window.refresh_stats()
