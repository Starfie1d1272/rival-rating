# Offline common-pricing kernel v1

This optional, retrospective research kernel does not alter the published TypeScript rating. It exposes six price heads across full and five outer folds, without pickle or third-party runtime dependencies. It does not yet rebuild the complete ledger, aggregate scores or difference registry. Do not treat the prices, arithmetic closure or reference MAE as proof of causal attribution or fairness. RatingPro and HLTV are not inputs; the separately documented H2 baseline is a community approximation.

`rr-offline-round-v1` and `rr-common-pricing-v1` identify the input and policy. `parameters/round-v1.schema.json` documents structural fields; `contracts.py` additionally enforces finite values, exactly ten unique players, five per side, exact facts coverage and required utility fields. Missing facts are errors, never zero. Kill slots are retained source order; replay sorts by `(tick, source index)` and only strictly earlier ticks affect objective group-start. Same-tick order is unknown. Hypothetical subsets are sensitivity cases, not observed chronology. Objective pricing and allocation must use `price_and_allocate` with the same validated context. Explicit HP bookkeeping consistency is not independent evidence of order or actual pre-hit HP.

Run from repository root with Python 3:

```sh
python3 -m unittest discover -s tools/offline_rating/tests -v
python3 -m tools.offline_rating integrity . tools/offline_rating/parameters/integrity-v1.json
python3 -m tools.offline_rating validate tools/offline_rating/parameters/common-heads-v1.json
```

`predict` requires `--input-sha256` for its parameter file, an ordered JSON feature array, map and kind; run `python3 -m tools.offline_rating predict --help`. Integrity hashes cover frozen public parameters, fixtures, schema and implementation; they detect changes relative to the reviewed manifest, not a malicious replacement of the manifest itself. For other frozen input files, provide an explicit path-to-SHA256 manifest to `integrity`. The fold check reports internal consistency; independent expected-universe evidence is required to verify coverage and teacher label origin remains unverified. Objective contexts bind goal and round inputs, and reject duplicate source events and illegal target sides. No original player data or external reference records are included.

## Experimental ledger pipeline

`python3 -m tools.offline_rating.pipeline_cli --help` exposes normalized round batch input (`rr-offline-round-batch-v1`) or an explicit hash-verified inventory via `--input-format inventory`. Each inventory role (`rounds`, `events`, `playerRounds`, `kills`) has `path`, `sha256` and optional `format: jsonl`. Website page fragments must first be combined into a JSON array. Both hashes of the batch/inventory and parameters are required, output must be a new file, and reference values are accepted only as a separate `--references` JSON post-score join. Rich mode only replays a caller-supplied hash-verified JSONL ledger, never reprices it with common heads. The report records input, parameter and optional reference hashes, component evidence and unresolved-order limitations.

This pipeline is experimental and is **not a complete reproduction of the 3,109-record study**. Website aggregation requires a separate hash-verified season/user identity map. The post-hoc `python3 -m tools.offline_rating.differences_cli --help` entry point accepts independently hashed report, batch, reference and baseline files; it preserves arithmetic components, source evidence and unknown external residuals. Do not use it to replace the frozen study report or production ratings. Full study parity has not been verified. A small local comparison against the saved stage 3 ledger covered 30 website and 30 professional rounds; maximum component differences were 5.56e-17 and 2.78e-17 respectively. This is not full-data validation.
