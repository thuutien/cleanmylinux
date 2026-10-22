"""Large & Old Files and Duplicates pages."""

import os

from gi.repository import Gtk

from ...core import files
from ...core.utils import HOME, human_age, human_size
from ..widgets import CheckTree, ScanPage, confirm, css_button, esc, label, muted


class FolderPicker(Gtk.Box):
    """Shows the folders to scan plus a few options."""

    def __init__(self, window, min_sizes, default_index):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.window = window
        self.roots = [HOME]
        row = Gtk.Box(spacing=8)
        row.set_halign(Gtk.Align.CENTER)
        self.folder_label = label("", "chip")
        row.pack_start(self.folder_label, False, False, 0)
        change = css_button("Change…", "pill flat-pill small", "folder-symbolic")
        change.connect("clicked", self._choose)
        row.pack_start(change, False, False, 0)
        self.pack_start(row, False, False, 0)

        opts = Gtk.Box(spacing=10)
        opts.set_halign(Gtk.Align.CENTER)
        opts.pack_start(label("Minimum size", "option-label"), False, False, 0)
        self.size_combo = Gtk.ComboBoxText()
        for text, _ in min_sizes:
            self.size_combo.append_text(text)
        self.size_combo.set_active(default_index)
        self.min_sizes = min_sizes
        opts.pack_start(self.size_combo, False, False, 0)
        self.hidden = Gtk.CheckButton(label="Include hidden folders")
        self.hidden.get_style_context().add_class("option-label")
        opts.pack_start(self.hidden, False, False, 8)
        self.pack_start(opts, False, False, 0)
        self._update()

    @property
    def min_size(self):
        return self.min_sizes[self.size_combo.get_active()][1]

    @property
    def skip_hidden(self):
        return not self.hidden.get_active()

    def _update(self):
        self.folder_label.set_text(", ".join(r.replace(HOME, "~", 1) or "/" for r in self.roots))

    def _choose(self, *_):
        dialog = Gtk.FileChooserNative.new("Choose folders to scan", self.window,
                                           Gtk.FileChooserAction.SELECT_FOLDER, "Select", "Cancel")
        dialog.set_select_multiple(True)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            self.roots = [f.get_path() for f in dialog.get_files() if f.get_path()] or [HOME]
            self._update()
        dialog.destroy()


def file_texts(entry):
    return [f"{esc(entry.name)}\n{muted(entry.folder)}", human_age(entry.last_used), human_size(entry.size)]


class LargeFilesPage(ScanPage):
    page_id = "large"
    title = "Large & Old Files"
    sidebar_icon = "folder-saved-search-symbolic"
    hero_icon = "folder-saved-search-symbolic"
    intro_title = "Large & Old Files"
    intro_text = ("Locate big files and files you haven't opened in a long time. "
                  "Review them and move the ones you don't need to the Trash.")
    action_label = "Remove"
    working_label = "Moving to Trash…"

    def intro_extra(self):
        self.picker = FolderPicker(self.window, [("10 MB", 10e6), ("50 MB", 50e6), ("100 MB", 100e6),
                                                 ("500 MB", 500e6), ("1 GB", 1e9)], 1)
        return self.picker

    def scan(self, progress, cancel):
        return files.find_large_old(self.picker.roots, self.picker.min_size,
                                    skip_hidden=self.picker.skip_hidden, progress=progress, cancel=cancel)

    def build_results(self, groups):
        self.tree = CheckTree([("File", True, 0.0), ("Last used", False, 1.0), ("Size", False, 1.0)],
                              self.refresh_summary)
        for group in groups:
            children = [(f, "", file_texts(f)) for f in group.files]
            self.tree.add_group(group, group.icon, [f"<b>{esc(group.name)}</b>  {muted(f'{len(group.files)} files')}",
                                                    "", f"<b>{human_size(group.size)}</b>"], children)
        self.tree.view.connect("row-activated", self._open)
        return self.tree

    def _open(self, view, path, _col):
        obj = self.tree.store[path][0]
        if isinstance(obj, files.FileEntry):
            Gtk.show_uri_on_window(self.window, "file://" + os.path.dirname(obj.path), 0)

    def _selected(self):
        return [f for g in self.result or [] for f in g.files if f.selected]

    def summary(self, groups):
        count = sum(len(g.files) for g in groups)
        if not count:
            return "No large files found", "Try a smaller minimum size or another folder."
        return (f"{count} large files · {human_size(sum(g.size for g in groups))}",
                "Select files to move to the Trash. Double-click a file to open its folder.")

    def selected_size(self):
        return sum(f.size for f in self._selected())

    def confirm_action(self):
        chosen = self._selected()
        return confirm(self.window, f"Move {len(chosen)} files to the Trash?",
                       f"{human_size(self.selected_size())} will be moved to the Trash. "
                       "You can restore them until you empty it.", "Move to Trash")

    def perform(self, progress):
        return files.trash_files(self._selected(), progress)

    def done_text(self, freed, errors):
        return "Files removed", f"{human_size(freed)} moved to the Trash. Empty it to reclaim the space."


class DuplicatesPage(ScanPage):
    page_id = "duplicates"
    title = "Duplicates"
    sidebar_icon = "edit-copy-symbolic"
    hero_icon = "edit-copy-symbolic"
    intro_title = "Duplicate Finder"
    intro_text = ("Find identical copies of files, byte for byte. The oldest copy is "
                  "always kept; the rest are pre-selected for removal.")
    action_label = "Remove"
    working_label = "Moving to Trash…"

    def intro_extra(self):
        self.picker = FolderPicker(self.window, [("Any size", 1), ("100 KB", 1e5), ("1 MB", 1e6),
                                                 ("10 MB", 1e7)], 1)
        return self.picker

    def scan(self, progress, cancel):
        return files.find_duplicates(self.picker.roots, self.picker.min_size,
                                     skip_hidden=self.picker.skip_hidden, progress=progress, cancel=cancel)

    @staticmethod
    def _group_toggle(group, entries, value):
        # Never select every copy: the first (oldest) stays when selecting the group.
        for index, entry in enumerate(entries):
            entry.selected = value and index > 0

    def build_results(self, groups):
        self.tree = CheckTree([("File", True, 0.0), ("Modified", False, 1.0), ("Size", False, 1.0)],
                              self.refresh_summary, self._group_toggle)
        for group in groups:
            children = [(f, "", [f"{esc(f.name)}\n{muted(f.folder)}", human_age(f.mtime), human_size(f.size)])
                        for f in group.files]
            wasted = group.size - group.files[0].size
            self.tree.add_group(group, group.icon,
                                [f"<b>{esc(group.name)}</b>  {muted(f'{len(group.files)} copies')}",
                                 "", f"<b>{human_size(wasted)}</b>"], children)
        return self.tree

    def _selected(self):
        chosen = []
        for group in self.result or []:
            picked = [f for f in group.files if f.selected]
            if len(picked) == len(group.files):  # keep at least one copy
                picked = picked[1:]
            chosen += picked
        return chosen

    def summary(self, groups):
        if not groups:
            return "No duplicates found", "Every file in the scanned folders is unique."
        wasted = sum(g.size - g.files[0].size for g in groups)
        return (f"{len(groups)} sets of duplicates · {human_size(wasted)} wasted",
                "One copy of each file is always kept, even if every copy is ticked.")

    def selected_size(self):
        return sum(f.size for f in self._selected())

    def confirm_action(self):
        return confirm(self.window, f"Move {len(self._selected())} duplicates to the Trash?",
                       f"{human_size(self.selected_size())} will be moved to the Trash.", "Move to Trash")

    def perform(self, progress):
        return files.trash_files(self._selected(), progress)

    def done_text(self, freed, errors):
        return "Duplicates removed", f"{human_size(freed)} moved to the Trash."
