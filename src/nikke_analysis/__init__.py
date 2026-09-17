"""Deterministic NIKKE meta-analysis pipeline.

The package is deliberately split into four stages so that every number in a
report can be traced back to an immutable input:

    collect/  network -> data/raw/     (fetch only, never interprets)
    build/    raw     -> data/processed (pure parsing + joining)
    analyze/  processed -> metrics      (pure maths)
    viz/      metrics -> reports/       (rendering)

No stage calls a language model. Re-running `nikke build` on the same raw
snapshots must always produce byte-identical processed tables.
"""

__version__ = "0.1.0"
