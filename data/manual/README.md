# Hand-maintained data

This is the only directory a human is expected to edit. Everything else is
either fetched (`data/raw/`) or derived (`data/processed/`), and nothing here is
needed for the pipeline to run - these files exist for the rare case the
automated sources get something wrong.

Two rules keep it from turning into an unauditable pile:

1. **Every row carries a reason.** Without one there is no way to know, six
   months later, whether the row is still needed.
2. **A row is temporary by default.** When the automated sources start producing
   the right answer, delete the row rather than leaving two sources of truth.

## `release_overrides.csv`

Pins a unit's release date, beating the notice-derived date and everything
weaker. Use it when a unit's real release is known and the notices cannot give
it - today that is the three units of the 2022-12-08 update, whose notice is no
longer published anywhere (see docs/timeline.md, "알려진 공백").

```csv
unit_id,release_date,reason
203,2022-12-08,"Winter Shopper banner; 2022-12-08 update notice (no longer online)"
```

`unit_id` is the three-digit id from `data/processed/roster.csv` (`016`), and
`c016_00` or `16` are accepted too.

## `unit_aliases.csv`

Extra spellings for the name index, for a name the notices use that the game
files and their full-name descriptions do not cover. A name listed in
`data/processed/release_unresolved.csv` is the signal that one is needed.

```csv
unit_id,alias,reason
836,스즈하라 사쿠라,"how the 2025-02-20 notice names her"
```

(That particular alias is not needed: it is derived automatically from the unit
description in the game files.)

## `season_calendar.csv`

Superseded. The Solo Raid calendar is now rebuilt from the notices into
`data/processed/season_calendar.csv`, which the analysis stage reads first; this
file is only a fallback when no processed calendar exists.
