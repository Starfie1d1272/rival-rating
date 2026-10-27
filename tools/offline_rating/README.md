# Offline common-pricing kernel v1

This optional, retrospective research kernel does not alter the published TypeScript rating. It exposes six price heads across full and five outer folds, without pickle or third-party runtime dependencies. It does not yet rebuild the complete ledger, aggregate scores or difference registry. Do not treat the prices, arithmetic closure or reference MAE as proof of causal attribution or fairness. RatingPro and HLTV are not inputs; the separately documented H2 baseline is a community approximation.

`rr-offline-round-v1` and `rr-common-pricing-v1` identify the input and policy. `parameters/round-v1.schema.json` documents structural fields; `contracts.py` additionally enforces finite values, exactly ten unique players, five per side, exact facts coverage and required utility fields. Missing facts are errors, never zero. Kill slots are retained source order; replay sorts by `(tick, source index)` and only strictly earlier ticks affect objective group-start. Same-tick order is unknown. Hypothetical subsets are sensitivity cases, not observed chronology. Objective pricing and allocation must use `price_and_allocate` with the same validated context. Explicit HP bookkeeping consistency is not independent evidence of order or actual pre-hit HP.

Run from repository root with Python 3:

```sh
python3 -m unittest discover -s tools/offline_rating/tests -v
python3 -m tools.offline_rating integrity . tools/offline_rating/parameters/integrity-v1.json
python3 -m tools.offline_rating validate tools/offline_rating/parameters/common-heads-v1.json
```

`predict` requires `--input-sha256` for its parameter file, an ordered JSON feature array, map and kind; run `python3 -m tools.offline_rating predict --help`. Integrity hashes cover frozen public parameters, fixtures, schema and implementation; they detect changes relative to the reviewed manifest, not a malicious replacement of the manifest itself. For other frozen input files, provide an explicit path-to-SHA256 manifest to `integrity`. The fold check verifies saved metadata coverage and consistency, including filtered head subsets; it reports label origin unverified because metadata alone cannot prove the teacher training lineage. No original player data or external reference records are included.
