# Pro Fixture Set 2026-06-11

Current local pro-demo calibration set generated from:

`/Users/starfie1d/GitHub/cs2-demo-analysis-kit/fixtures/demos/pro`

## Contents

- `zips/`: 52 unique `cs2-demo-format/2.0` ZIP exports.
- `reports/season-cohort.json`: DAK cohort output for the 52 ZIPs.
- `src/weights/rr-six-account-pro-baseline-v0.json`: the frozen six-account baseline derived from these ZIPs.

## Generation Notes

- Input `.dem` files: 54.
- Main batch: 51 top-level demos via `cs2dak export-batch`.
- Nested Falcons vs MOUZ BO3 folder: 3 demos exported separately.
- Final ZIP count is 52 because two nested exports duplicate top-level ZIP names, while nested map 2 produces a distinct ZIP.

## Validation Status

- Export batch: 51 ok, 0 failed, 610.5 seconds.
- DAK cohort: succeeded for 52 ZIPs.
- Strict ZIP validation: currently fails on local DAK schema drift:
  - `positions-1s.json` contains `lastPlaceName`, which the current strict schema rejects.
  - `replay.json` contains `projectiles`, which the current strict schema rejects.

These ZIPs are usable for current DAK/RR scoring and calibration, but should not be treated as release-clean strict contract fixtures until the exporter/schema boundary is reconciled.
