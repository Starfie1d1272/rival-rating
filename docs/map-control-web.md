# Map Control Web Prototype

This prototype turns a CS2 `.dem` into a nav-area map-control replay.

It is intentionally separate from RR / PRISM:

- no rating
- no win probability
- no player score
- no causal zone value

## Supported Maps

The web demo only accepts maps already present in the local demo dataset:

- `de_ancient`
- `de_dust2`
- `de_inferno`
- `de_mirage`
- `de_nuke`
- `de_overpass`

Other maps are rejected until they appear in the engineering dataset.

## Setup

Create the local Python environment and install Awpy:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install awpy
```

Download Awpy map resources into the repository-local home folder:

```bash
pnpm map-control:awpy:maps
pnpm map-control:awpy:navs
pnpm map-control:awpy:tris
```

These resources live under `.awpy-home/`, which is ignored by git.

## Run

```bash
pnpm map-control:web
```

Open:

```txt
http://127.0.0.1:8787
```

The page can:

- choose a local `.demo-cache` demo
- upload a `.dem`
- parse player positions, yaw/pitch, flash duration, active smokes, and nav areas
- render map control over the Awpy radar image
- play the control timeline
- show current T / CT / contested / vacuum nav-area counts
- show low-confidence residual info from areas seen in the last N seconds
- visualize player height and pitch hints on the replay
- click a coordinate to query cached static map information
- jump to sampled control-loss events

## Accuracy Modes

Default web mode is fast:

```txt
nav area centroid + horizontal FOV + vertical FOV + smoke blocking
```

The "Static LOS" checkbox adds Awpy `.tri` visibility checks:

```txt
nav area centroid + horizontal FOV + vertical FOV + static wall LOS + smoke blocking
```

Static LOS is much more realistic but currently slow because it checks many
player-to-nav-area line segments. It should be optimized with caching or
candidate-zone pruning before becoming the default.

## Static Map Information

Static map information is cached separately from demo replay output:

```bash
pnpm map-control:cache summary de_dust2
pnpm map-control:cache generate de_dust2 --origin-id 1
pnpm map-control:cache query de_dust2 --x 162.5 --y 25.12 --z 10 --ids-only
```

The cache uses nav areas as the map unit. A clicked coordinate is mapped to a
nav area, then the UI overlays the nav areas that are statically visible from
that origin. See `docs/map-control-static-cache.md` for the cache definition and
performance notes.

## 3D Visibility

Awpy exposes player `X/Y/Z`, `yaw`, and `pitch` on demo ticks. The local nav
resources also carry nav-area corner and centroid `z`, and Awpy `.tri`
visibility checks are 3D ray tests.

The current prototype uses this in three ways:

- player eye position is `player Z + eyeHeight`
- target position is nav-area centroid raised to `targetHeight`
- pitch is converted to a positive-up view angle and filtered by `verticalFovDeg`

When Static LOS is enabled, ordinary ground positions can use the static
nav-area LOS cache. If a player's current `Z` differs from the matched nav area
by at least 18 units, the exporter treats it as height-sensitive and bypasses
the cache for that player-area ray when the `.tri` checker is available. This
lets jump peeks, boosted positions, and off-floor cover peeks be represented as
different geometry from the same 2D map coordinate.

This is still geometric, not semantic. The prototype does not yet label a play
as "boost", "jump peek", or "cover peek"; it only shows the extra information
if the elevated eye position produces a different 3D line of sight.

## Residual Info

Each frame contains direct high-confidence control:

```txt
frame.control.T / CT / contested
```

It also contains low-confidence residual info:

```txt
frame.residual.T / CT / contested
```

Residual areas are nav areas directly seen by a team within the last
`residualSeconds`, but not directly visible in the current sampled frame. The
confidence decays linearly from `1.0` to `0.0` across that window and is drawn as
a pale dashed overlay below direct control.
