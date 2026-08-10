# Pro Fixture Set 2026-06-11

This directory records the 2026-06-11 calibration snapshot used by the current
provisional-v0 professional baseline. The snapshot was generated from the
data-contract/export path available at that time and is retained for
provenance and reproducibility.

Generated from the professional-demo calibration corpus maintained in the
sibling `cs2-demo-analysis-kit` workspace at the time of the 2026-06-11
baseline freeze.

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

The snapshot is a historical v2-format export; this snapshot should not be
interpreted as the current v3 contract fixture set. The ZIPs are usable for
current DAK/RR scoring and calibration, but should not be treated as
release-clean strict contract fixtures until the exporter/schema boundary is
reconciled.
