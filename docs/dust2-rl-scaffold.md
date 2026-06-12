# Dust2 RL Primitive Scaffold

This scaffold connects recurrent RL to the existing Dust2 web simulator constraints. It does not define a new abstract clutch game.

## Boundary

- Environment core: `solo_clutch_trainer.dust2_mvp`.
- RL wrapper: `solo_clutch_trainer.dust2_rl.Dust2PrimitiveEnv`.
- Policy output: tactical primitive heads, not raw WASD or mouse deltas.
- Controller: the existing Dust2 tick controller executes movement, aim turn limits, weapon model, 3D LOS, sound, bomb rules, and trace serialization.
- Formal training status: Phase A/B checkpoints exist; Phase C v4 is prepared for
  a two-generation dry-run followed by a six-hour self-play run.

## Action Heads

The LSTM policy emits four discrete heads:

- `primitive`: `hold_angle`, `move_to_a`, `move_to_b`, `rotate_site`, `search_point`, `contact_clear`, `push_contact`, `take_cover`, `plant`, `defuse`, `reload`, `engage_visible`, `postplant_reposition`.
- `aimMode`: `visible_enemy`, `last_seen`, `sound_region`, `path_frontier`, `site_watch`, `bomb`.
- `moveMode`: `walk`, `run`, `hold`.
- `siteHead`: `current`, `A`, `B`.

The adapter translates these heads into the existing Dust2 action dictionary. Invalid tactical requests are not made legal by RL; they are rejected or stalled by the existing controller and objective rules.

## Observation Contract

The observation is fixed-size float32 and contains only learner-side state plus observable or remembered opponent information:

- self position, speed, hp, ammo, cooldown, aim yaw/pitch, alive flag;
- round clock, bomb state, own or currently visible plant/defuse progress, active site;
- enemy visible flag and relative position only when visible;
- last-seen and coarse sound-region memory with age;
- path-distance features to active site and bomb;
- local commit affordances for plant/defuse;
- aim-ray blocked state and recent action labels.

It intentionally does not expose hidden exact enemy position.

For Phase C, CT navigation uses the known bombsite until the planted bomb is
locally reachable. Invalid defuse, plant, reload, engage, and post-plant
primitives are literal hold/no-op actions and cannot reveal hidden coordinates
through automatic aim or routing.

## Phase C

Phase C uses two independently initialized `RecurrentPPO` policies:

- one LSTM layer with hidden size 256;
- policy MLP 64x64 and value MLP 64x64;
- alternating 4096-step T and CT updates;
- gamma 0.999 so terminal-only credit remains meaningful across 40-80 second rounds;
- 70% latest opponent and 30% non-latest history opponent sampling;
- two to four environments, adjusted only at generation boundaries;
- 80% unplanted, 10% planted A, and 10% planted B initial states.
- a 7 GB Phase C run cap, leaving the existing 2.3 GB checkpoint corpus below
  the user's 10 GB aggregate checkpoint budget.

The Phase C reward is limited to terminal outcome, kill, T plant, and the CT
pre-plant kill bonus. Damage, progress, aim, idle, shot selection, and other
behavior shaping are zero.

Environment revision `phase-c-v8-20260612` also enforces:

- Phase C has no site-selection action head, target-site state, A/B movement
  primitive, or pre-plant A/B observation feature.
- Navigation is expressed through local graph actions such as advance, branch,
  explore, search, and contact clear. The planted site is resolved only from
  the fixed map bombsite where T physically completes the plant.
- Evaluation treats any reappearance of `siteHead`, `targetSite`,
  `move_to_a`, `move_to_b`, `rotate_site`, or site-selection events as a hard
  promotion failure.
- Promotion requires T and CT independently to clear 45% cross/history win-rate floors, plus a 50% unplanted plant rate and 35% unplanted T win rate.

- 100 Hz ticks and 1800 degrees/second turn limits;
- a true 250-tick reload before ammo refills;
- seven seconds of post-kill grace, including T's opportunity to plant after
  eliminating CT;
- randomized legal initial bomb positions for planted scenarios;
- side-limited objective progress and planted-bomb position information;
- neither side receives a pre-plant target site; physical on-site and can-plant
  features refer to either fixed bombsite;
- both sides start with reproducibly randomized yaw/pitch independent of the
  hidden pre-plant site, and Phase C removes inherited macro-intent metadata;
- horizontal movement remains capped at the configured run speed during
  vertical jump/nav transitions;
- literal policy fire is never automatically withheld for low hit probability,
  while rule baselines retain their own fire-discipline threshold;
- visible engagement follows the nearest exposed hit sample to the current
  crosshair instead of automatically preferring the head.

## Reward Decomposition

The scaffold computes:

```text
R =
  terminal
  + objective_event
  + damage
  + potential_shaping
  + legality
  + anti_degenerate
```

- `terminal`: win/loss according to Dust2 bomb/elimination/timeout rules.
- `objective_event`: plant and defuse event bonuses.
- `damage`: dealt damage, taken damage, kill, death.
- `potential_shaping`: Phase A higher shaping, Phase B lower shaping.
- `legality`: invalid plant/defuse, empty fire, low-probability withheld shots.
- `anti_degenerate`: visible enemy with no response, idle non-objective behavior, short blocked aim ray without recent contact.

Normative terms remain small shaping/filter terms. They should accelerate early Phase A training without defining a single correct tactic.

## Commands

```bash
pnpm run solo-clutch:dust2-rl-check
pnpm run solo-clutch:dust2-rl-init
pnpm run solo-clutch:dust2-rl-rollout
pnpm run solo-clutch:dust2-rl-plan
pnpm run solo-clutch:dust2-rl-dry-run
```

These commands validate the env, save an untrained LSTM checkpoint, or export a random primitive trace. None of them runs formal training.

Formal training is guarded behind:

```bash
pnpm run solo-clutch:dust2-rl-train --confirm-train
```

The training supervisor runs PPO in chunks. Between chunks it samples local resource pressure, evaluates fixed seeds, writes JSONL logs, saves viewer traces, prunes checkpoints under the configured cap, and may adjust resource-level hyperparameters such as `n_envs` and `batch_size`. It does not change the observation space, action space, LSTM architecture, or reward definition online.

Phase C v8:

```bash
solo-clutch-trainer/run_phase_c_v8_dry.sh
solo-clutch-trainer/run_phase_c_v8.sh
```

Earlier Phase C checkpoints use an incompatible four-head action space and
must not be loaded into v8.
