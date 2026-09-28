"""Deterministic NIKKE meta-analysis pipeline.

The package is deliberately split into stages so that every number in a
report can be traced back to an immutable input:

    collect/      network   -> data/raw/         (fetch only, never interprets)
    build/        raw       -> data/processed/   (pure parsing + joining)
    analyze/      processed -> metrics_*.csv     (pure maths: usage, lift, tiers)
    timeline.py   processed -> what was live at a moment    (nikke asof)
    tierlist.py   metrics   -> tiers at a moment            (nikke tier)
    raidstats.py  metrics   -> one season's usage by deck   (nikke raid)
    viz/          metrics   -> reports/*.png     (rendering)

No stage calls a language model. Re-running `nikke build` on the same raw
snapshots must always produce byte-identical processed tables.
"""

__version__ = "0.1.0"
