# Map Control MVP

This folder is independent from RR and PRISM. It is a first-pass control
overlay engine for CS2 demos, focused only on safe regions currently visible to
friendly players.

## Scope

MVP definition:

```txt
safe control = teammate alive + not blinded + sample is inside FOV
             + optional static LOS passes + active smokes do not block the segment
```

The module does not compute player rating, round win probability, causal zone
value, sound inference, or Shapley-style credit assignment.

## Data Model

The caller provides:

- `MapControlZone[]`: hand-authored callout zones or nav-area-derived zones.
- `MapControlTick[]`: per-tick player positions, yaw, optional pitch, and active
  smokes.
- optional `staticLineOfSight`: an adapter around awpy / map geometry. If omitted,
  static map geometry is treated as clear, so the module remains testable without
  a full CS2 map mesh.

The output is a `MapControlTimeline`:

- every frame is one demo tick/time.
- every zone has per-team visible coverage.
- overlay state is one of `T-controlled`, `CT-controlled`, `contested`, or
  `vacuum`.

## Recommended First Integration

1. Start with hand-authored Mirage zones and 2-5 sample points per zone.
2. Feed demo ticks from the analysis layer.
3. Wire `staticLineOfSight` to awpy visibility / nav geometry when available.
4. Render `MapControlTimeline.frames` as a 2D map overlay.
5. Use `detectControlLossEvents` to annotate the replay timeline.

This keeps the first deliverable explainable: "where did direct safe vision
exist, and when did it disappear?"
