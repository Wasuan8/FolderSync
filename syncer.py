"""
syncer.py — Execute the copy / delete actions safely and in parallel.

Given a list of actions produced by the scanner, this module:
  1. Creates any needed directories.
  2. Copies new / updated files using a thread pool.
  3. Deletes files / dirs that mirror mode flagged.

Every copy goes through a temp file (*.syncpart) so an interrupted transfer
never leaves a corrupt file on the destination.
"""

from __future__ import annotations

import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from config import WORKERS
from scanner import Action


# ── Types ────────────────────────────────────────────────────────────────────

ProgressCallback = Callable[[float, str], None]
"""Called with (fraction_complete, status_message) after each file."""


# ── Single-file safe copy ────────────────────────────────────────────────────

def copy_file(src_root: str, dst_root: str, rel: str) -> None:
    """
    Copy *rel* from *src_root* to *dst_root* atomically.

    Strategy: write to a ``.syncpart`` temp file, then ``os.replace`` it to
    the final name.  If anything fails, the temp file is cleaned up.
    """
    s_path = os.path.join(src_root, rel)
    d_path = os.path.join(dst_root, rel)
    os.makedirs(os.path.dirname(d_path), exist_ok=True)

    tmp = d_path + ".syncpart"
    try:
        shutil.copy2(s_path, tmp)
        os.replace(tmp, d_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ── Bulk sync execution ─────────────────────────────────────────────────────

def run_sync(
    src: str,
    dst: str,
    actions: list[Action],
    cancel: threading.Event,
    on_progress: ProgressCallback | None = None,
) -> tuple[int, list[tuple[str, str]]]:
    """
    Execute *actions* produced by ``scanner.scan_folders``.

    Parameters
    ----------
    src, dst : str
        Absolute paths to source and destination roots.
    actions : list[Action]
        The plan to execute (``mkdir``, ``new``, ``update``, ``delete``, ``deldir``).
    cancel : threading.Event
        Set this to abort mid-sync.
    on_progress : callable, optional
        ``on_progress(fraction, message)`` is called after every copied file.

    Returns
    -------
    files_copied : int
        Number of files successfully copied.
    errors : list[(relpath, error_message)]
        Files that could not be copied / deleted.
    """
    total_bytes = max(1, sum(a[2] for a in actions if a[0] in ("new", "update")))
    total_files = sum(1 for a in actions if a[0] in ("new", "update"))
    state = {"bytes": 0, "files": 0}
    errors: list[tuple[str, str]] = []
    lock = threading.Lock()

    # ── 1. Create directories ────────────────────────────────────────────
    for kind, rel, _ in actions:
        if kind == "mkdir":
            try:
                os.makedirs(os.path.join(dst, rel), exist_ok=True)
            except Exception as exc:
                errors.append((rel, str(exc)))

    # ── 2. Copy files in parallel ────────────────────────────────────────
    def _do_copy(action: Action) -> None:
        if cancel.is_set():
            return
        _kind, rel, size = action
        try:
            copy_file(src, dst, rel)
        except Exception as exc:
            with lock:
                errors.append((rel, str(exc)))
        with lock:
            state["bytes"] += size
            state["files"] += 1
            if on_progress:
                pct = state["bytes"] / total_bytes
                msg = f"Copying {state['files']}/{total_files}: {rel}"
                on_progress(pct, msg)

    copies = [a for a in actions if a[0] in ("new", "update")]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(_do_copy, copies))

    # ── 3. Delete extras (mirror mode) ───────────────────────────────────
    if not cancel.is_set():
        for kind, rel, _ in actions:
            target = os.path.join(dst, rel)
            try:
                if kind == "delete" and os.path.exists(target):
                    os.remove(target)
                elif kind == "deldir" and os.path.isdir(target):
                    shutil.rmtree(target)
            except Exception as exc:
                errors.append((rel, str(exc)))

    return state["files"], errors

