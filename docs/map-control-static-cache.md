# CS2 Static Map-Information Cache

This cache is an independent prototype layer for map-control research. It is not
part of RR/PRISM scoring.

## Definition

For each supported map, the cache uses Awpy nav areas as the spatial unit. Under
the assumption that players are standing on the ground/navmesh, it stores:

- origin nav area -> statically visible target nav areas
- origin and target points are nav-area centroids raised by `eyeHeight`
- visibility is full 360 degree static geometry only
- FOV, yaw, smoke, flash, death state, and timing are applied later at replay time

This means the cache answers:

> Given a coordinate, which nav area does it belong to, and which map areas does
> that position statically know about?

It does not claim that a real player is currently watching all of those areas.

## Commands

Generate or resume one full map cache:

```bash
pnpm map-control:cache generate de_dust2
```

Generate a small smoke-test slice:

```bash
pnpm map-control:cache generate de_dust2 --origin-id 1
pnpm map-control:cache generate de_dust2 --area-limit 10
```

Query a game-space coordinate:

```bash
pnpm map-control:cache query de_dust2 --x 162.5 --y 25.12 --z 10 --ids-only
```

Compute and save the origin row if it is missing:

```bash
pnpm map-control:cache query de_dust2 --x 162.5 --y 25.12 --z 10 --compute-missing
```

Check cache status:

```bash
pnpm map-control:cache summary de_dust2
```

The generated files live under `.map-control-cache/static-info/` and are ignored
by git.

## Web API

The local web prototype exposes:

```text
GET /api/static-cache/de_dust2
GET /api/map-info/de_dust2?x=162.5&y=25.12&z=10&computeMissing=1
```

In the UI, clicking the radar map converts the clicked pixel back to a game
coordinate, maps it to a nav area, queries `/api/map-info`, and overlays the
static visible nav areas.

## Performance Notes

Awpy's current `VisibilityChecker` is pure Python. A precise origin row on
`de_dust2` took about 76 seconds locally and produced 110 visible nav areas.
Full-map precomputation is feasible as an offline cache job, but not as a
synchronous page-load step.

The implemented path is therefore:

- full-cache CLI for overnight/offline precomputation
- resumable generation, so interrupted work is preserved
- partial caches, so a map can be useful before every origin is complete
- web/API on-demand row computation for exploratory clicks
- replay exporter uses compatible static caches first, then falls back to direct
  Awpy LOS for uncached rows

For a production version, the heavy visibility build should move to a faster
native/WASM implementation or a precomputed artifact store.
