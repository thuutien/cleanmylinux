"""Gtk.Application entry point."""

import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from ..core import host  # noqa: E402
from .window import MainWindow  # noqa: E402

CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")


class CleanMyLinux(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.thuutien.CleanMyLinux", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None
        self.restart_command = None

    def restart(self):
        """Quit, then start the freshly installed version (see main)."""
        from ..core import selfupdate
        self.restart_command = selfupdate.restart_command()
        self.quit()

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        if host.FLATPAK:  # let the Uninstaller show icons of host apps
            theme = Gtk.IconTheme.get_default()
            for path in ("/run/host/usr/share/icons", "/run/host/usr/share/pixmaps"):
                theme.append_search_path(path)
        provider = Gtk.CssProvider()
        provider.load_from_path(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()


def main():
    GLib.set_application_name("CleanMyLinux")
    GLib.set_prgname("cleanmylinux")
    app = CleanMyLinux()
    status = app.run(sys.argv[:1])
    if app.restart_command:
        # Replacing the process drops our D-Bus name, so the new copy starts fresh.
        os.execvp(app.restart_command[0], app.restart_command)
    return status
