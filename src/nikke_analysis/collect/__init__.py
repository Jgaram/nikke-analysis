"""Network-facing collectors.

A collector's only job is to put bytes on disk under ``data/raw/<source>/``.
It must not parse, normalise, or filter - that happens in ``build/`` against the
snapshot, so a parser bug never costs us the data.

The one exception is ``blablalink``: icons are looked up, not parsed, so they
go straight to ``data/assets/icons/`` with one file per unit.
"""
