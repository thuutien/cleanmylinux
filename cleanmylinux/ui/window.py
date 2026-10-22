"""Main window: sidebar navigation + page stack + live system stats."""

import os

import psutil
from gi.repository import GLib, Gtk

from .. import __version__
from ..core.utils import HOME, ROOT_FS, human_size
from ..core import selfupdate, updates
from .pages.apps import UninstallerPage, UpdaterPage
from .pages.cleanup import JunkPage, SmartScanPage
from .pages.files import DuplicatesPage, LargeFilesPage
from .pages.spacelens import SpaceLensPage
from .pages.speed import MaintenancePage, OptimizationPage
from .widgets import icon, label, run_async

SECTIONS = [
    (None, [SmartScanPage]),
    ("Cleanup", [JunkPage]),
    ("Speed", [OptimizationPage, MaintenancePage]),
    ("Applications", [UninstallerPage, UpdaterPage]),
    ("Files", [SpaceLensPage, LargeFilesPage, DuplicatesPage]),
]
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


class Meter(Gtk.Box):
    def __init__(self, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        top = Gtk.Box()
        top.pack_start(label(title, "meter-title", xalign=0), True, True, 0)
        self.value = label("", "meter-value", xalign=1)
        top.pack_end(self.value, False, False, 0)
        self.pack_start(top, False, False, 0)
        self.bar = Gtk.LevelBar(min_value=0, max_value=1)
        self.bar.set_mode(Gtk.LevelBarMode.CONTINUOUS)
        for name in ("low", "high", "full"):
            self.bar.remove_offset_value(name)
        self.pack_start(self.bar, False, False, 0)

    def set(self, fraction, text):
        self.bar.set_value(max(0.0, min(fraction, 1.0)))
        self.value.set_text(text)
        context = self.bar.get_style_context()
        context.remove_class("hot") if fraction < 0.85 else context.add_class("hot")


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CleanMyLinux")
        self.set_default_size(1080, 720)
        self.set_size_request(900, 600)
        self.get_style_context().add_class("cml")
        icon_path = os.path.join(DATA_DIR, "cleanmylinux.svg")
        if os.path.exists(icon_path):
            self.set_icon_from_file(icon_path)

        header = Gtk.HeaderBar(show_close_button=True, title="CleanMyLinux")
        header.get_style_context().add_class("cml-header")
        self.settings = selfupdate.load_settings()
        menu = Gtk.Menu()
        check = Gtk.MenuItem(label="Check for Updates…")
        check.connect("activate", lambda *_: self.show_update_dialog())
        auto = Gtk.CheckMenuItem(label="Check for Updates at Startup",
                                 active=self.settings.get("auto_check", True))
        auto.connect("toggled", self._toggle_auto_check)
        about = Gtk.MenuItem(label="About CleanMyLinux")
        about.connect("activate", self._about)
        for item in (check, auto, Gtk.SeparatorMenuItem(), about):
            menu.append(item)
        menu.show_all()
        menu_button = Gtk.MenuButton(popup=menu, relief=Gtk.ReliefStyle.NONE)
        menu_button.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu_button.set_tooltip_text("Menu")
        header.pack_end(menu_button)
        # Shown when the startup check finds a newer release.
        self.release = None
        self.update_button = Gtk.Button(label="Update Available")
        self.update_button.get_style_context().add_class("update-available")
        self.update_button.set_no_show_all(True)
        self.update_button.connect("clicked", lambda *_: self.show_update_dialog(self.release))
        header.pack_end(self.update_button)
        self.set_titlebar(header)

        root = Gtk.Box()
        self.add(root)

        # Sidebar
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.get_style_context().add_class("sidebar")
        sidebar.set_size_request(230, -1)
        brand = Gtk.Box(spacing=10)
        brand.set_margin_start(18)
        brand.set_margin_top(6)
        brand.set_margin_bottom(14)
        logo = Gtk.Image()
        if os.path.exists(icon_path):
            from gi.repository import GdkPixbuf
            logo.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, 34, 34))
        brand.pack_start(logo, False, False, 0)
        brand.pack_start(label("CleanMyLinux", "brand", xalign=0), False, False, 0)
        sidebar.pack_start(brand, False, False, 0)

        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.get_style_context().add_class("nav")
        self.nav.set_header_func(self._nav_header)
        sidebar.pack_start(self.nav, True, True, 0)

        stats = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        stats.get_style_context().add_class("stats")
        self.cpu_meter = Meter("CPU")
        self.ram_meter = Meter("Memory")
        self.disk_meter = Meter("System disk")
        for meter in (self.cpu_meter, self.ram_meter, self.disk_meter):
            stats.pack_start(meter, False, False, 0)
        self.home_meter = None
        if os.stat(HOME).st_dev != os.stat(ROOT_FS).st_dev:
            self.home_meter = Meter("Home")
            stats.pack_start(self.home_meter, False, False, 0)
        sidebar.pack_end(stats, False, False, 0)
        root.pack_start(sidebar, False, False, 0)

        # Pages
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=180)
        self.stack.get_style_context().add_class("content")
        root.pack_start(self.stack, True, True, 0)
        self.pages = {}
        self.rows = {}
        for section, page_classes in SECTIONS:
            for cls in page_classes:
                page = cls(self)
                self.pages[cls.page_id] = page
                self.stack.add_named(page, cls.page_id)
                row = Gtk.ListBoxRow()
                row.section = section
                row.page_id = cls.page_id
                box = Gtk.Box(spacing=12)
                box.pack_start(icon(cls.sidebar_icon, 18), False, False, 0)
                box.pack_start(label(cls.title, xalign=0), False, False, 0)
                row.badge = label("", "nav-badge")
                row.badge.set_no_show_all(True)
                box.pack_end(row.badge, False, False, 0)
                row.add(box)
                self.nav.add(row)
                self.rows[cls.page_id] = row
        self.nav.connect("row-selected", self._row_selected)
        self.current = None
        self.show_all()
        self.show_page("smart")
        self.refresh_stats()
        psutil.cpu_percent(None)
        GLib.timeout_add_seconds(2, self.refresh_stats)
        self.refresh_update_badge()
        if self.settings.get("auto_check", True):
            run_async(selfupdate.fetch_latest, self.on_release_checked)  # errors stay silent

    def on_release_checked(self, release):
        self.release = release
        newer = selfupdate.is_newer(release.version)
        self.update_button.set_label(f"Update to {release.version}")
        self.update_button.set_visible(newer)

    def show_update_dialog(self, release=None):
        from .update_dialog import UpdateDialog
        UpdateDialog(self, release).show()

    def _toggle_auto_check(self, item):
        self.settings["auto_check"] = item.get_active()
        try:
            selfupdate.save_settings(self.settings)
        except OSError:
            pass

    def set_badge(self, page_id, count):
        badge = self.rows[page_id].badge
        badge.set_text(str(count))
        badge.set_visible(count > 0)

    def refresh_update_badge(self):
        run_async(updates.count_cached, lambda n: self.set_badge("updater", n))

    def _nav_header(self, row, before):
        if row.section and (before is None or before.section != row.section):
            header = label(row.section.upper(), "nav-header", xalign=0)
            row.set_header(header)
        else:
            row.set_header(None)

    def _row_selected(self, _list, row):
        if row is None:
            return
        page_id = row.page_id
        if self.current is not None:
            old = self.pages[self.current]
            if hasattr(old, "on_hidden"):
                old.on_hidden()
            self.get_style_context().remove_class(f"page-{self.current}")
        self.current = page_id
        self.get_style_context().add_class(f"page-{page_id}")
        self.stack.set_visible_child_name(page_id)
        page = self.pages[page_id]
        if hasattr(page, "on_shown"):
            page.on_shown()

    def show_page(self, page_id):
        self.nav.select_row(self.rows[page_id])

    def refresh_stats(self):
        cpu = psutil.cpu_percent(None)
        self.cpu_meter.set(cpu / 100, f"{cpu:.0f}%")
        mem = psutil.virtual_memory()
        self.ram_meter.set(mem.percent / 100, f"{human_size(mem.used)} / {human_size(mem.total)}")
        disk = psutil.disk_usage(ROOT_FS)
        self.disk_meter.set(disk.percent / 100, f"{human_size(disk.free)} free")
        if self.home_meter:
            home = psutil.disk_usage(HOME)
            self.home_meter.set(home.percent / 100, f"{human_size(home.free)} free")
        return True

    def _about(self, *_):
        dialog = Gtk.AboutDialog(transient_for=self, modal=True, program_name="CleanMyLinux",
                                 version=__version__, comments="Keep your Linux clean, fast and tidy.",
                                 license_type=Gtk.License.MIT_X11, logo_icon_name="edit-clear-all")
        icon_path = os.path.join(DATA_DIR, "cleanmylinux.svg")
        if os.path.exists(icon_path):
            from gi.repository import GdkPixbuf
            dialog.set_logo(GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, 96, 96))
        dialog.run()
        dialog.destroy()
