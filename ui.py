"""
ui.py — The application window.

Builds the GUI, reacts to user clicks, and delegates all real work
to the scanner and syncer modules.  Contains zero sync logic of its own.
"""

from __future__ import annotations

import os
import platform
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from config import (
    APP_NAME,
    APP_VERSION,
    C_ACCENT,
    C_ACCENT_HOVER,
    C_AMBER,
    C_BG,
    C_BG_CARD,
    C_BG_ENTRY,
    C_BG_HOVER,
    C_BORDER,
    C_FG,
    C_FG_DIM,
    C_GREEN,
    C_RED,
    C_TOAST_BG,
    DEFAULT_EXCLUDES,
    ICO_CANCEL,
    ICO_CHECK,
    ICO_DELETE,
    ICO_DST,
    ICO_EJECT,
    ICO_FOLDER,
    ICO_NEW,
    ICO_SCAN,
    ICO_SRC,
    ICO_SWAP,
    ICO_SYNC,
    ICO_UPDATE,
    ICO_USB,
    ICO_WARN,
    MAX_ROWS,
    VOLUME_POLL_SEC,
    load_config,
    save_config,
)
from scanner import scan_folders
from syncer import run_sync
from utils import human_size, parse_exclude_patterns, validate_folder_pair


# ══════════════════════════════════════════════════════════════════════════════
# VOLUME WATCHER — detects external drive attach / detach
# ══════════════════════════════════════════════════════════════════════════════

class VolumeWatcher:
    """
    Polls ``/Volumes`` (macOS) for newly attached or detached drives and
    delivers events through a callback.

    On non-macOS platforms the watcher is a silent no-op.
    """

    def __init__(self, on_change: Callable[[str, str], None]) -> None:
        self._on_change = on_change
        self._stop = threading.Event()
        self._volumes: set[str] = set()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if platform.system() != "Darwin":
            return
        self._volumes = self._current_volumes()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def _current_volumes() -> set[str]:
        try:
            return set(os.listdir("/Volumes"))
        except OSError:
            return set()

    def _run(self) -> None:
        while not self._stop.is_set():
            time.sleep(VOLUME_POLL_SEC)
            current = self._current_volumes()
            for v in current - self._volumes:
                self._on_change("attached", v)
            for v in self._volumes - current:
                self._on_change("detached", v)
            self._volumes = current


# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

class ToastNotification(tk.Toplevel):
    """
    Transient slide-in notification anchored to the bottom-right of *parent*.
    Auto-dismisses after *duration_ms* milliseconds.
    """

    def __init__(
        self,
        parent: tk.Tk,
        message: str,
        *,
        icon: str = "",
        duration_ms: int = 5000,
        bg: str = C_TOAST_BG,
        fg: str = C_FG,
        accent: str = C_ACCENT,
    ) -> None:
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=bg)
        self._parent = parent
        self._duration = duration_ms

        frame = tk.Frame(self, bg=bg, padx=16, pady=12)
        frame.pack(fill="both", expand=True)

        # Accent bar
        tk.Frame(frame, bg=accent, width=4).pack(side="left", fill="y", padx=(0, 12))

        text_frame = tk.Frame(frame, bg=bg)
        text_frame.pack(side="left", fill="both", expand=True)

        if icon:
            tk.Label(
                text_frame, text=icon, font=("Helvetica", 18), bg=bg, fg=fg,
            ).pack(side="left", padx=(0, 8))

        tk.Label(
            text_frame, text=message, font=("Helvetica", 13),
            bg=bg, fg=fg, wraplength=320, justify="left",
        ).pack(side="left", fill="x", expand=True)

        close_btn = tk.Label(
            frame, text="✕", font=("Helvetica", 12),
            bg=bg, fg=C_FG_DIM, cursor="hand2",
        )
        close_btn.pack(side="right", padx=(8, 0))
        close_btn.bind("<Button-1>", lambda _: self.destroy())

        self._position()
        self.after(self._duration, self._dismiss)

    def _position(self) -> None:
        self.update_idletasks()
        pw, ph = self._parent.winfo_width(), self._parent.winfo_height()
        px, py = self._parent.winfo_rootx(), self._parent.winfo_rooty()
        tw = max(self.winfo_reqwidth(), 360)
        th = self.winfo_reqheight()
        self.geometry(f"{tw}x{th}+{px + pw - tw - 20}+{py + ph - th - 20}")

    def _dismiss(self) -> None:
        try:
            self.destroy()
        except tk.TclError:
            pass


class RoundedCard(tk.Frame):
    """Dark-themed card container with a subtle border."""

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        bg = kwargs.pop("bg", C_BG_CARD)
        super().__init__(
            parent, bg=bg,
            highlightthickness=1, highlightbackground=C_BORDER,
            **kwargs,
        )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    """FolderSync main window — all UI, no sync logic."""

    # ── Initialisation ───────────────────────────────────────────────────

    def __init__(self) -> None:
        super().__init__()

        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1000x740")
        self.minsize(820, 600)
        self.configure(bg=C_BG)

        # State
        self.src_var = tk.StringVar()
        self.dst_var = tk.StringVar()
        self.mirror_var = tk.BooleanVar(value=False)
        self.protect_var = tk.BooleanVar(value=True)
        self.excl_var = tk.StringVar(value=DEFAULT_EXCLUDES)
        self.status_var = tk.StringVar(value="Select your folders to begin.")
        self.summary_var = tk.StringVar(value="")

        self.msg_queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.actions: list[tuple[str, str, int]] = []
        self.busy = False

        # Build
        self._apply_styles()
        self._build_header()
        self._build_folder_card()
        self._build_options_card()
        self._build_action_bar()
        self._build_preview_table()
        self._build_footer()

        # Config
        self._load_saved_config()

        # Volume watcher
        self.volume_watcher = VolumeWatcher(on_change=self._on_volume_change)
        self.volume_watcher.start()

        # Lifecycle
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_queue)

    # ── Styling ──────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            ".", background=C_BG, foreground=C_FG,
            fieldbackground=C_BG_ENTRY, borderwidth=0, focuscolor=C_ACCENT,
        )

        # Labels
        style.configure("Title.TLabel", font=("Helvetica", 22, "bold"),
                         foreground=C_FG, background=C_BG)
        style.configure("Subtitle.TLabel", font=("Helvetica", 12),
                         foreground=C_FG_DIM, background=C_BG)
        style.configure("CardTitle.TLabel", font=("Helvetica", 13, "bold"),
                         foreground=C_FG, background=C_BG_CARD)
        style.configure("Card.TLabel", foreground=C_FG, background=C_BG_CARD)
        style.configure("CardDim.TLabel", foreground=C_FG_DIM, background=C_BG_CARD)
        style.configure("Summary.TLabel", font=("Helvetica", 12, "bold"),
                         foreground=C_GREEN, background=C_BG)
        style.configure("Status.TLabel", foreground=C_FG_DIM, background=C_BG)

        # Entries
        style.configure("Dark.TEntry", fieldbackground=C_BG_ENTRY,
                         foreground=C_FG, insertcolor=C_FG)
        style.map("Dark.TEntry",
                  fieldbackground=[("focus", C_BG_ENTRY), ("!focus", C_BG_ENTRY)])

        # Buttons
        style.configure("Accent.TButton", font=("Helvetica", 12, "bold"),
                         background=C_ACCENT, foreground="#ffffff", padding=(16, 8))
        style.map("Accent.TButton",
                  background=[("active", C_ACCENT_HOVER), ("disabled", C_BG_ENTRY)])

        style.configure("Secondary.TButton", font=("Helvetica", 11),
                         background=C_BG_CARD, foreground=C_FG, padding=(12, 6))
        style.map("Secondary.TButton",
                  background=[("active", C_BG_HOVER), ("disabled", C_BG_ENTRY)])

        # Checkbuttons
        style.configure("Dark.TCheckbutton", background=C_BG_CARD,
                         foreground=C_FG, font=("Helvetica", 11))
        style.map("Dark.TCheckbutton", background=[("active", C_BG_CARD)])

        # Progressbar
        style.configure("Accent.Horizontal.TProgressbar",
                         troughcolor=C_BG_ENTRY, background=C_ACCENT,
                         lightcolor=C_ACCENT, darkcolor=C_ACCENT,
                         bordercolor=C_BG_ENTRY)

        # Treeview
        style.configure("Dark.Treeview",
                         background=C_BG_CARD, foreground=C_FG,
                         fieldbackground=C_BG_CARD, rowheight=28,
                         font=("Helvetica", 11))
        style.configure("Dark.Treeview.Heading",
                         background=C_BG_ENTRY, foreground=C_FG_DIM,
                         font=("Helvetica", 11, "bold"))
        style.map("Dark.Treeview",
                  background=[("selected", C_ACCENT)],
                  foreground=[("selected", "#ffffff")])

        # Scrollbar
        style.configure("Dark.Vertical.TScrollbar",
                         background=C_BG_CARD, troughcolor=C_BG_CARD,
                         arrowcolor=C_FG_DIM)

    # ── Layout builders ──────────────────────────────────────────────────

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=C_BG)
        header.pack(fill="x", padx=24, pady=(20, 4))
        tk.Label(header, text=f"{ICO_FOLDER} {APP_NAME}",
                 font=("Helvetica", 22, "bold"), bg=C_BG, fg=C_FG).pack(side="left")
        tk.Label(header, text=f"v{APP_VERSION}",
                 font=("Helvetica", 11), bg=C_BG, fg=C_FG_DIM).pack(
                     side="left", padx=(8, 0), pady=(6, 0))

        sub = tk.Frame(self, bg=C_BG)
        sub.pack(fill="x", padx=24, pady=(0, 12))
        tk.Label(sub,
                 text="Sync your project folders with external drives — fast, safe, parallel.",
                 font=("Helvetica", 12), bg=C_BG, fg=C_FG_DIM).pack(anchor="w")

    def _build_folder_card(self) -> None:
        card = RoundedCard(self, padx=16, pady=14)
        card.pack(fill="x", padx=24, pady=(0, 10))

        title_row = tk.Frame(card, bg=C_BG_CARD)
        title_row.pack(fill="x", pady=(0, 10))
        tk.Label(title_row, text=f"{ICO_FOLDER}  Folders",
                 font=("Helvetica", 13, "bold"), bg=C_BG_CARD, fg=C_FG).pack(side="left")

        swap_btn = tk.Label(title_row, text=f"{ICO_SWAP} Swap",
                            font=("Helvetica", 11), bg=C_BG_CARD, fg=C_ACCENT,
                            cursor="hand2")
        swap_btn.pack(side="right")
        swap_btn.bind("<Button-1>", lambda _: self._swap_folders())

        self._build_folder_row(card, f"{ICO_SRC}  Source (local project)",
                               self.src_var, self._pick_source)
        self._build_folder_row(card, f"{ICO_DST}  Destination (external drive)",
                               self.dst_var, self._pick_destination)

    def _build_folder_row(
        self, parent: tk.Widget, label: str,
        var: tk.StringVar, browse_cmd: Callable,
    ) -> None:
        row = tk.Frame(parent, bg=C_BG_CARD)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, font=("Helvetica", 11),
                 bg=C_BG_CARD, fg=C_FG_DIM, anchor="w").pack(fill="x")

        entry_row = tk.Frame(row, bg=C_BG_CARD)
        entry_row.pack(fill="x", pady=(2, 0))
        tk.Entry(
            entry_row, textvariable=var, font=("Helvetica", 12),
            bg=C_BG_ENTRY, fg=C_FG, insertbackground=C_FG,
            relief="flat", highlightthickness=1,
            highlightbackground=C_BORDER, highlightcolor=C_ACCENT,
        ).pack(side="left", fill="x", expand=True, ipady=6)

        browse = tk.Label(entry_row, text="  Browse…  ",
                          font=("Helvetica", 11), bg=C_BG_ENTRY, fg=C_ACCENT,
                          cursor="hand2")
        browse.pack(side="right", ipady=6)
        browse.bind("<Button-1>", lambda _: browse_cmd())

    def _build_options_card(self) -> None:
        card = RoundedCard(self, padx=16, pady=14)
        card.pack(fill="x", padx=24, pady=(0, 10))

        tk.Label(card, text="⚙  Options", font=("Helvetica", 13, "bold"),
                 bg=C_BG_CARD, fg=C_FG).pack(anchor="w", pady=(0, 8))

        chk = tk.Frame(card, bg=C_BG_CARD)
        chk.pack(fill="x")
        ttk.Checkbutton(chk, text="  Protect newer files on destination (safer)",
                        variable=self.protect_var,
                        style="Dark.TCheckbutton").pack(anchor="w", pady=2)
        ttk.Checkbutton(chk, text="  Mirror mode — delete destination files not in source",
                        variable=self.mirror_var,
                        style="Dark.TCheckbutton").pack(anchor="w", pady=2)

        excl = tk.Frame(card, bg=C_BG_CARD)
        excl.pack(fill="x", pady=(8, 0))
        tk.Label(excl, text="Ignore patterns:", font=("Helvetica", 11),
                 bg=C_BG_CARD, fg=C_FG_DIM).pack(side="left", padx=(0, 8))
        tk.Entry(
            excl, textvariable=self.excl_var, font=("Helvetica", 11),
            bg=C_BG_ENTRY, fg=C_FG, insertbackground=C_FG,
            relief="flat", highlightthickness=1,
            highlightbackground=C_BORDER, highlightcolor=C_ACCENT,
        ).pack(side="left", fill="x", expand=True, ipady=4)

    def _build_action_bar(self) -> None:
        bar = tk.Frame(self, bg=C_BG)
        bar.pack(fill="x", padx=24, pady=(4, 8))

        self.scan_btn = ttk.Button(bar, text=f" {ICO_SCAN}  Scan Changes ",
                                   style="Accent.TButton", command=self.start_scan)
        self.scan_btn.pack(side="left")

        self.sync_btn = ttk.Button(bar, text=f" {ICO_SYNC}  Sync Now ",
                                   style="Accent.TButton", command=self.start_sync,
                                   state="disabled")
        self.sync_btn.pack(side="left", padx=(10, 0))

        self.cancel_btn = ttk.Button(bar, text=f" {ICO_CANCEL}  Cancel ",
                                     style="Secondary.TButton",
                                     command=self.cancel_event.set, state="disabled")
        self.cancel_btn.pack(side="left", padx=(10, 0))

        self.summary_label = tk.Label(bar, textvariable=self.summary_var,
                                      font=("Helvetica", 12, "bold"),
                                      bg=C_BG, fg=C_GREEN)
        self.summary_label.pack(side="right")

    def _build_preview_table(self) -> None:
        frame = tk.Frame(self, bg=C_BG)
        frame.pack(fill="both", expand=True, padx=24)

        cols = ("status", "file", "size")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                 selectmode="browse", style="Dark.Treeview")
        self.tree.heading("status", text="Action")
        self.tree.heading("file", text="File")
        self.tree.heading("size", text="Size")
        self.tree.column("status", width=120, stretch=False)
        self.tree.column("file", width=600)
        self.tree.column("size", width=100, anchor="e", stretch=False)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview,
                           style="Dark.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.tree.tag_configure("new", foreground=C_GREEN)
        self.tree.tag_configure("update", foreground=C_AMBER)
        self.tree.tag_configure("delete", foreground=C_RED)
        self.tree.tag_configure("error", foreground=C_RED)

    def _build_footer(self) -> None:
        footer = tk.Frame(self, bg=C_BG)
        footer.pack(fill="x", padx=24, pady=(8, 16))
        self.progress = ttk.Progressbar(footer, mode="determinate",
                                        style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill="x")
        tk.Label(footer, textvariable=self.status_var, font=("Helvetica", 11),
                 bg=C_BG, fg=C_FG_DIM, anchor="w").pack(fill="x", pady=(6, 0))

    # ── Folder helpers ───────────────────────────────────────────────────

    def _pick_source(self) -> None:
        p = filedialog.askdirectory(title="Select SOURCE folder (local project)",
                                    initialdir=os.path.expanduser("~"))
        if p:
            self.src_var.set(p)
            self._reset_preview()

    def _pick_destination(self) -> None:
        start = "/Volumes" if os.path.isdir("/Volumes") else os.path.expanduser("~")
        p = filedialog.askdirectory(title="Select DESTINATION folder (external drive)",
                                    initialdir=start)
        if p:
            self.dst_var.set(p)
            self._reset_preview()

    def _swap_folders(self) -> None:
        s, d = self.src_var.get(), self.dst_var.get()
        self.src_var.set(d)
        self.dst_var.set(s)
        self._reset_preview()

    # ── Validation ───────────────────────────────────────────────────────

    def _validate(self) -> tuple[str, str] | None:
        src = self.src_var.get().strip()
        dst = self.dst_var.get().strip()
        err = validate_folder_pair(src, dst)
        if err:
            messagebox.showerror(APP_NAME, err)
            return None
        return os.path.realpath(src), os.path.realpath(dst)

    # ── Preview state ────────────────────────────────────────────────────

    def _reset_preview(self) -> None:
        self.actions = []
        self.tree.delete(*self.tree.get_children())
        self.sync_btn.config(state="disabled")
        self.summary_var.set("")
        self.progress["value"] = 0

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.scan_btn.config(state="disabled" if busy else "normal")
        self.cancel_btn.config(state="normal" if busy else "disabled")
        if busy:
            self.sync_btn.config(state="disabled")

    # ── Scan workflow ────────────────────────────────────────────────────

    def start_scan(self) -> None:
        paths = self._validate()
        if not paths:
            return
        self._persist_config()
        self._reset_preview()
        self._set_busy(True)
        self.cancel_event.clear()
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        self.status_var.set("Scanning folders…")

        src, dst = paths
        patterns = parse_exclude_patterns(self.excl_var.get())
        mirror = self.mirror_var.get()
        protect = self.protect_var.get()

        def _worker() -> None:
            try:
                acts, skipped = scan_folders(src, dst, patterns, mirror,
                                             protect, self.cancel_event)
                self.msg_queue.put(("scan_done", acts, skipped))
            except Exception as exc:
                self.msg_queue.put(("error", f"Scan failed: {exc}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_scan_done(self, acts: list, skipped: int) -> None:
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)
        self._set_busy(False)

        if self.cancel_event.is_set():
            self.status_var.set("Scan cancelled.")
            return

        self.actions = acts
        labels = {
            "new": f"{ICO_NEW}  New", "update": f"{ICO_UPDATE}  Update",
            "delete": f"{ICO_DELETE}  Delete", "deldir": f"{ICO_DELETE}  Delete folder",
            "mkdir": f"{ICO_FOLDER}  New folder",
        }
        visible = [a for a in acts if a[0] != "mkdir"]
        for kind, rel, size in visible[:MAX_ROWS]:
            tag = "delete" if kind in ("delete", "deldir") else kind
            self.tree.insert("", "end",
                             values=(labels[kind], rel, human_size(size) if size else ""),
                             tags=(tag,))
        if len(visible) > MAX_ROWS:
            self.tree.insert("", "end",
                             values=("…", f"and {len(visible) - MAX_ROWS} more", ""))

        n_new = sum(1 for a in acts if a[0] == "new")
        n_upd = sum(1 for a in acts if a[0] == "update")
        n_del = sum(1 for a in acts if a[0] in ("delete", "deldir"))
        total = sum(a[2] for a in acts if a[0] in ("new", "update"))

        if not acts:
            self.summary_var.set(f"{ICO_CHECK}  Everything is up to date")
            self.summary_label.config(fg=C_GREEN)
            skip = f"  ({skipped} newer file(s) skipped)" if skipped else ""
            self.status_var.set(f"Nothing to copy.{skip}")
            return

        self.summary_var.set(
            f"{n_new} new  ·  {n_upd} updated  ·  {n_del} to delete  ·  {human_size(total)}")
        self.summary_label.config(fg=C_AMBER if n_del else C_FG)
        skip = f"  ({skipped} newer file(s) skipped)" if skipped else ""
        self.status_var.set(f"Review the list, then click Sync Now.{skip}")
        self.sync_btn.config(state="normal")

    # ── Sync workflow ────────────────────────────────────────────────────

    def start_sync(self) -> None:
        paths = self._validate()
        if not paths or not self.actions:
            return

        n_del = sum(1 for a in self.actions if a[0] in ("delete", "deldir"))
        if n_del and not messagebox.askyesno(
            APP_NAME,
            f"{n_del} item(s) will be PERMANENTLY deleted "
            f"from the destination.\n\nContinue?",
        ):
            return

        self._set_busy(True)
        self.cancel_event.clear()
        src, dst = paths
        acts = list(self.actions)
        self.progress.config(mode="determinate", value=0)

        def _on_progress(pct: float, msg: str) -> None:
            self.msg_queue.put(("progress", pct, msg))

        def _worker() -> None:
            try:
                files, errors = run_sync(src, dst, acts, self.cancel_event,
                                         on_progress=_on_progress)
                self.msg_queue.put(("sync_done", files, errors,
                                    self.cancel_event.is_set()))
            except Exception as exc:
                self.msg_queue.put(("error", f"Sync failed: {exc}"))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Queue polling ────────────────────────────────────────────────────

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]

                if kind == "scan_done":
                    self._handle_scan_done(msg[1], msg[2])

                elif kind == "progress":
                    self.progress["value"] = msg[1] * 100
                    self.status_var.set(msg[2])

                elif kind == "sync_done":
                    _, files, errors, cancelled = msg
                    self._set_busy(False)
                    self.actions = []
                    self.sync_btn.config(state="disabled")
                    self.progress["value"] = 0 if cancelled else 100

                    if cancelled:
                        self.status_var.set(
                            f"Cancelled after {files} file(s). Scan again to continue.")
                    elif errors:
                        self.status_var.set(f"Finished with {len(errors)} error(s).")
                        self.summary_var.set(f"{ICO_WARN}  Completed with errors")
                        self.summary_label.config(fg=C_RED)
                        detail = "\n".join(f"• {r}: {e}" for r, e in errors[:15])
                        messagebox.showwarning(
                            APP_NAME,
                            f"Some files could not be copied:\n\n{detail}")
                    else:
                        self.status_var.set(
                            f"{ICO_CHECK}  Done — {files} file(s) synced. "
                            f"Destination is up to date.")
                        self.summary_var.set(f"{ICO_CHECK}  Sync complete")
                        self.summary_label.config(fg=C_GREEN)
                        self.tree.delete(*self.tree.get_children())

                elif kind == "error":
                    self.progress.stop()
                    self._set_busy(False)
                    self.status_var.set(msg[1])
                    messagebox.showerror(APP_NAME, msg[1])

                elif kind == "volume_change":
                    self._handle_volume_toast(msg[1], msg[2])

        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # ── Volume events ────────────────────────────────────────────────────

    def _on_volume_change(self, event: str, volume_name: str) -> None:
        self.msg_queue.put(("volume_change", event, volume_name))

    def _handle_volume_toast(self, event: str, volume_name: str) -> None:
        if event == "attached":
            msg = f"Drive connected: {volume_name}\nYou can select it as your destination."
            try:
                subprocess.Popen(["afplay", "/System/Library/Sounds/Blow.aiff"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
            dst = self.dst_var.get()
            if dst and volume_name in dst and os.path.isdir(dst):
                msg = (f"Drive reconnected: {volume_name}\n"
                       f"Your destination folder is available again.")
            ToastNotification(self, msg, icon=ICO_USB, accent=C_GREEN, duration_ms=6000)

        elif event == "detached":
            msg = f"Drive disconnected: {volume_name}"
            try:
                subprocess.Popen(["afplay", "/System/Library/Sounds/Sosumi.aiff"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
            dst = self.dst_var.get()
            if dst and volume_name in dst:
                msg = (f"Drive disconnected: {volume_name}\n"
                       f"{ICO_WARN} Your destination folder is no longer available!")
                ToastNotification(self, msg, icon=ICO_EJECT, accent=C_RED, duration_ms=8000)
                if self.busy:
                    self.cancel_event.set()
                    self.status_var.set(
                        f"Cancelled — drive '{volume_name}' was disconnected.")
            else:
                ToastNotification(self, msg, icon=ICO_EJECT, accent=C_AMBER, duration_ms=5000)

    # ── Config ───────────────────────────────────────────────────────────

    def _load_saved_config(self) -> None:
        cfg = load_config()
        self.src_var.set(cfg["src"])
        self.dst_var.set(cfg["dst"])
        self.mirror_var.set(cfg["mirror"])
        self.protect_var.set(cfg["protect"])
        self.excl_var.set(cfg["exclude"])

    def _persist_config(self) -> None:
        save_config(
            src=self.src_var.get(), dst=self.dst_var.get(),
            mirror=self.mirror_var.get(), protect=self.protect_var.get(),
            exclude=self.excl_var.get(),
        )

    # ── Close ────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self.busy and not messagebox.askyesno(APP_NAME, "A task is running. Quit anyway?"):
            return
        self.cancel_event.set()
        self.volume_watcher.stop()
        self._persist_config()
        self.destroy()

