# AccountSignalsV2 regression fixtures

Put parsed demo fixtures here as JSON files. This library does not parse `.dem`
files directly; upstream analysis code should download and parse demos, then
export `AccountSignalsV2[]` for each match or map.

For analysis sidecars that already contain `players`, `kills`, `rounds`, and
`match`, run:

```bash
pnpm fixture:account path/to/demo.analysis.json fixtures/account-signals-v2/<match-id>.json --tier=elite --match-url=https://...
```

Then freeze expected RR outputs:

```bash
pnpm fixture:freeze
```

Fixture shape:

```json
{
  "id": "elite-match-example",
  "source": {
    "matchUrl": "https://...",
    "demoFile": "match.dem",
    "tier": "elite",
    "parsedAt": "2026-06-04T00:00:00.000Z"
  },
  "signals": [],
  "expected": {
    "tolerance": 0.000001,
    "players": [
      {
        "steamId64": "7656119...",
        "valueAccountsRR": 1.12,
        "cohortRR": 1.08
      }
    ]
  }
}
```

When `expected.players` is omitted, the regression test still checks that all
computed RR values are finite and that cohort RR anchors to mean `1.0`. Add
expected values after freezing a baseline to detect future scoring drift.
