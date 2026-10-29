"""
scanner.py — Compare two folder trees and decide WHAT needs to change.

This module is read-only: it never copies, deletes, or modifies any file.
It returns a list of planned *actions* that the syncer can execute later.
"""

from __future__ import annotations

import os
import threading

from config import MTIME_TOLERANCE
from utils import is_excluded


# ── Action types ─────────────────────────────────────────────────────────────
#   ("new",    relpath, size)   — file exists in source but not destination
#   ("update", relpath, size)   — file changed (size or mtime differs)
#   ("delete", relpath, size)   — file in destination not in source (mirror)
#   ("deldir", relpath, 0)      — directory in destination not in source
#   ("mkdir",  relpath, 0)      — directory exists in source but not destination

Action = tuple[str, str, int]


def scan_folders(
    src: str,
    dst: str,
    patterns: list[str],
    mirror: bool,
    protect_newer: bool,
    cancel: threading.Event,
) -> tuple[list[Action], int]:
    """
    Walk *src* and *dst* and produce a list of sync actions.

    Parameters
    ----------
    src : str
        Absolute path to the source (authoritative) folder.
    dst : str
        Absolute path to the destination folder.
    patterns : list[str]
        Glob patterns for files / dirs to ignore.
    mirror : bool
        If ``True``, also plan deletions for items in *dst* not in *src*.
    protect_newer : bool
        If ``True``, skip overwriting files on *dst* that are newer than *src*.
    cancel : threading.Event
        Set this event to abort the scan early.

    Returns
    -------
    actions : list[Action]
        Each action is ``(kind, relpath, size_in_bytes)``.
    skipped : int
        Number of files skipped because the destination copy was newer.
    """
    actions: list[Action] = []
    skipped = 0
    src_files: set[str] = set()
    src_dirs: set[str] = set()

    # ── Walk source tree ─────────────────────────────────────────────────
    for root, dirs, files in os.walk(src):
        if cancel.is_set():
            return actions, skipped

        dirs[:] = [d for d in dirs if not is_excluded(d, patterns)]
        rel_root = os.path.relpath(root, src)
        rel_root = "" if rel_root == "." else rel_root

        if rel_root:
            src_dirs.add(rel_root)
            if not os.path.isdir(os.path.join(dst, rel_root)):
                actions.append(("mkdir", rel_root, 0))

        for fname in files:
            if is_excluded(fname, patterns):
                continue

            rel = os.path.join(rel_root, fname)
            src_files.add(rel)

            s_path = os.path.join(src, rel)
            d_path = os.path.join(dst, rel)

            try:
                s_stat = os.stat(s_path)
            except OSError:
                continue

            if not os.path.exists(d_path):
                actions.append(("new", rel, s_stat.st_size))
                continue

            try:
                d_stat = os.stat(d_path)
            except OSError:
                actions.append(("update", rel, s_stat.st_size))
                continue

            changed = (
                s_stat.st_size != d_stat.st_size
                or abs(s_stat.st_mtime - d_stat.st_mtime) > MTIME_TOLERANCE
            )
            if changed:
                if protect_newer and d_stat.st_mtime > s_stat.st_mtime + MTIME_TOLERANCE:
                    skipped += 1
                else:
                    actions.append(("update", rel, s_stat.st_size))

    # ── Walk destination for mirror-mode deletions ───────────────────────
    if mirror and os.path.isdir(dst):
        for root, dirs, files in os.walk(dst):
            if cancel.is_set():
                return actions, skipped

            rel_root = os.path.relpath(root, dst)
            rel_root = "" if rel_root == "." else rel_root
            keep: list[str] = []

            for d in dirs:
                if is_excluded(d, patterns):
                    continue
                rel = os.path.join(rel_root, d)
                if rel in src_dirs:
                    keep.append(d)
                else:
                    actions.append(("deldir", rel, 0))
            dirs[:] = keep

            for fname in files:
                if is_excluded(fname, patterns):
                    continue
                rel = os.path.join(rel_root, fname)
                if rel not in src_files:
                    try:
                        size = os.path.getsize(os.path.join(dst, rel))
                    except OSError:
                        size = 0
                    actions.append(("delete", rel, size))

    return actions, skipped

