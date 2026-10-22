"""Large & old files and duplicate finder."""

import hashlib
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field

from .utils import HOME, Throttle, move_to_trash, walk_files

KINDS = {
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg", ".ts"},
    "Audio": {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".opus", ".wma"},
    "Pictures": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".bmp", ".raw", ".cr2", ".nef", ".heic", ".psd", ".xcf"},
    "Archives": {".zip", ".tar", ".gz", ".tgz", ".xz", ".bz2", ".7z", ".rar", ".zst", ".deb", ".rpm", ".appimage"},
    "Disk Images": {".iso", ".img", ".qcow2", ".vdi", ".vmdk", ".vhd", ".vhdx", ".dmg"},
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp", ".epub", ".csv", ".txt"},
}
KIND_ICONS = {
    "Videos": "video-x-generic-symbolic", "Audio": "audio-x-generic-symbolic",
    "Pictures": "image-x-generic-symbolic", "Archives": "package-x-generic-symbolic",
    "Disk Images": "drive-harddisk-symbolic", "Documents": "text-x-generic-symbolic",
    "Other": "application-x-executable-symbolic",
}
DEFAULT_SKIP = [os.path.join(HOME, d) for d in (".cache", ".local/share/Trash", ".var")]


def kind_of(path):
    ext = os.path.splitext(path)[1].lower()
    for kind, exts in KINDS.items():
        if ext in exts:
            return kind
    return "Other"


@dataclass
class FileEntry:
    path: str
    size: int
    mtime: float
    atime: float
    selected: bool = False

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def folder(self):
        return os.path.dirname(self.path).replace(HOME, "~", 1)

    @property
    def last_used(self):
        return max(self.mtime, self.atime)


@dataclass
class FileGroup:
    name: str
    icon: str
    files: list = field(default_factory=list)

    @property
    def size(self):
        return sum(f.size for f in self.files)


def find_large_old(roots=(HOME,), min_size=50 * 1000 * 1000, old_days=365,
                   skip_hidden=True, progress=None, cancel=None):
    """Find files >= min_size. Files untouched for old_days are grouped separately."""
    report = Throttle(progress)
    found = []
    for root in roots:
        for path, st in walk_files(root, cancel, skip_hidden, DEFAULT_SKIP,
                                   on_dir=lambda d: report(d.replace(HOME, "~", 1))):
            if st.st_size >= min_size:
                found.append(FileEntry(path, st.st_size, st.st_mtime, st.st_atime))
    old_cutoff = time.time() - old_days * 86400
    groups = {}
    for entry in sorted(found, key=lambda f: -f.size):
        kind = "Old Files (1+ year unused)" if entry.last_used < old_cutoff else kind_of(entry.path)
        icon = "document-open-recent-symbolic" if kind.startswith("Old") else KIND_ICONS[kind]
        groups.setdefault(kind, FileGroup(kind, icon)).files.append(entry)
    return sorted(groups.values(), key=lambda g: -g.size)


def _hash(path, limit=None, chunk=1 << 20):
    h = hashlib.blake2b(digest_size=20)
    read = 0
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk if limit is None else min(chunk, limit - read))
            if not block:
                break
            h.update(block)
            read += len(block)
            if limit is not None and read >= limit:
                break
    return h.hexdigest()


def find_duplicates(roots=(HOME,), min_size=100 * 1000, skip_hidden=True,
                    progress=None, cancel=None):
    """Group identical files: size, then first 64 KB, then full content."""
    report = Throttle(progress)
    by_size = defaultdict(list)
    seen_inodes = set()
    for root in roots:
        for path, st in walk_files(root, cancel, skip_hidden, DEFAULT_SKIP,
                                   on_dir=lambda d: report(f"Indexing {d.replace(HOME, '~', 1)}", 0.0)):
            if st.st_size < min_size:
                continue
            key = (st.st_dev, st.st_ino)
            if key in seen_inodes:  # hard links are not real duplicates
                continue
            seen_inodes.add(key)
            by_size[st.st_size].append(FileEntry(path, st.st_size, st.st_mtime, st.st_atime))

    candidates = [files for files in by_size.values() if len(files) > 1]
    total = sum(len(c) for c in candidates) or 1
    done = 0
    groups = []
    for files in candidates:
        if cancel is not None and cancel.is_set():
            break
        partial = defaultdict(list)
        for entry in files:
            done += 1
            report(f"Comparing {entry.name}", done / total)
            try:
                partial[_hash(entry.path, 64 * 1024)].append(entry)
            except OSError:
                pass
        for same_start in partial.values():
            if len(same_start) < 2:
                continue
            full = defaultdict(list)
            for entry in same_start:
                try:
                    digest = same_start[0].size <= 64 * 1024 or _hash(entry.path)
                    full[digest].append(entry)
                except OSError:
                    pass
            for dupes in full.values():
                if len(dupes) > 1:
                    # Keep the oldest copy; pre-select the rest.
                    dupes.sort(key=lambda f: (f.mtime, len(f.path)))
                    for extra in dupes[1:]:
                        extra.selected = True
                    groups.append(FileGroup(dupes[0].name, KIND_ICONS[kind_of(dupes[0].path)], dupes))
    groups.sort(key=lambda g: -(g.size - g.files[0].size))
    return groups


def trash_files(entries, progress=None):
    """Move entries to the Trash. Returns (freed_bytes, errors)."""
    report = Throttle(progress)
    freed, errors = 0, []
    for index, entry in enumerate(entries):
        report(f"Moving {entry.name} to Trash…", index / max(len(entries), 1))
        try:
            move_to_trash(entry.path)
            freed += entry.size
        except Exception as exc:
            errors.append(f"{entry.name}: {exc}")
    return freed, errors
