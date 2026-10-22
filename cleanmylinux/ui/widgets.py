"""Reusable widgets: async runner, hero screens, check trees and the scan page skeleton."""

import threading
import traceback

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, GObject, Gtk, Pango  # noqa: E402

from ..core.utils import human_size  # noqa: E402


def run_async(func, on_done=None, on_error=None):
    """Run func() in a thread; deliver its result to on_done on the GTK main loop."""
    def deliver(cb, value):
        cb(value)
        return False

    def worker():
        try:
            result = func()
        except Exception as exc:
            traceback.print_exc()
            if on_error:
                GLib.idle_add(deliver, on_error, exc)
            return
        if on_done:
            GLib.idle_add(deliver, on_done, result)

    threading.Thread(target=worker, daemon=True).start()


def idle(func):
    """Wrap a callback so worker threads can call it safely."""
    def wrapper(*args):
        GLib.idle_add(lambda: func(*args) and False)
    return wrapper


def icon(name, size=16, css=None):
    image = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    image.set_pixel_size(size)
    if css:
        image.get_style_context().add_class(css)
    return image


def label(text="", css=None, xalign=0.5, wrap=False, markup=False):
    widget = Gtk.Label()
    widget.set_markup(text) if markup else widget.set_text(text)
    widget.set_xalign(xalign)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_justify(Gtk.Justification.CENTER if xalign == 0.5 else Gtk.Justification.LEFT)
    for cls in (css or "").split():
        widget.get_style_context().add_class(cls)
    return widget


def css_button(text, css="pill", icon_name=None):
    button = Gtk.Button()
    box = Gtk.Box(spacing=6)
    if icon_name:
        box.pack_start(icon(icon_name, 16), False, False, 0)
    if text:
        box.pack_start(Gtk.Label(label=text), False, False, 0)
    box.set_halign(Gtk.Align.CENTER)
    button.add(box)
    for cls in css.split():
        button.get_style_context().add_class(cls)
    return button


class RoundButton(Gtk.Button):
    """The big glowing circular action button."""

    def __init__(self, text, sub=""):
        super().__init__()
        self.get_style_context().add_class("round-button")
        self.set_size_request(118, 118)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_valign(Gtk.Align.CENTER)
        self.main = label(text, "round-main")
        self.sub = label(sub, "round-sub")
        box.pack_start(self.main, False, False, 0)
        box.pack_start(self.sub, False, False, 0)
        self.add(box)

    def set_text(self, text, sub=""):
        self.main.set_text(text)
        self.sub.set_text(sub)
        self.sub.set_visible(bool(sub))


def confirm(parent, title, body, ok_label="Continue", destructive=True, details=None):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                               buttons=Gtk.ButtonsType.NONE, text=title)
    dialog.format_secondary_text(body)
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    ok = dialog.add_button(ok_label, Gtk.ResponseType.OK)
    if destructive:
        ok.get_style_context().add_class("destructive-action")
    if details:
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD)
        view.get_buffer().set_text(details)
        scroll = Gtk.ScrolledWindow(min_content_height=140, max_content_height=260)
        scroll.set_propagate_natural_height(True)
        scroll.add(view)
        dialog.get_message_area().pack_start(scroll, True, True, 0)
        scroll.show_all()
    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.OK


def info(parent, title, body, error=False):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True,
                               message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
                               buttons=Gtk.ButtonsType.OK, text=title)
    dialog.format_secondary_text(body)
    dialog.run()
    dialog.destroy()


class Hero(Gtk.Box):
    """Centered icon + title + subtitle + action, used for intro and done screens."""

    def __init__(self, icon_name, title, subtitle, action=None, extra=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.image = icon(icon_name, 128, "hero-icon")
        self.pack_start(self.image, False, False, 6)
        self.title = label(title, "hero-title")
        self.subtitle = label(subtitle, "hero-subtitle", wrap=True)
        self.subtitle.set_max_width_chars(60)
        self.pack_start(self.title, False, False, 0)
        self.pack_start(self.subtitle, False, False, 0)
        if extra is not None:
            self.pack_start(extra, False, False, 8)
        if action is not None:
            self.pack_start(action, False, False, 24)


class CheckTree(Gtk.ScrolledWindow):
    """Two-level list with checkboxes. Parents are groups, children are items.

    Every row object must have a `selected` attribute. `texts(obj)` returns the
    strings for the text columns; `columns` is [(title, expand, xalign)].
    """

    def __init__(self, columns, on_changed=None, group_toggle=None):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.get_style_context().add_class("card")
        self.on_changed = on_changed
        self.group_toggle = group_toggle
        types = [GObject.TYPE_PYOBJECT, bool, bool, str] + [str] * len(columns)
        self.store = Gtk.TreeStore(*types)
        self.view = Gtk.TreeView(model=self.store, headers_visible=True)
        self.view.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        self.view.set_enable_search(False)

        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self._toggled)
        col = Gtk.TreeViewColumn("", toggle, active=1, inconsistent=2)
        self.view.append_column(col)

        for index, (title, expand, xalign) in enumerate(columns):
            text = Gtk.CellRendererText(xalign=xalign)
            col = Gtk.TreeViewColumn(title)
            if index == 0:
                pix = Gtk.CellRendererPixbuf()
                col.pack_start(pix, False)
                col.add_attribute(pix, "icon-name", 3)
                text.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
            col.pack_start(text, True)
            col.add_attribute(text, "markup", 4 + index)
            col.set_expand(expand)
            col.set_resizable(True)
            if xalign == 1.0:
                col.set_alignment(1.0)
            self.view.append_column(col)
        self.add(self.view)

    def clear(self):
        self.store.clear()

    def add_group(self, obj, icon_name, texts, children):
        """children: list of (obj, icon_name, texts)."""
        parent = self.store.append(None, [obj, False, False, icon_name, *texts])
        for child, child_icon, child_texts in children:
            self.store.append(parent, [child, child.selected, False, child_icon, *child_texts])
        self._sync_parent(parent)
        return parent

    def add_row(self, obj, icon_name, texts):
        return self.store.append(None, [obj, obj.selected, False, icon_name, *texts])

    def _sync_parent(self, parent):
        states = [self.store[c][0].selected for c in self._children(parent)]
        if not states:
            states = [self.store[parent][0].selected]
        self.store[parent][1] = all(states)
        self.store[parent][2] = any(states) and not all(states)

    def _children(self, parent):
        child = self.store.iter_children(parent)
        while child is not None:
            yield child
            child = self.store.iter_next(child)

    def _toggled(self, _renderer, path):
        it = self.store.get_iter(path)
        parent = self.store.iter_parent(it)
        if self.store.iter_has_child(it):
            new = not self.store[it][1]
            objs = [self.store[c][0] for c in self._children(it)]
            if self.group_toggle:
                self.group_toggle(self.store[it][0], objs, new)
            else:
                for obj in objs:
                    obj.selected = new
            for child in self._children(it):
                self.store[child][1] = self.store[child][0].selected
            self._sync_parent(it)
        else:
            obj = self.store[it][0]
            obj.selected = not obj.selected
            self.store[it][1] = obj.selected
            if parent is not None:
                self._sync_parent(parent)
        if self.on_changed:
            self.on_changed()

    def set_all(self, value):
        def visit(it):
            while it is not None:
                self.store[it][0].selected = value
                self.store[it][1] = value
                self.store[it][2] = False
                visit(self.store.iter_children(it))
                it = self.store.iter_next(it)
        visit(self.store.get_iter_first())
        if self.on_changed:
            self.on_changed()


def muted(text):
    return f"<span alpha='65%'>{GLib.markup_escape_text(text)}</span>"


def esc(text):
    return GLib.markup_escape_text(str(text))


class ScanPage(Gtk.Stack):
    """intro → scanning → results → working → done.

    Subclasses implement scan(progress, cancel), build_results(result),
    summary(result), selected_size() and perform(progress).
    """

    page_id = ""
    title = ""
    sidebar_icon = ""
    hero_icon = ""
    intro_title = ""
    intro_text = ""
    scan_label = "Scan"
    action_label = "Clean"
    working_label = "Cleaning…"
    done_icon = "object-select-symbolic"

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.set_transition_duration(220)
        self.cancel = threading.Event()
        self.result = None

        self.scan_button = RoundButton(self.scan_label)
        self.scan_button.connect("clicked", lambda *_: self.start_scan())
        self.add_named(Hero(self.hero_icon, self.intro_title, self.intro_text,
                            self.scan_button, self.intro_extra()), "intro")

        # Progress
        progress = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        progress.set_valign(Gtk.Align.CENTER)
        progress.set_halign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner()
        spinner.set_size_request(72, 72)
        spinner.start()
        progress.pack_start(spinner, False, False, 0)
        self.progress_title = label("Scanning…", "hero-title")
        self.progress_detail = label("", "hero-subtitle")
        self.progress_detail.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.progress_detail.set_max_width_chars(70)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_size_request(360, -1)
        self.stop_button = css_button("Stop", "pill flat-pill")
        self.stop_button.connect("clicked", lambda *_: self.cancel.set())
        self.stop_button.set_halign(Gtk.Align.CENTER)
        for widget in (self.progress_title, self.progress_detail, self.progress_bar):
            progress.pack_start(widget, False, False, 0)
        progress.pack_start(self.stop_button, False, False, 10)
        self.add_named(progress, "progress")

        # Results
        results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        results.set_margin_start(32)
        results.set_margin_end(32)
        results.set_margin_bottom(20)
        head = Gtk.Box(spacing=16)
        head.pack_start(icon(self.hero_icon, 64, "hero-icon"), False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        texts.set_valign(Gtk.Align.CENTER)
        self.summary_title = label("", "result-title", xalign=0)
        self.summary_text = label("", "hero-subtitle", xalign=0, wrap=True)
        texts.pack_start(self.summary_title, False, False, 0)
        texts.pack_start(self.summary_text, False, False, 0)
        head.pack_start(texts, True, True, 0)
        self.header_tools = Gtk.Box(spacing=6)
        self.header_tools.set_valign(Gtk.Align.CENTER)
        head.pack_end(self.header_tools, False, False, 0)
        results.pack_start(head, False, False, 0)
        self.results_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        results.pack_start(self.results_holder, True, True, 0)
        footer = Gtk.Box(spacing=12)
        back = css_button("Start Over", "pill flat-pill", "go-previous-symbolic")
        back.connect("clicked", lambda *_: self.reset())
        back.set_valign(Gtk.Align.CENTER)
        footer.pack_start(back, False, False, 0)
        self.action_button = RoundButton(self.action_label)
        self.action_button.connect("clicked", lambda *_: self.start_action())
        footer.set_center_widget(self.action_button)
        results.pack_start(footer, False, False, 0)
        self.add_named(results, "results")

        self.done_hero = Hero(self.done_icon, "", "", self._again_button())
        self.add_named(self.done_hero, "done")
        self.show_all()
        self.set_visible_child_name("intro")

    # -- hooks ---------------------------------------------------------------
    def intro_extra(self):
        return None

    def scan(self, progress, cancel):
        raise NotImplementedError

    def build_results(self, result):
        raise NotImplementedError

    def summary(self, result):
        return "", ""

    def selected_size(self):
        return 0

    def action_state(self):
        """(enabled, button sub-label) for the main action button."""
        size = self.selected_size()
        return size > 0, human_size(size) if size else ""

    def confirm_action(self):
        return True

    def perform(self, progress):
        """Return (freed_bytes, errors)."""
        raise NotImplementedError

    def done_text(self, freed, errors):
        return "All clean!", f"You freed up {human_size(freed)}."

    # -- flow ----------------------------------------------------------------
    def _again_button(self):
        button = css_button("Done", "pill")
        button.set_halign(Gtk.Align.CENTER)
        button.connect("clicked", lambda *_: self.reset())
        return button

    def reset(self):
        self.result = None
        self.set_visible_child_name("intro")

    def _progress(self, text, fraction=None):
        self.progress_detail.set_text(text)
        if fraction is None:
            self.progress_bar.pulse()
        else:
            self.progress_bar.set_fraction(fraction)

    def start_scan(self):
        self.cancel = threading.Event()
        self.progress_title.set_text("Scanning…")
        self.progress_detail.set_text("")
        self.progress_bar.set_fraction(0)
        self.stop_button.show()
        self.set_visible_child_name("progress")
        cancel = self.cancel
        report = idle(lambda text, fraction=None: self._progress(text, fraction))
        run_async(lambda: self.scan(report, cancel), self._scanned, self._failed)

    def _scanned(self, result):
        if self.cancel.is_set():
            self.reset()
            return
        self.result = result
        for child in self.results_holder.get_children():
            self.results_holder.remove(child)
        for child in self.header_tools.get_children():
            self.header_tools.remove(child)
        widget = self.build_results(result)
        self.results_holder.pack_start(widget, True, True, 0)
        self.results_holder.show_all()
        self.header_tools.show_all()
        self.refresh_summary()
        self.set_visible_child_name("results")

    def refresh_summary(self):
        title, text = self.summary(self.result)
        self.summary_title.set_text(title)
        self.summary_text.set_text(text)
        enabled, sub = self.action_state()
        self.action_button.set_text(self.action_label, sub)
        self.action_button.set_sensitive(enabled)

    def start_action(self):
        if not self.confirm_action():
            return
        self.progress_title.set_text(self.working_label)
        self.progress_detail.set_text("")
        self.progress_bar.set_fraction(0)
        self.stop_button.hide()
        self.set_visible_child_name("progress")
        report = idle(lambda text, fraction=None: self._progress(text, fraction))
        run_async(lambda: self.perform(report), self._performed, self._failed)

    def _performed(self, outcome):
        freed, errors = outcome
        title, text = self.done_text(freed, errors)
        if errors:
            text += f"\n{len(errors)} item(s) could not be processed:\n" + "\n".join(errors[:4])
        self.done_hero.title.set_text(title)
        self.done_hero.subtitle.set_text(text)
        self.set_visible_child_name("done")
        self.window.refresh_stats()

    def _failed(self, exc):
        info(self.window, "Something went wrong", str(exc), error=True)
        self.reset()
