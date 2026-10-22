"""Gtk.Application entry point."""

import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .window import MainWindow  # noqa: E402

CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")


class CleanMyLinux(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.cleanmylinux", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
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
    return CleanMyLinux().run(sys.argv[:1])
