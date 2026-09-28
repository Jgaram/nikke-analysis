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

## `extra_elements.csv`

The element(s) whose weakness advantage (우월 코드) a unit's skill gives it on
top of its own. No source carries this - the game files and nikke-utils list one
element per unit - so it lives here, and the roster build writes it to the
`extra_elements` column of `roster.csv`. Such a unit counts as each of its
elements: it gets an element tier in each and is listed in each element's tier
table (`nikke tier --element`).

```csv
unit_id,element,since,reason
016,Iron,,"라피 : 레드 후드 (작열): 스킬로 철갑 우월 코드도 가진다"
140,Water,treasure,"슈가 (철갑): 애장품(2026-07-23)으로 스킬이 바뀌어 수냉 우월 코드도 가진다"
```

One row per unit and added element; the element in English (`Iron`) or Korean
(`철갑`). `since` says from when the row holds: empty for as long as the unit
exists, `treasure` (or `애장품`) from the unit's treasure on - for a skill the
treasure changed. Those go to the roster's `treasure_elements` column instead,
and the unit counts as that element only in the seasons played with its
treasure (the treasure date itself comes from the update notices, not from
here; a row written before the treasure is out waits for it). Unlike the
override and alias files these rows are not temporary: they last as long as the skill does. A
`unit_id` the roster does not have, or a `since` the build does not know, is
reported by `nikke check` (`extra_element_unknown_unit`,
`extra_element_unknown_since`).

## `ranking_names.csv`

Which unit a name in the Solo Raid rankings (enikk) means, for a name two units
share. The site gives English display names only, and 라이 (392) and 레이 (831,
Ayanami Rei) are both `Rei`. Without a row the build settles such a name from
context (release date, the burst stage the deck lacks, the boss weakness) - and
for `Rei` that guessed 라이 in Water-weak seasons, where the decks (with Asuka and
Mari) show it was 레이.

```csv
name,unit_id,reason
Rei,831,"enikk 랭킹의 Rei 는 레이(아야나미 레이)..."
```

A row holds from the named unit's release on; before it the name is settled
from context as usual (`Rei` before 2024-08-29 is 라이, the only Rei there was).
Like `extra_elements.csv` these rows last as long as the site names units that
way. A name listed in `data/processed/raid_unresolved_names.csv` with two
candidates is the signal one may be needed; a `unit_id` the roster does not
have is reported by `nikke check` (`ranking_name_unknown_unit`).

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
