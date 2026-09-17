"""Pure transforms: snapshots on disk -> tidy tables in data/processed.

Nothing in here touches the network. Every function takes bytes or paths and
returns records, so the whole stage is reproducible and unit-testable.
"""
