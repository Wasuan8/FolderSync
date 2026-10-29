"""
config.py — Settings, constants, colour palette, and persisted user preferences.

Everything the app needs to know at startup lives here.
No logic, no UI — just values.
"""

from __future__ import annotations

import json
import os

# ── App identity ─────────────────────────────────────────────────────────────

APP_NAME = "FolderSync"
APP_VERSION = "2.0"

# ── Paths ────────────────────────────────────────────────────────────────────

CONFIG_FILE = os.path.expanduser("~/.foldersync.json")

# ── Sync defaults ────────────────────────────────────────────────────────────

DEFAULT_EXCLUDES = ".DS_Store, __pycache__, node_modules, .Trash, *.syncpart"
MTIME_TOLERANCE = 2.0   # seconds — exFAT / FAT32 timestamp granularity
WORKERS = 4              # parallel copy threads
MAX_ROWS = 3000          # max rows shown in the preview table
VOLUME_POLL_SEC = 2      # how often we poll /Volumes for drive changes

# ── Colour palette (dark mode) ───────────────────────────────────────────────

C_BG = "#1e1e2e"           # main background
C_BG_CARD = "#2a2a3c"      # card / section background
C_BG_ENTRY = "#363649"     # entry field background
C_BG_HOVER = "#3a3a50"     # hover state
C_FG = "#e0e0f0"           # primary text
C_FG_DIM = "#9090a8"       # secondary / muted text
C_ACCENT = "#7c6ff7"       # accent / primary buttons
C_ACCENT_HOVER = "#6b5ce6" # accent hover
C_GREEN = "#34d399"        # new / success
C_AMBER = "#fbbf24"        # update / warning
C_RED = "#f87171"          # delete / error
C_BORDER = "#3f3f5c"       # subtle borders
C_TOAST_BG = "#323248"     # toast notification background

# ── Icons (Unicode) ──────────────────────────────────────────────────────────

ICO_FOLDER = "📁"
ICO_SRC = "💻"
ICO_DST = "💾"
ICO_SCAN = "🔍"
ICO_SYNC = "🚀"
ICO_CANCEL = "✕"
ICO_SWAP = "⇄"
ICO_NEW = "✚"
ICO_UPDATE = "↻"
ICO_DELETE = "✖"
ICO_CHECK = "✓"
ICO_USB = "🔌"
ICO_EJECT = "⏏"
ICO_WARN = "⚠"


# ── Config persistence ──────────────────────────────────────────────────────

def load_config() -> dict:
    """
    Load saved user settings from disk.

    Returns a dict with keys: src, dst, mirror, protect, exclude.
    Falls back to safe defaults on any error.
    """
    defaults = {
        "src": "",
        "dst": "",
        "mirror": False,
        "protect": True,
        "exclude": DEFAULT_EXCLUDES,
    }
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        for key in defaults:
            if key in data:
                defaults[key] = data[key]
    except Exception:
        pass
    return defaults


def save_config(
    src: str,
    dst: str,
    mirror: bool,
    protect: bool,
    exclude: str,
) -> None:
    """Persist the current settings to disk."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(
                {
                    "src": src,
                    "dst": dst,
                    "mirror": mirror,
                    "protect": protect,
                    "exclude": exclude,
                },
                f,
                indent=2,
            )
    except Exception:
        pass

