# Hand-maintained data

This is the only directory a human is expected to edit. Everything else is
either fetched (`data/raw/`) or derived (`data/processed/`).

Two rules keep it from turning into an unauditable pile:

1. **Every override carries a reason.** Without one there is no way to know,
   six months later, whether the row is still needed.
2. **An override is temporary by default.** When the patch-note collector starts
   producing the right date for a unit, delete its row rather than leaving two
   sources of truth in play.

## `release_overrides.csv`

Pins a unit's release date, beating both the patch-note date and the data-file
date. Use it when a unit's real release is known and the automated sources
disagree.

```csv
unit_id,release_date,reason
016,2023-11-16,"Red Hood banner; confirmed against the 2023-11-16 update notice"
```

`unit_id` is the three-digit id from `data/processed/roster.csv` (`016`), and
`c016_00` or `16` are accepted too.

## `season_calendar.csv`

Maps each Solo Raid season to the dates it ran. Optional but worth filling in:
without it the pipeline can only *infer* which units existed in a season from
who was picked, which under-counts the roster and slightly inflates every pick
rate. It is also what makes `metrics_patch_impact.csv` possible - attributing a
meta shift to the patches inside a window needs to know where the window is.

```csv
season,start_date,end_date
40,2026-08-27,2026-09-03
41,2026-09-24,2026-10-01
```
