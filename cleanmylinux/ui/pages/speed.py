"""Optimization (login items, heavy consumers) and Maintenance pages."""

import os

from gi.repository import Gio, GLib, GObject, Gtk, Pango

from ...core import system
from ...core.utils import human_size
from ..widgets import RoundButton, confirm, css_button, icon, idle, info, label, run_async


def page_header(icon_name, title, subtitle):
    head = Gtk.Box(spacing=16)
    head.pack_start(icon(icon_name, 64, "hero-icon"), False, False, 0)
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    texts.set_valign(Gtk.Align.CENTER)
    title_label = label(title, "result-title", xalign=0)
    sub = label(subtitle, "hero-subtitle", xalign=0, wrap=True)
    texts.pack_start(title_label, False, False, 0)
    texts.pack_start(sub, False, False, 0)
    head.pack_start(texts, True, True, 0)
    return head, sub


def app_icon(name, size=32):
    if name and os.path.isabs(name) and os.path.exists(name):
        image = Gtk.Image.new_from_gicon(Gio.FileIcon.new(Gio.File.new_for_path(name)), Gtk.IconSize.DND)
    else:
        image = Gtk.Image.new_from_gicon(
            Gio.ThemedIcon.new_with_default_fallbacks(name or "application-x-executable"), Gtk.IconSize.DND)
    image.set_pixel_size(size)
    return image


class OptimizationPage(Gtk.Box):
    page_id = "optimization"
    title = "Optimization"
    sidebar_icon = "system-run-symbolic"

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.window = window
        self.timer = None
        for side in ("start", "end"):
            getattr(self, f"set_margin_{side}")(28)
        self.set_margin_bottom(20)
        head, self.subtitle = page_header("system-run-symbolic", "Optimization",
                                          "Control which apps launch at login and find the ones "
                                          "hogging your CPU and memory.")
        self.pack_start(head, False, False, 0)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(stack=self.stack)
        switcher.get_style_context().add_class("tabs")
        self.pack_start(switcher, False, False, 0)

        # Login items
        self.login_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow()
        scroll.get_style_context().add_class("card")
        scroll.add(self.login_list)
        self.stack.add_titled(scroll, "login", "Login Items")

        # Heavy consumers: pid, name, user, cpu text, mem text, cpu, mem, owned
        self.proc_store = Gtk.ListStore(int, str, str, str, str, float, GObject.TYPE_INT64, bool)
        self.proc_view = Gtk.TreeView(model=self.proc_store)
        for title, col_id, sort_id, xalign, expand in (("Process", 1, 1, 0.0, True), ("User", 2, 2, 0.0, False),
                                                       ("CPU", 3, 5, 1.0, False), ("Memory", 4, 6, 1.0, False),
                                                       ("PID", 0, 0, 1.0, False)):
            cell = Gtk.CellRendererText(xalign=xalign, ellipsize=Pango.EllipsizeMode.END if expand else Pango.EllipsizeMode.NONE)
            column = Gtk.TreeViewColumn(title, cell, text=col_id)
            column.set_sort_column_id(sort_id)
            column.set_expand(expand)
            self.proc_view.append_column(column)
        proc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        proc_scroll = Gtk.ScrolledWindow()
        proc_scroll.get_style_context().add_class("card")
        proc_scroll.add(self.proc_view)
        proc_box.pack_start(proc_scroll, True, True, 0)
        buttons = Gtk.Box(spacing=8)
        buttons.set_halign(Gtk.Align.END)
        quit_button = css_button("Quit", "pill flat-pill small", "window-close-symbolic")
        quit_button.connect("clicked", lambda *_: self._stop(False))
        kill_button = css_button("Force Quit", "pill flat-pill small danger", "process-stop-symbolic")
        kill_button.connect("clicked", lambda *_: self._stop(True))
        buttons.pack_start(quit_button, False, False, 0)
        buttons.pack_start(kill_button, False, False, 0)
        proc_box.pack_start(buttons, False, False, 0)
        self.stack.add_titled(proc_box, "heavy", "Heavy Consumers")
        self.stack.connect("notify::visible-child-name", lambda *_: self._tick())
        self.pack_start(self.stack, True, True, 0)
        self.show_all()

    def on_shown(self):
        self.load_login_items()
        system.heavy_processes()  # prime CPU counters
        if self.timer is None:
            self.timer = GLib.timeout_add_seconds(2, self._tick)

    def on_hidden(self):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None

    def load_login_items(self):
        for row in self.login_list.get_children():
            self.login_list.remove(row)
        items = system.login_items()
        for item in items:
            row = Gtk.Box(spacing=12)
            for side in ("start", "end", "top", "bottom"):
                getattr(row, f"set_margin_{side}")(8)
            row.pack_start(app_icon(item.icon), False, False, 0)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            texts.set_valign(Gtk.Align.CENTER)
            texts.pack_start(label(f"<b>{GLib.markup_escape_text(item.name)}</b>", xalign=0, markup=True),
                             False, False, 0)
            comment = label(item.comment or item.command, "dim", xalign=0)
            comment.set_ellipsize(Pango.EllipsizeMode.END)
            texts.pack_start(comment, False, False, 0)
            row.pack_start(texts, True, True, 0)
            if item.user_only:
                remove = css_button("", "pill flat-pill small", "user-trash-symbolic")
                remove.set_tooltip_text("Remove this login item")
                remove.set_valign(Gtk.Align.CENTER)
                remove.connect("clicked", self._remove, item)
                row.pack_end(remove, False, False, 0)
            switch = Gtk.Switch(active=item.enabled, valign=Gtk.Align.CENTER)
            switch.connect("notify::active", self._switched, item)
            row.pack_end(switch, False, False, 0)
            self.login_list.add(row)
        self.login_list.show_all()
        enabled = sum(1 for i in items if i.enabled)
        self.subtitle.set_text(f"{enabled} of {len(items)} login items start automatically. "
                               "Disabling the ones you don't need speeds up login.")

    def _switched(self, switch, _pspec, item):
        try:
            system.set_login_item(item, switch.get_active())
        except OSError as exc:
            info(self.window, "Could not change login item", str(exc), error=True)
        GLib.idle_add(lambda: self.load_login_items() and False)

    def _remove(self, _button, item):
        if confirm(self.window, f"Remove “{item.name}” from login items?",
                   "The app itself is not uninstalled.", "Remove"):
            system.remove_login_item(item)
            self.load_login_items()

    def _tick(self):
        if self.stack.get_visible_child_name() != "heavy":
            return True
        selection = self.proc_view.get_selection()
        model, it = selection.get_selected()
        selected_pid = model[it][0] if it else None
        rows = system.heavy_processes()
        self.proc_store.clear()
        for pid, name, user, cpu, mem, owned in rows:
            it = self.proc_store.append([pid, name, user, f"{cpu:.1f}%", human_size(mem), cpu, mem, owned])
            if pid == selected_pid:
                selection.select_iter(it)
        return True

    def _stop(self, force):
        model, it = self.proc_view.get_selection().get_selected()
        if it is None:
            return
        pid, name = model[it][0], model[it][1]
        if force and not confirm(self.window, f"Force quit {name}?",
                                 "Unsaved changes in this app will be lost.", "Force Quit"):
            return
        try:
            system.stop_process(pid, force)
        except PermissionError:
            info(self.window, f"Cannot stop {name}", "This process belongs to another user or the system.",
                 error=True)
        except ProcessLookupError:
            pass
        GLib.timeout_add(500, lambda: self._tick() and False)


class MaintenancePage(Gtk.Box):
    page_id = "maintenance"
    title = "Maintenance"
    sidebar_icon = "preferences-system-symbolic"

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.window = window
        for side in ("start", "end"):
            getattr(self, f"set_margin_{side}")(28)
        self.set_margin_bottom(20)
        head, _ = page_header("preferences-system-symbolic", "Maintenance",
                              "Run a set of scripts that keep your system healthy and responsive. "
                              "Tasks marked 🔒 need your password once.")
        self.pack_start(head, False, False, 0)

        self.rows = {}
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        for task in system.TASKS:
            if not task.available:
                continue
            row = Gtk.Box(spacing=12)
            for side in ("start", "end", "top", "bottom"):
                getattr(row, f"set_margin_{side}")(8)
            check = Gtk.CheckButton(active=task.recommended, valign=Gtk.Align.CENTER)
            row.pack_start(check, False, False, 0)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            title = GLib.markup_escape_text(task.name) + ("  🔒" if task.needs_root else "")
            texts.pack_start(label(f"<b>{title}</b>", xalign=0, markup=True), False, False, 0)
            desc = label(task.description, "dim", xalign=0, wrap=True)
            texts.pack_start(desc, False, False, 0)
            row.pack_start(texts, True, True, 0)
            status = Gtk.Stack()
            spinner = Gtk.Spinner()
            status.add_named(Gtk.Box(), "idle")
            status.add_named(spinner, "running")
            status.add_named(icon("object-select-symbolic", 20, "ok-icon"), "ok")
            status.add_named(icon("dialog-error-symbolic", 20, "error-icon"), "error")
            row.pack_end(status, False, False, 0)
            listbox.add(row)
            self.rows[task.id] = (task, check, status, spinner, row)
        scroll = Gtk.ScrolledWindow()
        scroll.get_style_context().add_class("card")
        scroll.add(listbox)
        self.pack_start(scroll, True, True, 0)

        self.log = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.log.get_style_context().add_class("log")
        log_scroll = Gtk.ScrolledWindow(min_content_height=90)
        log_scroll.add(self.log)
        expander = Gtk.Expander(label="Details")
        expander.add(log_scroll)
        self.pack_start(expander, False, False, 0)

        self.button = RoundButton("Run")
        self.button.set_size_request(104, 104)
        self.button.connect("clicked", self._run)
        self.pack_start(self.button, False, False, 0)
        self.show_all()
        for _task, _check, status, _sp, _row in self.rows.values():
            status.set_visible_child_name("idle")

    def _append(self, text):
        buffer = self.log.get_buffer()
        buffer.insert(buffer.get_end_iter(), text + "\n")

    def _status(self, task, state, output):
        _task, _check, status, spinner, _row = self.rows[task.id]
        if state == "running":
            spinner.start()
        else:
            spinner.stop()
        status.set_visible_child_name(state)
        if output:
            self._append(f"[{task.name}] {output}")

    def _run(self, *_):
        tasks = [t for t, check, *_ in self.rows.values() if check.get_active()]
        if not tasks:
            return
        self.button.set_sensitive(False)
        self.log.get_buffer().set_text("")
        for task in tasks:
            self.rows[task.id][2].set_visible_child_name("idle")
        report = idle(self._status)
        run_async(lambda: system.run_tasks(tasks, report), self._finished,
                  lambda e: (info(self.window, "Maintenance failed", str(e), error=True), self._finished(None)))

    def _finished(self, _result):
        self.button.set_sensitive(True)
        self.button.set_text("Run", "Done")
        self.window.refresh_stats()
