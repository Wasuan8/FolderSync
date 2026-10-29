# 📁 FolderSync

**Keep an external drive perfectly in sync with your local project folder.**

FolderSync is a lightweight macOS desktop app that compares two directories,
shows you exactly what changed, and copies only the differences — fast, safe,
and in parallel.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-macOS-000000?logo=apple&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Features

| Feature | Description |
|---|---|
| **Two-step workflow** | Scan first → review changes → sync. Nothing happens without your approval. |
| **Parallel copying** | 4 worker threads copy files concurrently for maximum throughput. |
| **Safe writes** | Every file is written to a `.syncpart` temp file, then atomically renamed. An interrupted copy never corrupts the destination. |
| **Mirror mode** | Optionally delete files on the destination that no longer exist in the source — true one-way mirroring. |
| **Newer-file protection** | By default, files on the destination that are *newer* than the source are skipped (e.g. if you edited directly on the drive). |
| **Ignore patterns** | Exclude files and folders by glob pattern: `.DS_Store`, `node_modules`, `__pycache__`, etc. |
| **External drive alerts** | Background watcher detects when a USB/SSD drive is plugged in or ejected and shows a toast notification with a system sound. If the destination drive is ejected mid-sync, the operation is auto-cancelled. |
| **Dark theme UI** | Modern dark interface with card-based layout, colour-coded action labels, and a progress bar. |
| **Config persistence** | Source, destination, and all options are saved to `~/.foldersync.json` and restored on next launch. |

---

## 🗂️ Project Layout

```
FolderSync/
├── main.py          ← Entry point — run this file
├── config.py        ← Settings, constants, colour palette, saved paths
├── utils.py         ← Small helpers (file sizes, glob matching, validation)
├── scanner.py       ← Compares folders, decides WHAT to change (changes nothing)
├── syncer.py        ← Performs the copy / delete safely and in parallel
├── ui.py            ← The window (calls scanner + syncer, has no sync logic)
├── icon.icns        ← App icon for macOS bundle
├── FolderSync.spec  ← PyInstaller build spec
└── README.md        ← This file
```

### How the modules connect

```
main.py
  └─ ui.py (App window)
       ├─ config.py   — reads/writes settings
       ├─ utils.py    — human_size(), is_excluded(), validate_folder_pair()
       ├─ scanner.py  — scan_folders() → list of actions
       └─ syncer.py   — run_sync(actions) → executes copies & deletes
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+** (ships with macOS or install via [python.org](https://www.python.org))
- **Tkinter** (included with the standard Python installer on macOS)

### Run from source

```bash
cd FolderSync
python3 main.py
```

### Build a standalone .app

```bash
pip install pyinstaller
pyinstaller FolderSync.spec
```

The finished app bundle will be at `dist/FolderSync.app`. Drag it to your
Applications folder or run it directly.

One-liner build (without the spec file):

```bash
pyinstaller --windowed --noconfirm --name FolderSync main.py
```

---

## 🖥️ How to Use

1. **Pick folders** — Select your local project folder as the **Source** and a
   folder on your external drive as the **Destination**.
2. **Scan** — Click **🔍 Scan Changes**. The app walks both trees and shows a
   colour-coded preview:
   - 🟢 **New** — file exists only in the source
   - 🟡 **Update** — file changed (different size or timestamp)
   - 🔴 **Delete** — file exists only on the destination (mirror mode)
3. **Review** — Scroll through the list. The summary shows the count and total
   size.
4. **Sync** — Click **🚀 Sync Now**. Files are copied in parallel. A progress
   bar tracks the operation. You can cancel at any time.

### Options

| Option | Default | What it does |
|---|---|---|
| Protect newer files | ✅ On | Skips destination files that are newer than the source |
| Mirror mode | ❌ Off | Deletes destination files not present in the source |
| Ignore patterns | `.DS_Store, __pycache__, …` | Comma-separated glob patterns to skip |

---

## 🔌 External Drive Alerts

FolderSync watches `/Volumes` on macOS for drive mount/unmount events:

| Event | Notification |
|---|---|
| 🟢 Drive plugged in | Toast: *"Drive connected: MyDrive"* + system sound |
| 🟢 Destination drive returns | Toast: *"Your destination folder is available again"* |
| 🔴 Destination drive ejected mid-sync | Toast + **auto-cancel** of the running sync |
| 🟡 Other drive ejected | Toast: *"Drive disconnected: OtherDrive"* |

> **Note:** The volume watcher is macOS-only. On other platforms the app works
> normally but drive alerts are disabled.

---

## ⚙️ Configuration

Settings are saved to `~/.foldersync.json` automatically when you click Scan or
close the window. The file looks like:

```json
{
  "src": "/Users/you/Projects/MyApp",
  "dst": "/Volumes/BackupSSD/MyApp",
  "mirror": false,
  "protect": true,
  "exclude": ".DS_Store, __pycache__, node_modules, .Trash, *.syncpart"
}
```

Delete this file to reset all settings to defaults.

---

## 🧩 Architecture Notes

- **No sync logic in the UI** — `ui.py` calls `scanner.scan_folders()` and
  `syncer.run_sync()` on background threads and communicates via a
  `queue.Queue`. The Tk main loop polls the queue every 100 ms.

- **Atomic copies** — `syncer.copy_file()` writes to `file.syncpart`, then
  `os.replace()` atomically renames it. If power is lost mid-write, the
  `.syncpart` temp is cleaned up on the next run (it's in the default exclude
  list).

- **Thread pool** — File copies run on a `ThreadPoolExecutor` with 4 workers
  (configurable via `config.WORKERS`). Directory creation and deletion are
  sequential to avoid race conditions.

- **Cancellation** — A `threading.Event` is shared between the UI and the
  worker threads. Setting it aborts the scan or sync gracefully.

---

## 📄 License

MIT — use it however you like.

# FolderSync
