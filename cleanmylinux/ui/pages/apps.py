"""Uninstaller page."""

import os
import time

from gi.repository import Gio, GLib, GObject, Gtk, Pango

from ...core import apps, updates
from ...core.utils import human_age, human_size
from ..widgets import (CheckTree, RoundButton, ScanPage, confirm, css_button, esc, icon, info, label,
                       muted, run_async)

SOURCES = [("all", "All Applications"), ("apt", "System (APT)"), ("flatpak", "Flatpak"),
           ("snap", "Snap"), ("leftover", "Leftovers")]
BADGES = {"apt": "APT", "flatpak": "Flatpak", "snap": "Snap", "leftover": "Leftover"}


def _gicon(app):
    if app.desktop_file:
        try:
            info_ = (Gio.DesktopAppInfo.new_from_filename(app.desktop_file) if os.path.isabs(app.desktop_file)
                     else Gio.DesktopAppInfo.new(app.desktop_file))
            if info_ and info_.get_icon():
                return info_.get_icon()
        except TypeError:
            pass
    if app.icon:
        if os.path.isabs(app.icon) and os.path.exists(app.icon):
            return Gio.FileIcon.new(Gio.File.new_for_path(app.icon))
        return Gio.ThemedIcon.new_with_default_fallbacks(app.icon)
    return Gio.ThemedIcon.new("application-x-executable")


class UninstallerPage(Gtk.Box):
    page_id = "uninstaller"
    title = "Uninstaller"
    sidebar_icon = "package-x-generic-symbolic"

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.window = window
        self.apps = []
        self.loaded = False
        self.source = "all"
        for side in ("start", "end"):
            getattr(self, f"set_margin_{side}")(28)
        self.set_margin_bottom(20)

        head = Gtk.Box(spacing=16)
        head.pack_start(icon("package-x-generic-symbolic", 64, "hero-icon"), False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        texts.set_valign(Gtk.Align.CENTER)
        self.title_label = label("Uninstaller", "result-title", xalign=0)
        self.subtitle_label = label("Loading applications…", "hero-subtitle", xalign=0)
        texts.pack_start(self.title_label, False, False, 0)
        texts.pack_start(self.subtitle_label, False, False, 0)
        head.pack_start(texts, True, True, 0)
        self.search = Gtk.SearchEntry(placeholder_text="Search apps")
        self.search.set_valign(Gtk.Align.CENTER)
        self.search.connect("search-changed", lambda *_: self.filter.refilter())
        head.pack_end(self.search, False, False, 0)
        self.pack_start(head, False, False, 0)

        tabs = Gtk.Box(spacing=4)
        self.tab_buttons = {}
        group = None
        for key, text in SOURCES:
            button = Gtk.RadioButton.new_with_label_from_widget(group, text)
            button.set_mode(False)
            button.get_style_context().add_class("tab")
            button.connect("toggled", self._tab, key)
            group = group or button
            self.tab_buttons[key] = button
            tabs.pack_start(button, False, False, 0)
        refresh = css_button("", "pill flat-pill small", "view-refresh-symbolic")
        refresh.set_tooltip_text("Reload")
        refresh.connect("clicked", lambda *_: self.load())
        tabs.pack_end(refresh, False, False, 0)
        self.pack_start(tabs, False, False, 0)

        # selected, gicon, markup, badge, size text, size, app
        self.store = Gtk.ListStore(bool, Gio.Icon, str, str, str, GObject.TYPE_INT64, object)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        sorted_model = Gtk.TreeModelSort(model=self.filter)
        self.view = Gtk.TreeView(model=sorted_model)
        self.sorted_model = sorted_model
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self._toggled)
        self.view.append_column(Gtk.TreeViewColumn("", toggle, active=0))
        col = Gtk.TreeViewColumn("Application")
        pix = Gtk.CellRendererPixbuf(stock_size=Gtk.IconSize.DND)
        col.pack_start(pix, False)
        col.add_attribute(pix, "gicon", 1)
        text = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(text, True)
        col.add_attribute(text, "markup", 2)
        col.set_expand(True)
        col.set_sort_column_id(2)
        self.view.append_column(col)
        badge = Gtk.TreeViewColumn("Source", Gtk.CellRendererText(), text=3)
        badge.set_sort_column_id(3)
        self.view.append_column(badge)
        size = Gtk.TreeViewColumn("Size", Gtk.CellRendererText(xalign=1.0), text=4)
        size.set_sort_column_id(5)
        size.set_alignment(1.0)
        self.view.append_column(size)
        self.view.connect("row-activated", lambda v, p, c: self._toggled(None, p))
        scroll = Gtk.ScrolledWindow()
        scroll.get_style_context().add_class("card")
        scroll.add(self.view)
        self.pack_start(scroll, True, True, 0)

        footer = Gtk.Box(spacing=12)
        self.purge = Gtk.CheckButton(label="Also remove settings and app data")
        self.purge.get_style_context().add_class("option-label")
        footer.pack_start(self.purge, False, False, 0)
        self.button = RoundButton("Uninstall")
        self.button.set_size_request(104, 104)
        self.button.connect("clicked", self._uninstall)
        footer.set_center_widget(self.button)
        self.pack_start(footer, False, False, 0)
        self.show_all()
        self._update()

    def on_shown(self):
        if not self.loaded:
            self.load()

    def load(self):
        self.loaded = True
        self.subtitle_label.set_text("Loading applications…")
        run_async(apps.list_apps, self._loaded, lambda e: self.subtitle_label.set_text(str(e)))

    def _loaded(self, items):
        self.apps = items
        self.store.clear()
        for app in items:
            name = GLib.markup_escape_text(app.name)
            sub = GLib.markup_escape_text(f"{app.version}  ·  {app.summary}" if app.version else app.summary)
            if app.protected:
                sub = "🔒 Essential system package · " + sub
            self.store.append([False, _gicon(app), f"<b>{name}</b>\n<span alpha='60%' size='small'>{sub}</span>",
                               BADGES[app.source], human_size(app.size) if app.size else "—",
                               app.size, app])
        counts = {k: sum(1 for a in items if a.source == k) for k, _ in SOURCES}
        for key, text in SOURCES:
            n = len(items) if key == "all" else counts[key]
            self.tab_buttons[key].set_label(f"{text}  {n}")
            self.tab_buttons[key].set_visible(key == "all" or n > 0)
        self.filter.refilter()
        self._update()

    def _tab(self, button, key):
        if button.get_active():
            self.source = key
            self.filter.refilter()

    def _visible(self, model, it, _data):
        app = model[it][6]
        if app is None:
            return False
        if self.source != "all" and app.source != self.source:
            return False
        query = self.search.get_text().strip().lower()
        return not query or query in app.name.lower() or query in app.id.lower()

    def _toggled(self, _cell, path):
        sort_iter = self.sorted_model.get_iter(path)
        filter_iter = self.sorted_model.convert_iter_to_child_iter(sort_iter)
        it = self.filter.convert_iter_to_child_iter(filter_iter)
        app = self.store[it][6]
        if app.protected:
            info(self.window, f"{app.name} is part of the core system",
                 "Removing essential packages can make your system unbootable, so it is locked.")
            return
        app.selected = not app.selected
        self.store[it][0] = app.selected
        self._update()

    def _selected(self):
        return [a for a in self.apps if a.selected]

    def _update(self):
        chosen = self._selected()
        total = sum(a.size for a in self.apps)
        self.subtitle_label.set_text(
            f"{len(self.apps)} applications using {human_size(total)}" if self.apps else
            self.subtitle_label.get_text())
        size = sum(a.size for a in chosen)
        self.button.set_text("Uninstall" if not all(a.source == "leftover" for a in chosen) or not chosen
                             else "Remove", f"{len(chosen)} · {human_size(size)}" if chosen else "")
        self.button.set_sensitive(bool(chosen))

    def _uninstall(self, *_):
        chosen = self._selected()
        apt_ids = [a.id for a in chosen if a.source == "apt"]
        extra = []
        if apt_ids:
            removals = apps.simulate_apt_removal(apt_ids)
            extra = [p for p in removals if p not in apt_ids]
        lines = [f"• {a.name} ({BADGES[a.source]})" for a in chosen]
        if extra:
            lines += ["", "APT will also remove these dependent packages:"] + [f"  - {p}" for p in extra]
        warn = ""
        if len(extra) > 5:
            warn = f" Warning: {len(extra)} additional packages will be removed — review the list carefully."
        purge = self.purge.get_active()
        if not confirm(self.window, f"Uninstall {len(chosen)} item(s)?",
                       ("Their settings and data will also be deleted." if purge else
                        "Your personal settings will be kept.") + warn,
                       "Uninstall", details="\n".join(lines)):
            return
        self.button.set_sensitive(False)
        self.subtitle_label.set_text("Uninstalling… you may be asked for your password.")
        run_async(lambda: apps.uninstall(chosen, purge), self._done,
                  lambda e: info(self.window, "Uninstall failed", str(e), error=True))

    def _done(self, errors):
        if errors:
            info(self.window, "Some apps could not be removed", "\n".join(errors)[:1500], error=True)
        self.window.refresh_stats()
        self.load()


class UpdaterPage(ScanPage):
    page_id = "updater"
    title = "Updater"
    sidebar_icon = "software-update-available-symbolic"
    hero_icon = "software-update-available-symbolic"
    intro_title = "Updater"
    intro_text = ("Keep your system and apps up to date with the latest features, "
                  "bug fixes and security patches — APT, Flatpak and Snap in one place.")
    scan_label = "Check"
    action_label = "Update"
    working_label = "Installing updates…"

    def intro_extra(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.refresh = Gtk.CheckButton(label="Refresh package lists first (asks for your password)")
        self.refresh.get_style_context().add_class("option-label")
        self.refresh.set_halign(Gtk.Align.CENTER)
        age = updates.lists_age()
        self.refresh.set_active(age is None or age > 86400)
        box.pack_start(self.refresh, False, False, 0)
        when = "unknown" if age is None else human_age(time.time() - age).lower()
        box.pack_start(label(f"Package lists last refreshed: {when}", "dim"), False, False, 0)
        return box

    def scan(self, progress, cancel):
        return updates.check(self.refresh.get_active(), progress)

    def build_results(self, result):
        groups, self.check_errors = result
        self.groups = groups
        self.tree = CheckTree([("Update", True, 0.0), ("Download", False, 1.0)], self.refresh_summary)
        for group in groups:
            children = []
            for update in group.updates:
                version = f"{update.old}  →  {update.new}" if update.old else update.new
                badge = "  <span foreground='#ffb4c4' size='small' weight='bold'>SECURITY</span>" \
                    if update.security else ""
                children.append((update, "", [f"<b>{esc(update.name)}</b>{badge}\n{muted(version)}",
                                              human_size(update.size) if update.size else ""]))
            self.tree.add_group(group, group.icon,
                                [f"<b>{esc(group.name)}</b>  {muted(f"{len(group.updates)} update{'s' if len(group.updates) != 1 else ''}")}",
                                 f"<b>{human_size(group.size)}</b>" if group.size else ""], children)
        self.tree.view.expand_all()
        self.window.set_badge("updater", sum(len(g.updates) for g in groups))
        return self.tree

    def _selected(self):
        return [u for g in getattr(self, "groups", []) for u in g.updates if u.selected]

    def summary(self, result):
        groups, errors = result
        total = sum(len(g.updates) for g in groups)
        note = f" ({errors[0]})" if errors else ""
        if not total:
            return "Everything is up to date", "No updates are available right now." + note
        security = sum(u.security for g in groups for u in g.updates)
        sec = f", including {security} security fix{'es' if security != 1 else ''}" if security else ""
        return f"{total} update{'s' if total != 1 else ''} available", f"Review and install them{sec}.{note}"

    def selected_size(self):
        return sum(u.size for u in self._selected())

    def action_state(self):
        chosen = self._selected()
        size = self.selected_size()
        sub = f"{len(chosen)} items" + (f" · {human_size(size)}" if size else "")
        return bool(chosen), sub if chosen else ""

    def perform(self, progress):
        return updates.install(self._selected(), progress)

    def done_text(self, count, errors):
        self.window.refresh_update_badge()
        if not count:
            return "No updates installed", "Nothing was changed."
        return "Up to date", f"{count} update{'s' if count != 1 else ''} installed successfully."
