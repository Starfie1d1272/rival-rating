# Demo regression workflow

`rival-rating` is a pure scoring library. It cannot turn raw CS2 `.dem` files
into metrics by itself. Demo regression therefore has three stages:

1. Download match demos, prioritizing elite matches.
2. Extract `.dem` files from the downloaded archive.
3. Parse each demo with Awpy or the upstream analysis pipeline.
4. Save exported fixtures under `fixtures/account-signals-v2/*.json` and run
   `pnpm test`.

For public HLTV demo archives, create a local manifest:

```json
{
  "demos": [
    {
      "demoId": "107241",
      "matchUrl": "https://www.hltv.org/matches/2393408/...",
      "tier": "elite"
    }
  ]
}
```

Then download archives into the git-ignored cache:

```bash
pnpm demo:download demo-sources.json .demo-cache
```

Awpy is the default local parser choice for raw CS2 `.dem` files. Install it in
your Python environment first:

```bash
python3 -m pip install awpy
```

Then parse a `.dem` into the compact analysis sidecar:

```bash
pnpm demo:parse .demo-cache/<match>.dem .demo-cache/<match>.analysis.json --demo-id=107241 --tier=elite --match-url=https://...
```

The fixture test at `src/rr/models/account-regression-fixtures.test.ts` computes
both `computeValueAccountsRR` and `computeCohortAccountsRR` for each fixture.
If the fixture includes `expected.players`, it compares current scores against
the frozen values using the fixture tolerance. If not, it still verifies that
scores are finite and cohort RR anchors to mean `1.0`.

If the parser output is an analysis sidecar shaped like `{ players, kills,
rounds, match }`, generate a fixture with:

```bash
pnpm fixture:account path/to/demo.analysis.json fixtures/account-signals-v2/<match-id>.json --tier=elite --match-url=https://...
```

This converter fills the account fields available from the sidecar and leaves
unsupported context buckets as `null`, which makes the model use its documented
fallback behavior.

After reviewing the generated fixture, freeze the current scores into
`expected.players`:

```bash
pnpm fixture:freeze
```

Future `pnpm test` runs will then compare current scores to those frozen values
with the fixture tolerance.

Recommended first batch:

- 20 match/map demos total.
- Prefer elite/pro-level matches first.
- Keep each fixture source URL and local demo filename in `source`.
- Freeze expected values only after confirming the parser output is stable.

Operational notes:

- Public pro match pages such as HLTV can expose `.rar` demo downloads, but
  raw archives are only source material.
- Do not commit raw demo archives to this repository.
- Store downloaded demos outside git, parse them with the upstream analysis
  repo, then commit only compact JSON fixtures here.
- If the demo source requires login, complete login/2FA in the browser first
  or provide a direct list of match/demo URLs.
