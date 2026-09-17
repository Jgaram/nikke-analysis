"""Collect the two roster sources that a restricted network can always reach.

``gamefiles``  - LiviaMedeiros/nikke-forbidden-library, a CI-updated mirror of the
                 game's own localisation tables. Authoritative for unit ids and
                 for the EN/KO/JA spelling of every unit, including units that
                 only exist in the data files so far.

``nikkeutils`` - the ``@sancti0n/nikke-utils`` npm package, a community-maintained
                 table of burst / class / weapon / element / squad plus a
                 ``dateAdded`` field.

Neither is authoritative for *release* dates - see ``build/roster.py`` for how
the two are reconciled and where patch notes take over.
"""

from __future__ import annotations

import json
import logging
import shutil
import tarfile
from pathlib import Path

from ..util.http import Fetcher
from ..util.snapshot import SnapshotWriter
from .base import git_head_sha, shallow_sparse_clone, temp_checkout_dir

log = logging.getLogger(__name__)

GAMEFILES_REPO = "https://github.com/LiviaMedeiros/nikke-forbidden-library.git"
GAMEFILES_SUBDIR = "forbidden-library/roledata"
GAMEFILES_SOURCE = "roster_gamefiles"

NPM_REGISTRY = "https://registry.npmjs.org"
NPM_PACKAGE = "@sancti0n/nikke-utils"
NPM_SOURCE = "roster_nikkeutils"


def collect_gamefiles(*, repo_url: str = GAMEFILES_REPO, keep_checkout: bool = False) -> Path:
    """Snapshot every ``roledata/[NNN] Name.yaml`` file."""
    checkout = temp_checkout_dir("roledata")
    try:
        roledata = shallow_sparse_clone(repo_url, GAMEFILES_SUBDIR, checkout)
        head = git_head_sha(checkout)
        writer = SnapshotWriter(GAMEFILES_SOURCE)
        files = sorted(p for p in roledata.iterdir() if p.suffix in {".yaml", ".yml"})
        if not files:
            raise RuntimeError(f"no roledata files found under {roledata}")
        for path in files:
            payload = path.read_bytes()
            writer.write(
                f"roledata/{path.name}",
                payload,
                url=f"{repo_url}#{GAMEFILES_SUBDIR}/{path.name}",
                content_type="application/yaml",
            )
        writer.seal({"repo": repo_url, "commit": head, "subdir": GAMEFILES_SUBDIR})
        log.info("gamefiles snapshot: %s files -> %s", len(files), writer.dir)
        return writer.dir
    finally:
        if not keep_checkout:
            shutil.rmtree(checkout, ignore_errors=True)


def collect_nikkeutils(*, registry: str = NPM_REGISTRY, package: str = NPM_PACKAGE) -> Path:
    """Snapshot the published ``characters.js`` from the latest npm release."""
    fetcher = Fetcher(delay=0.2)
    meta_url = f"{registry}/{package}"
    meta = fetcher.get(meta_url).json()
    version = meta["dist-tags"]["latest"]
    tarball_url = meta["versions"][version]["dist"]["tarball"]

    tgz = fetcher.get(tarball_url).content
    work = temp_checkout_dir("npm")
    try:
        archive_path = work / "package.tgz"
        archive_path.write_bytes(tgz)
        with tarfile.open(archive_path) as tar:
            member = tar.getmember("package/src/data/characters.js")
            extracted = tar.extractfile(member)
            if extracted is None:
                raise RuntimeError("characters.js missing from npm tarball")
            characters_js = extracted.read()

        writer = SnapshotWriter(NPM_SOURCE)
        writer.write(
            "characters.js",
            characters_js,
            url=tarball_url,
            content_type="application/javascript",
            meta={"package": package, "version": version},
        )
        writer.write(
            "registry-metadata.json",
            json.dumps(
                {
                    "package": package,
                    "version": version,
                    "tarball": tarball_url,
                    "published_at": meta.get("time", {}).get(version),
                },
                indent=2,
            ).encode(),
            url=meta_url,
            content_type="application/json",
        )
        writer.seal({"package": package, "version": version})
        log.info("npm snapshot: %s@%s -> %s", package, version, writer.dir)
        return writer.dir
    finally:
        shutil.rmtree(work, ignore_errors=True)
