# CleanMyLinux

A CleanMyMac-style system cleaner for Linux, built with Python and GTK 3.

## Features

| Module | What it does |
| --- | --- |
| **Smart Scan** | One-click scan: junk total, RAM, login items and disk health, then cleans the junk. |
| **System Junk** | User caches, browser caches (history, cookies and passwords are left alone), thumbnails, developer caches (pip, npm, cargo, gradle…), old logs, partial downloads and every Trash bin. Admin items: APT cache, systemd journal, rotated `/var/log` files, crash reports. |
| **Optimization** | Turn login items (`~/.config/autostart`, `/etc/xdg/autostart`) on or off, and quit apps that use the most CPU or memory. |
| **Maintenance** | Free RAM, `apt autoremove`, remove unused Flatpak runtimes, shrink the journal, rebuild the font cache, refresh the app database, reset thumbnails, repair broken packages, TRIM SSDs. |
| **Uninstaller** | Remove APT, Flatpak and Snap apps, plus data left behind by removed Flatpak apps. Before removing anything it shows every package APT would take with it. Essential packages are locked. |
| **Updater** | Check APT, Flatpak and Snap updates in one list, with security fixes flagged and download sizes shown, then install the ones you pick. Can refresh package lists first. The sidebar badge shows how many updates are pending. |
| **Space Lens** | A clickable treemap of any folder (or the whole disk) to find what is eating space. |
| **Large & Old Files** | Finds big files and files you haven't used in over a year, grouped by type. |
| **Duplicates** | Finds files that are byte-for-byte identical (by size, then a partial hash, then a full BLAKE2 hash). The oldest copy is always kept. |

## Safety

- Files you pick in Large Files, Duplicates and Space Lens go to the **Trash**. They are not deleted outright.
- Cache and Trash folders are emptied, not removed.
- A hard guard refuses to delete `/`, `$HOME`, `~/.config`, `~/.local` and other system roots.
- Admin tasks go through `pkexec` to a small helper (`cleanmylinux/core/helper.py`) that only accepts a fixed list of actions. You enter your password once per run.
- Login items are changed through per-user overrides. System files are never edited.

## Run

Requires `python3-gi`, `gir1.2-gtk-3.0` and `python3-psutil`. These come preinstalled on Linux Mint, Ubuntu and most GNOME/Cinnamon desktops.

```bash
./bin/cleanmylinux
```

## Install (per user, no root)

```bash
./install.sh
```

This adds CleanMyLinux to your app menu. To remove it, run `./install.sh --uninstall`.

## Layout

```
cleanmylinux/
  core/        scanners and cleaners (no GTK): junk, files, spacelens, apps, system, helper
  ui/          GTK window, pages and style.css
  data/        app icon
```
