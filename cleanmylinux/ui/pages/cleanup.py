"""Smart Scan and System Junk pages."""

import psutil
from gi.repository import Gtk

from ...core import junk, system
from ...core.utils import HOME, human_size
from ..widgets import CheckTree, ScanPage, css_button, esc, icon, label, muted


def junk_tree(categories, on_changed):
    tree = CheckTree([("Item", True, 0.0), ("Size", False, 1.0)], on_changed)
    for cat in categories:
        badge = "  <span size='small' alpha='70%'>🔒 admin</span>" if cat.needs_root else ""
        children = [(item, "", [f"{esc(item.label)}\n{muted(item.detail.replace(HOME, '~', 1))}"
                                if item.detail else esc(item.label), human_size(item.size)])
                    for item in cat.items]
        tree.add_group(cat, cat.icon, [f"<b>{esc(cat.name)}</b>{badge}\n{muted(cat.description)}",
                                       f"<b>{human_size(cat.size)}</b>"], children)
    return tree


class JunkPage(ScanPage):
    page_id = "junk"
    title = "System Junk"
    sidebar_icon = "edit-clear-all-symbolic"
    hero_icon = "edit-clear-all-symbolic"
    intro_title = "System Junk"
    intro_text = ("Clean caches, logs, thumbnails, package leftovers and Trash "
                  "to free up space and keep your system tidy.")

    def scan(self, progress, cancel):
        return junk.scan(progress, cancel)

    def build_results(self, categories):
        self.tree = junk_tree(categories, self.refresh_summary)
        select = css_button("Select All", "pill flat-pill small")
        select.connect("clicked", lambda *_: self.tree.set_all(True))
        none = css_button("Deselect", "pill flat-pill small")
        none.connect("clicked", lambda *_: self.tree.set_all(False))
        self.header_tools.pack_start(select, False, False, 0)
        self.header_tools.pack_start(none, False, False, 0)
        return self.tree

    def summary(self, categories):
        total = sum(c.size for c in categories)
        if not total:
            return "Your system is already clean", "Nothing worth removing was found."
        return (f"{human_size(total)} of junk found",
                f"{human_size(self.selected_size())} selected for cleaning. "
                "Expand a category to review individual items.")

    def selected_size(self):
        return sum(c.selected_size for c in self.result or [])

    def perform(self, progress):
        return junk.clean(self.result, progress)

    def done_text(self, freed, errors):
        return "Cleanup complete", f"{human_size(freed)} of junk removed."


class SmartScanPage(ScanPage):
    page_id = "smart"
    title = "Smart Scan"
    sidebar_icon = "starred-symbolic"
    hero_icon = "weather-clear-symbolic"
    intro_title = "Welcome to CleanMyLinux"
    intro_text = ("Start a comprehensive scan to find junk, check your system's health "
                  "and spot what slows your computer down.")
    action_label = "Run"
    working_label = "Running tasks…"

    def scan(self, progress, cancel):
        categories = junk.scan(progress, cancel)
        progress("Checking system health…", 0.95)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        home = psutil.disk_usage(HOME)
        items = system.login_items()
        heavy = [p for p in system.heavy_processes(200) if p[4] > 500 * 1000 * 1000]
        return {
            "junk": categories, "mem": mem, "disk": disk, "home": home,
            "login": sum(1 for i in items if i.enabled), "heavy": heavy,
        }

    def _tile(self, icon_name, title, value, detail, page_id):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("tile")
        box.pack_start(icon(icon_name, 48, "hero-icon"), False, False, 4)
        box.pack_start(label(title, "tile-title"), False, False, 0)
        box.pack_start(label(value, "tile-value"), False, False, 0)
        detail_label = label(detail, "tile-detail", wrap=True)
        detail_label.set_max_width_chars(26)
        box.pack_start(detail_label, True, True, 0)
        review = css_button("Review", "pill flat-pill small")
        review.set_halign(Gtk.Align.CENTER)
        review.connect("clicked", lambda *_: self.window.show_page(page_id))
        box.pack_end(review, False, False, 4)
        return box

    def build_results(self, result):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        tiles = Gtk.Box(spacing=16, homogeneous=True)
        junk_total = sum(c.size for c in result["junk"])
        tiles.pack_start(self._tile("edit-clear-all-symbolic", "Cleanup", human_size(junk_total),
                                    f"of junk across {len(result['junk'])} categories", "junk"), True, True, 0)
        mem = result["mem"]
        heavy = result["heavy"]
        tiles.pack_start(self._tile("system-run-symbolic", "Speed", f"{mem.percent:.0f}% RAM",
                                    f"{result['login']} login items, {len(heavy)} using 500 MB+ memory",
                                    "optimization"), True, True, 0)
        disk = result["disk"]
        tiles.pack_start(self._tile("drive-harddisk-symbolic", "Storage", f"{human_size(disk.free)} free",
                                    f"{disk.percent:.0f}% of your system disk is used", "spacelens"),
                         True, True, 0)
        outer.pack_start(tiles, False, False, 0)
        outer.pack_start(label("Junk to be cleaned when you press Run:", "section-label", xalign=0),
                         False, False, 0)
        self.tree = junk_tree(result["junk"], self.refresh_summary)
        outer.pack_start(self.tree, True, True, 0)
        return outer

    def summary(self, result):
        return "Scan complete", "Here is what we found. Press Run to clean the selected junk."

    def selected_size(self):
        return sum(c.selected_size for c in (self.result or {}).get("junk", []))

    def perform(self, progress):
        return junk.clean(self.result["junk"], progress)

    def done_text(self, freed, errors):
        return "Your Linux is clean", f"{human_size(freed)} freed. Everything looks great!"
