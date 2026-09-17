"""Network-facing collectors.

A collector's only job is to put bytes on disk under ``data/raw/<source>/``.
It must not parse, normalise, or filter - that happens in ``build/`` against the
snapshot, so a parser bug never costs us the data.
"""
