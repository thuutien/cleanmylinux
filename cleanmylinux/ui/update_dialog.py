"""Check for, download and install new CleanMyLinux releases."""

import re

from gi.repository import GLib, Gtk

from .. import __version__
from ..core import selfupdate
from .widgets import icon, idle, label, run_async

METHOD_HINTS = {
    "manual": "You are running CleanMyLinux from source. Update it with git pull, "
              "or install a package from the release page.",
    "package": "CleanMyLinux was installed by your package manager. Update it there.",
}


def markdown_markup(text):
    """Render the small Markdown subset used in release notes as Pango markup."""
    lines = []
    for raw in text.strip().splitlines():
        line = GLib.markup_escape_text(raw.rstrip())
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"`([^`]+)`", r"<tt>\1</tt>", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        heading = re.match(r"#+\s+(.*)", line)
        if heading:
            line = f"<b><big>{heading.group(1)}</big></b>"
        elif re.match(r"\s*[-*]\s+", line):
            indent = "    " if line.startswith(" ") else ""
            line = indent + "•  " + re.sub(r"^\s*[-*]\s+", "", line)
        lines.append(line)
    return "\n".join(lines)


class UpdateDialog(Gtk.Dialog):
    def __init__(self, window, release=None):
        super().__init__(title="Software Update", transient_for=window, modal=True)
        self.main_window = window
        self.release = release
        self.set_default_size(520, -1)
        self.set_resizable(False)
        self.close_button = self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.action_button = self.add_button("", Gtk.ResponseType.APPLY)
        self.action_button.get_style_context().add_class("suggested-action")
        self.connect("response", self._response)

        area = self.get_content_area()
        area.set_spacing(10)
        for side in ("start", "end", "top", "bottom"):
            getattr(area, f"set_margin_{side}")(18)
        head = Gtk.Box(spacing=14)
        self.spinner = Gtk.Spinner()
        self.icon = icon("software-update-available-symbolic", 48)
        head.pack_start(self.icon, False, False, 0)
        head.pack_start(self.spinner, False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        texts.set_valign(Gtk.Align.CENTER)
        self.title_label = label("", xalign=0)
        self.title_label.get_style_context().add_class("update-title")
        self.detail_label = label("", xalign=0, wrap=True)
        self.detail_label.set_max_width_chars(50)
        texts.pack_start(self.title_label, False, False, 0)
        texts.pack_start(self.detail_label, False, False, 0)
        head.pack_start(texts, True, True, 0)
        area.pack_start(head, False, False, 0)

        self.notes = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD,
                                  left_margin=10, right_margin=10, top_margin=8, bottom_margin=8)
        self.notes_scroll = Gtk.ScrolledWindow(min_content_height=200, max_content_height=320)
        self.notes_scroll.set_propagate_natural_height(True)
        self.notes_scroll.set_shadow_type(Gtk.ShadowType.IN)
        self.notes_scroll.add(self.notes)
        area.pack_start(self.notes_scroll, True, True, 0)
        self.progress = Gtk.ProgressBar(show_text=False)
        area.pack_start(self.progress, False, False, 0)
        area.show_all()

        if release is None:
            self.check()
        else:
            self._checked(release)

    # -- states ------------------------------------------------------------
    def _state(self, title, detail="", busy=False, action=None, notes=None, progress=False):
        self.title_label.set_markup(f"<b><big>{title}</big></b>")
        self.detail_label.set_text(detail)
        self.spinner.set_visible(busy)
        self.icon.set_visible(not busy)
        (self.spinner.start if busy else self.spinner.stop)()
        self.action_button.set_visible(action is not None)
        if action:
            self.action_button.set_label(action)
        self.notes_scroll.set_visible(bool(notes))
        if notes:
            buffer = self.notes.get_buffer()
            buffer.set_text("")
            buffer.insert_markup(buffer.get_start_iter(), markdown_markup(notes), -1)
        self.progress.set_visible(progress)
        self.close_button.set_sensitive(not busy)
        self.mode = action

    def check(self):
        self._state("Checking for updates…", busy=True)
        run_async(selfupdate.fetch_latest, self._checked,
                  lambda exc: self._state("Couldn't check for updates",
                                          f"{exc}. Check your internet connection.", action="Try Again"))

    def _checked(self, release):
        self.release = release
        self.main_window.on_release_checked(release)
        if not selfupdate.is_newer(release.version):
            self._state("You're up to date", f"CleanMyLinux {__version__} is the latest version.")
            return
        method = selfupdate.install_method()
        can_install = selfupdate.asset_for(release, method) is not None
        detail = f"You have version {__version__}."
        if not can_install:
            detail += " " + METHOD_HINTS.get(method, "Download it from the release page.")
        self._state(f"CleanMyLinux {release.version} is available", detail,
                    action=f"Install {release.version}" if can_install else "Open Download Page",
                    notes=release.notes)

    def _install(self):
        method = selfupdate.install_method()
        hint = "" if method == "flatpak" else " You may be asked for your password."
        self._state(f"Installing CleanMyLinux {self.release.version}…", "Downloading…" + hint,
                    busy=True, progress=True)
        self.progress.set_fraction(0)
        report = idle(lambda fraction: (self.progress.set_fraction(fraction),
                                        self.detail_label.set_text(f"Downloading… {fraction:.0%}" + hint)))
        run_async(lambda: selfupdate.install(self.release, report), self._installed,
                  lambda exc: self._state("Update failed", str(exc), action="Try Again"))

    def _installed(self, outcome):
        ok, output = outcome
        if ok:
            self._state(f"Updated to {self.release.version}",
                        "Restart CleanMyLinux to start using the new version.", action="Restart Now")
        else:
            self._state("Update failed", output.splitlines()[-1] if output else "The installer failed.",
                        action="Try Again")

    def _response(self, _dialog, response):
        if response != Gtk.ResponseType.APPLY:
            self.destroy()
            return
        mode = self.mode or ""
        if mode == "Try Again":
            self.check()
        elif mode.startswith("Install"):
            self._install()
        elif mode == "Open Download Page":
            Gtk.show_uri_on_window(self.main_window, self.release.url, 0)
        elif mode == "Restart Now":
            self.main_window.get_application().restart()
