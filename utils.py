"""
utils.py — Small helpers used across the project.

Pure functions with no side-effects and no UI dependency.
"""

from __future__ import annotations

import fnmatch
import os


def human_size(n: float) -> str:
    """
    Convert a byte count to a human-readable string.

    Examples
    --------
    >>> human_size(0)
    '0 B'
    >>> human_size(1536)
    '1.5 KB'
    >>> human_size(1_073_741_824)
    '1.0 GB'
    """
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def parse_exclude_patterns(raw: str) -> list[str]:
    """
    Split a comma-separated string into a list of glob patterns.

    Leading / trailing whitespace around each pattern is stripped.
    Empty tokens are discarded.

    >>> parse_exclude_patterns(".DS_Store, __pycache__, *.log")
    ['.DS_Store', '__pycache__', '*.log']
    """
    return [p.strip() for p in raw.split(",") if p.strip()]


def is_excluded(name: str, patterns: list[str]) -> bool:
    """
    Return ``True`` if *name* matches any of the fnmatch *patterns*.

    >>> is_excluded("thumbs.db", ["*.db", "*.tmp"])
    True
    >>> is_excluded("readme.md", ["*.db", "*.tmp"])
    False
    """
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def validate_folder_pair(src: str, dst: str) -> str | None:
    """
    Validate that *src* and *dst* form a legal sync pair.

    Returns
    -------
    str or None
        An error message string if something is wrong, or ``None`` if valid.
    """
    if not src or not dst:
        return "Please select both folders."
    if not os.path.isdir(src):
        return "Source folder does not exist."
    if not os.path.isdir(dst):
        return "Destination folder not found.\n\nIs your external drive connected?"

    real_src = os.path.realpath(src)
    real_dst = os.path.realpath(dst)

    if real_src == real_dst:
        return "Source and destination are the same folder."
    if real_dst.startswith(real_src + os.sep) or real_src.startswith(real_dst + os.sep):
        return "One folder is inside the other.\nPlease choose separate folders."

    return None

