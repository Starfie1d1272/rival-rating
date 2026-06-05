# HLTV label fixtures

These files provide player-map targets for `scripts/fit-hltv-weights.mjs`.

HLTV Rating 2.0/2.1 formulas are not public; current HLTV match pages may expose
newer visible rating versions such as Rating 3.0. Store the visible target as
`hltvRating` and record `ratingVersion` explicitly.

```json
{
  "version": "hltv-labels-v1",
  "fixtureId": "hltv-108324-m1-nuke",
  "ratingVersion": "3.0",
  "sourceUrl": "https://www.hltv.org/matches/...",
  "labels": [
    {
      "steamId64": "76561199032006224",
      "playerName": "kyousuke",
      "hltvRating": 1.61
    }
  ]
}
```

Run a local fit:

```sh
pnpm fit:hltv --out=.demo-cache/hltv-fit/rr-hltv-fit-v1.json --metrics=.demo-cache/hltv-fit/metrics.json
```

Treat output weights as a comparison artifact until the label set is large.
