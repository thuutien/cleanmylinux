"""Build a size tree of a folder for the Space Lens view."""

import os

from .utils import Throttle

SMALL_FILE = 1000 * 1000
SKIP_ROOTS = {"/proc", "/sys", "/dev", "/run"}


class Node:
    __slots__ = ("name", "path", "size", "is_dir", "children", "parent", "count")

    def __init__(self, name, path, is_dir, parent=None):
        self.name = name
        self.path = path
        self.size = 0
        self.is_dir = is_dir
        self.children = []
        self.parent = parent
        self.count = 0

    @property
    def is_group(self):
        """True for the synthetic "small files" bucket, which cannot be removed."""
        return self.path is None

    def remove(self):
        """Detach this node and subtract its size from all ancestors."""
        if self.parent is None:
            return
        self.parent.children.remove(self)
        node = self.parent
        while node is not None:
            node.size -= self.size
            node.count -= self.count
            node = node.parent


def scan(root, progress=None, cancel=None):
    report = Throttle(progress, 0.1)
    try:
        root_dev = os.lstat(root).st_dev
    except OSError as exc:
        raise RuntimeError(f"Cannot read {root}: {exc}")
    top = Node(os.path.basename(root.rstrip("/")) or root, root, True)
    stats = {"files": 0}

    def visit(node, depth):
        small_size, small_count = 0, 0
        try:
            with os.scandir(node.path) as it:
                entries = list(it)
        except OSError:
            return
        for entry in entries:
            if cancel is not None and cancel.is_set():
                return
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.path in SKIP_ROOTS:
                        continue
                    if entry.stat(follow_symlinks=False).st_dev != root_dev:
                        continue
                    child = Node(entry.name, entry.path, True, node)
                    if depth < 400:
                        visit(child, depth + 1)
                    node.children.append(child)
                    node.size += child.size
                    node.count += child.count
                else:
                    size = entry.stat(follow_symlinks=False).st_size
                    stats["files"] += 1
                    node.size += size
                    node.count += 1
                    if size >= SMALL_FILE:
                        child = Node(entry.name, entry.path, False, node)
                        child.size, child.count = size, 1
                        node.children.append(child)
                    else:
                        small_size += size
                        small_count += 1
            except OSError:
                pass
        if small_count:
            group = Node(f"{small_count} smaller files", None, False, node)
            group.size, group.count = small_size, small_count
            node.children.append(group)
        node.children.sort(key=lambda n: -n.size)
        report(stats["files"], node.path)

    visit(top, 0)
    return top
