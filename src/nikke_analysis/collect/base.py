"""Shared plumbing for collectors."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


class CollectorError(RuntimeError):
    pass


def shallow_sparse_clone(repo_url: str, subdir: str, dest: Path, *, ref: str = "HEAD") -> Path:
    """Fetch one directory of a public git repo without downloading its history.

    Used for the game-file mirrors on GitHub: they are the only source that
    carries the official EN/KO/JA spelling of every unit, but cloning them in
    full would pull hundreds of megabytes of unrelated text.

    Returns the path to ``subdir`` inside the checkout.
    """
    dest.mkdir(parents=True, exist_ok=True)
    cmd_base = ["git", "-c", "advice.detachedHead=false"]
    clone = cmd_base + [
        "clone",
        "--depth",
        "1",
        "--filter=blob:none",
        "--sparse",
        "--quiet",
    ]
    if ref != "HEAD":
        clone += ["--branch", ref]
    clone += [repo_url, str(dest)]

    result = subprocess.run(clone, capture_output=True, text=True)
    if result.returncode != 0:
        raise CollectorError(f"git clone failed for {repo_url}: {result.stderr.strip()}")

    result = subprocess.run(
        cmd_base + ["-C", str(dest), "sparse-checkout", "set", "--no-cone", subdir],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CollectorError(f"sparse-checkout failed for {subdir}: {result.stderr.strip()}")

    target = dest / subdir
    if not target.is_dir():
        raise CollectorError(f"{subdir} missing from {repo_url} checkout")
    return target


def git_head_sha(checkout: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def temp_checkout_dir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"nikke-{prefix}-"))
