"""Immutable raw-snapshot store.

Collectors never hand parsed objects to the rest of the pipeline. They write
exactly what came off the wire into ``data/raw/<source>/<run_id>/`` together
with a manifest describing where each byte came from. Everything downstream
reads from disk.

Why this indirection is worth it here:

* The upstream sites (enikk, the official patch-note pages) change their markup
  without notice. When a parser breaks we can fix it and re-run against the
  snapshots we already have, instead of losing a season of history.
* Solo Raid rankings are *ephemeral* - once a season rotates out, the old top-50
  is gone from the site. A snapshot taken during the season is the only copy
  that will ever exist.
* Parsers become pure functions of (bytes -> records), which makes them
  testable offline.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..paths import raw_dir

MANIFEST_NAME = "manifest.json"


def utc_now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@dataclass(frozen=True)
class SnapshotEntry:
    """One fetched resource inside a run."""

    filename: str
    url: str
    status: int
    content_type: str
    sha256: str
    bytes: int
    fetched_at: str
    meta: dict[str, Any] = field(default_factory=dict)


class SnapshotWriter:
    """Accumulates fetched payloads for one collector run, then seals them."""

    def __init__(self, source: str, run_id: str | None = None, root: Path | None = None):
        self.source = source
        base = (root if root is not None else raw_dir()) / source
        stem = run_id or utc_now_stamp()
        # Run ids are second-resolution timestamps. Two runs in the same second
        # must not share a directory: the second would write into the first, and
        # an empty second run discarding its directory would delete the first.
        candidate, suffix = base / stem, 1
        while candidate.exists():
            suffix += 1
            candidate = base / f"{stem}-{suffix:03d}"
        self.run_id = candidate.name
        self.dir = candidate
        self.dir.mkdir(parents=True)
        self._entries: list[SnapshotEntry] = []

    def write(
        self,
        filename: str,
        payload: bytes,
        *,
        url: str,
        status: int = 200,
        content_type: str = "",
        meta: dict[str, Any] | None = None,
    ) -> SnapshotEntry:
        target = self.dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        entry = SnapshotEntry(
            filename=filename,
            url=url,
            status=status,
            content_type=content_type,
            sha256=hashlib.sha256(payload).hexdigest(),
            bytes=len(payload),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            meta=meta or {},
        )
        self._entries.append(entry)
        return entry

    def seal(self, extra: dict[str, Any] | None = None) -> Path:
        manifest = {
            "source": self.source,
            "run_id": self.run_id,
            "sealed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "entry_count": len(self._entries),
            "entries": [asdict(e) for e in self._entries],
        }
        if extra:
            manifest["extra"] = extra
        path = self.dir / MANIFEST_NAME
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def discard(self) -> None:
        """Drop a run that turned out to have nothing new.

        Incremental collectors call this so an idle week does not leave an empty
        run directory behind for every source.
        """
        shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self) -> "SnapshotWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.seal()


@dataclass(frozen=True)
class SnapshotRun:
    source: str
    run_id: str
    dir: Path
    manifest: dict[str, Any]

    @property
    def entries(self) -> list[dict[str, Any]]:
        return self.manifest.get("entries", [])

    def read(self, filename: str) -> bytes:
        return (self.dir / filename).read_bytes()

    def read_text(self, filename: str, encoding: str = "utf-8") -> str:
        return self.read(filename).decode(encoding)

    def read_json(self, filename: str) -> Any:
        return json.loads(self.read_text(filename))

    def iter_files(self, suffix: str | None = None) -> Iterator[tuple[str, bytes]]:
        for entry in self.entries:
            name = entry["filename"]
            if suffix is None or name.endswith(suffix):
                yield name, self.read(name)


def list_runs(source: str, root: Path | None = None) -> list[SnapshotRun]:
    """All sealed runs for a source, oldest first."""
    base = (root if root is not None else raw_dir()) / source
    if not base.is_dir():
        return []
    runs: list[SnapshotRun] = []
    for child in sorted(base.iterdir()):
        manifest_path = child / MANIFEST_NAME
        if not manifest_path.is_file():
            continue  # an interrupted run; skip rather than half-parse it
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        runs.append(SnapshotRun(source, child.name, child, manifest))
    return runs


def latest_run(source: str, root: Path | None = None) -> SnapshotRun | None:
    runs = list_runs(source, root=root)
    return runs[-1] if runs else None
