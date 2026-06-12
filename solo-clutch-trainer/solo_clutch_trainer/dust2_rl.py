from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random
from typing import Any, Literal

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from . import dust2_mvp as m


Side = m.Side
RLPhase = Literal["A", "B", "C"]

PRIMITIVES: tuple[str, ...] = (
    "hold_angle",
    "move_to_a",
    "move_to_b",
    "rotate_site",
    "search_point",
    "contact_clear",
    "push_contact",
    "take_cover",
    "plant",
    "defuse",
    "reload",
    "engage_visible",
    "postplant_reposition",
)
AIM_MODES: tuple[str, ...] = (
    "visible_enemy",
    "last_seen",
    "sound_region",
    "path_frontier",
    "site_watch",
    "bomb",
)
MOVE_MODES: tuple[str, ...] = ("walk", "run", "hold")
SITE_HEADS: tuple[str, ...] = ("current", "A", "B")
OBSERVATION_SIZE = 72


@dataclass(frozen=True)
class Dust2RewardConfig:
    phase: RLPhase = "A"
    terminal_win_reward: float = 1.0
    terminal_loss_reward: float = -1.0
    plant_reward: float = 0.25
    enemy_plant_cost: float | None = None
    defuse_reward: float = 0.25
    plant_progress_reward: float = 0.0
    defuse_progress_reward: float = 0.0
    enemy_defuse_progress_cost: float = 0.0
    plant_interrupt_cost: float = 0.0
    defuse_interrupt_cost: float = 0.0
    defuse_interrupt_reward: float = 0.0
    postplant_alive_reward: float = 0.0
    damage_reward_coef: float = 0.20
    damage_taken_coef: float = 0.18
    kill_bonus: float = 0.10
    death_penalty: float = 0.10
    preplant_death_extra_penalty: float = 0.0
    preplant_ct_kill_bonus: float = 0.0
    shot_cost: float = 0.002
    empty_fire_cost: float = 0.020
    low_probability_shot_cost: float = 0.020
    invalid_objective_cost: float = 0.050
    visible_no_response_cost: float = 0.002
    idle_degenerate_cost: float = 0.001
    aim_wall_cost: float = 0.001
    phase_a_potential_coef: float = 0.080
    phase_b_potential_coef: float = 0.020
    potential_gamma: float = 0.990

    @property
    def potential_coef(self) -> float:
        return self.phase_a_potential_coef if self.phase == "A" else self.phase_b_potential_coef


@dataclass(frozen=True)
class Dust2Scenario:
    seed: int = 2607
    spawn_mode: str = "clutch_like"
    site_choice: str = "auto"
    bomb_state: m.BombStateInput = "unplanted"
    t_area_id: str | None = None
    ct_area_id: str | None = None
    learner_side: Side = "T"
    opponent_side: Side = "CT"
    static_los: bool = True
    frame_stride: int = 10


class Dust2PrimitiveEnv(gym.Env[np.ndarray, np.ndarray]):
    """Gym wrapper around the existing Dust2 simulator and viewer trace schema.

    The policy only selects high-level tactical primitives. Movement legality,
    visibility, sound, bomb rules, weapon model, acceleration, and trace payloads
    stay inside dust2_mvp.py so this cannot regress into a separate toy game.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        scenario: Dust2Scenario | None = None,
        reward_config: Dust2RewardConfig | None = None,
        config: m.Dust2Config | None = None,
    ):
        self.scenario = scenario or Dust2Scenario()
        self.reward_config = reward_config or Dust2RewardConfig()
        self.config = config or m.Dust2Config()
        self.dust2 = m.load_dust2_map()
        self.visibility = m.Visibility(enabled=self.scenario.static_los)
        self.path_cache = m.PathCache(self.dust2, self.config)
        self.action_space = spaces.MultiDiscrete(
            [len(PRIMITIVES), len(AIM_MODES), len(MOVE_MODES), len(SITE_HEADS)]
        )
        self.observation_space = spaces.Box(low=-1.0, high=1.0, shape=(OBSERVATION_SIZE,), dtype=np.float32)
        self.rng = random.Random(self.scenario.seed)
        self.state: m.RoundState | None = None
        self.frames: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.metrics: list[dict[str, Any]] = []
        self.initial_area_ids: dict[str, str] = {}
        self._last_observation = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
        self._reset_seed = self.scenario.seed

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        if seed is not None:
            self._reset_seed = int(seed)
        scenario = self._scenario_from_options(options or {})
        self.scenario = scenario
        self.rng = random.Random(self._reset_seed)
        forced_site_id = m.site_id_for_scenario(scenario.site_choice, scenario.bomb_state)
        spawn_site_id = forced_site_id or self.rng.choice(("A", "B"))
        if scenario.spawn_mode == "postplant_curriculum" and scenario.bomb_state == "unplanted":
            scenario = m.replace(scenario, bomb_state=f"planted_{spawn_site_id.lower()}")  # type: ignore[arg-type]
            self.scenario = scenario
            forced_site_id = spawn_site_id
        self.path_cache = m.PathCache(self.dust2, self.config)
        state = m.create_initial_state(
            self.dust2,
            self.config,
            self.rng,
            spawn_mode=scenario.spawn_mode,
            site_id=spawn_site_id,
            bomb_state=scenario.bomb_state,
            t_area_id=scenario.t_area_id,
            ct_area_id=scenario.ct_area_id,
            path_cache=self.path_cache,
        )
        initial_events: list[dict[str, Any]] = []
        if forced_site_id is None and scenario.bomb_state == "unplanted":
            chosen_site_id = (
                spawn_site_id
                if scenario.spawn_mode == "plant_curriculum"
                else m.choose_t_bombsite(self.dust2, self.path_cache, state.agents["T"].area_id, self.rng)
            )
            state = m.replace(
                state,
                bomb=m.replace(state.bomb, site_id=chosen_site_id),
                agents={
                    **state.agents,
                    "T": m.replace(
                        state.agents["T"],
                        macro_intent=m.sample_t_macro_intent(self.rng, scenario.bomb_state, chosen_site_id),
                    ),
                },
            )
            initial_events.append({"type": "site-choice", "tick": 0, "side": "T", "site": chosen_site_id, "mode": "auto"})
        initial_events.append({
            "type": "macro-intent",
            "tick": 0,
            "side": "T",
            "intent": state.agents["T"].macro_intent,
            "site": state.bomb.site_id,
        })
        self.state = state
        self.initial_area_ids = {"T": state.agents["T"].area_id, "CT": state.agents["CT"].area_id}
        self.events = list(initial_events)
        self.metrics = []
        self.frames = [m.frame_payload(state, initial_events, {}, self.config, self.visibility)]
        self._last_observation = self.build_observation_for_side(state, scenario.learner_side)
        return self._last_observation.copy(), {
            "seed": self._reset_seed,
            "scenario": asdict(scenario),
            "learnerSide": scenario.learner_side,
        }

    def step(self, action: np.ndarray | list[int] | tuple[int, ...]) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self.state is None:
            raise RuntimeError("reset() must be called before step().")
        if self.state.terminal is not None:
            return self._last_observation.copy(), 0.0, True, False, {"terminal": asdict(self.state.terminal)}
        action_tuple = normalize_action(action)
        rotate_target_site_id = rotate_target_for_decision(
            action_tuple,
            self.state,
            self.scenario.learner_side,
            self.dust2,
        )
        total_reward = 0.0
        reward_parts = zero_reward_parts()
        step_events: list[dict[str, Any]] = []
        for _ in range(max(1, self.config.decision_interval_ticks)):
            if self.state is None or self.state.terminal is not None:
                break
            prev_state = self.state
            primitive_action = primitive_to_dust2_action(
                action_tuple,
                self.scenario.learner_side,
                self.dust2,
                self.config,
                self.visibility,
                self.path_cache,
                prev_state,
                lock_current_site=(
                    self.scenario.spawn_mode == "plant_curriculum"
                    and self.scenario.learner_side == "T"
                    and not prev_state.bomb.planted
                ),
                rotate_target_site_id=rotate_target_site_id,
            )
            next_state, events, tick_metric = m.step_dust2_round(
                self.dust2,
                self.config,
                self.visibility,
                self.path_cache,
                prev_state,
                self.rng,
                action_overrides={self.scenario.learner_side: primitive_action},
            )
            tick_reward, tick_parts = compute_reward(
                self.scenario.learner_side,
                prev_state,
                next_state,
                primitive_action,
                events,
                tick_metric,
                self.dust2,
                self.config,
                self.visibility,
                self.reward_config,
            )
            total_reward += tick_reward
            add_reward_parts(reward_parts, tick_parts)
            self.state = next_state
            self.events.extend(events)
            self.metrics.append(tick_metric)
            step_events.extend(events)
            if (
                next_state.tick % max(1, self.scenario.frame_stride) == 0
                or next_state.terminal is not None
                or m.has_key_events(events)
            ):
                self.frames.append(m.frame_payload(next_state, events, tick_metric, self.config, self.visibility))
        self._last_observation = self.build_observation_for_side(self.state, self.scenario.learner_side)
        terminated = self.state.terminal is not None
        truncated = False
        return self._last_observation.copy(), float(total_reward), terminated, truncated, {
            "action": describe_action(action_tuple),
            "events": step_events,
            "reward": reward_parts,
            "terminal": asdict(self.state.terminal) if self.state.terminal else None,
        }

    def trace_payload(self) -> dict[str, Any]:
        if self.state is None:
            raise RuntimeError("reset() must be called before trace_payload().")
        terminal = self.state.terminal
        behavior = m.summarize_behavior(self.metrics, self.events, self.state, self.config)
        summary = {
            "winner": terminal.winner if terminal else None,
            "terminal_reason": terminal.reason if terminal else "partial-rollout",
            "terminal_tick": terminal.tick if terminal else self.state.tick,
            "terminal_seconds": round((terminal.tick if terminal else self.state.tick) * self.config.tick_seconds, 3),
            "site": self.state.bomb.site_id,
            "site_choice": self.scenario.site_choice,
            "bomb_state": self.scenario.bomb_state,
            "spawn_mode": self.scenario.spawn_mode,
            "selected_areas": self.initial_area_ids,
            "learner_side": self.scenario.learner_side,
            "behavior": behavior,
        }
        return {
            "kind": "dust2-solo-clutch-rl-primitive-trace",
            "schemaVersion": "dust2-solo-clutch-rl-primitive-0.1",
            "seed": self._reset_seed,
            "config": m.config_payload(self.config),
            "knowledge": m.knowledge_payload(),
            "rl": {
                "observationSize": OBSERVATION_SIZE,
                "actionSpace": {
                    "primitive": list(PRIMITIVES),
                    "aimMode": list(AIM_MODES),
                    "moveMode": list(MOVE_MODES),
                    "siteHead": list(SITE_HEADS),
                },
                "rewardConfig": asdict(self.reward_config),
                "status": "scaffold-only-no-formal-training-started",
            },
            "map": m.map_payload(self.dust2),
            "summary": summary,
            "frames": self.frames,
            "events": self.events,
        }

    def _scenario_from_options(self, options: dict[str, Any]) -> Dust2Scenario:
        if not options:
            return self.scenario
        data = asdict(self.scenario)
        data.update({key: value for key, value in options.items() if value is not None and key in data})
        return Dust2Scenario(**data)

    def build_observation_for_side(self, state: m.RoundState, side: Side) -> np.ndarray:
        agent = state.agents[side]
        enemy = state.agents["CT" if side == "T" else "T"]
        site_id_known = side == "T" or state.bomb.planted
        observable_site_id = observable_current_site_id(
            side,
            state,
            self.dust2,
        )
        site = self.dust2.bomb_sites[observable_site_id]
        bounds = map_bounds(self.dust2)
        visible_enemy = m.can_see(agent, enemy, self.dust2, self.config, self.visibility, state.utilities)
        visible_plant_progress = (
            state.bomb.plant_progress_ticks
            if side == "T" or visible_enemy
            else 0
        )
        visible_defuse_progress = (
            state.bomb.defuse_progress_ticks
            if side == "CT" or visible_enemy
            else 0
        )
        path_to_site = self.path_cache.path(agent.area_id, m.site_representative_area_id(self.dust2, site))
        site_path_distance = m.path_distance(self.dust2, path_to_site) if path_to_site else m.distance2(agent.position, site.position)
        bomb_position = (
            state.bomb.position
            if side == "T" or can_commit_defuse(side, agent, state, site, self.config)
            else site.position
        ) or site.position
        path_to_bomb = self.path_cache.path(agent.area_id, m.nearest_area_id(self.dust2, bomb_position))
        bomb_path_distance = m.path_distance(self.dust2, path_to_bomb) if path_to_bomb else m.distance2(agent.position, bomb_position)
        aim_endpoint, aim_blocked = m.aim_ray_endpoint(agent, self.config, self.visibility, state.utilities)
        values: list[float] = [
            1.0 if side == "T" else -1.0,
            scale01(state.tick, self.config.round_ticks),
            1.0 if state.bomb.planted else -1.0,
            1.0 if state.bomb.defused else -1.0,
            scale01(visible_plant_progress, self.config.plant_ticks),
            scale01(visible_defuse_progress, self.config.defuse_ticks),
            scale01(
                0 if state.bomb.planted_at_tick is None else state.tick - state.bomb.planted_at_tick,
                self.config.bomb_timer_ticks,
            ),
            (1.0 if state.bomb.site_id == "A" else -1.0) if site_id_known else 0.0,
            *normalized_position(agent.position, bounds),
            normalized_velocity(agent.velocity, self.config.run_speed_per_tick),
            clamp_unit(agent.hp * 2.0 - 1.0),
            scale01(agent.ammo, self.config.max_ammo),
            scale01(
                max(agent.fire_cooldown_ticks, agent.reload_cooldown_ticks),
                max(self.config.reload_cooldown_ticks, self.config.fire_cooldown_ticks),
            ),
            math.sin(math.radians(agent.aim_deg)),
            math.cos(math.radians(agent.aim_deg)),
            clamp_unit(agent.aim_pitch_deg / 89.0),
            clamp_unit(agent.aim_turn_delta_deg / self.config.max_turn_deg_per_tick),
            clamp_unit(agent.aim_pitch_turn_delta_deg / self.config.max_pitch_turn_deg_per_tick),
            1.0 if agent.is_alive else -1.0,
            1.0 if enemy.is_alive else -1.0,
            1.0 if visible_enemy else -1.0,
        ]
        values.extend(relative_observation(agent.position, enemy.position if visible_enemy else None, bounds))
        values.extend(memory_position_observation(agent, agent.last_seen_position, agent.last_seen_tick, state.tick, bounds, 3.5, self.config))
        values.extend(memory_position_observation(agent, agent.last_sound_position, agent.last_sound_tick, state.tick, bounds, 3.5, self.config))
        values.extend([
            distance_feature(site_path_distance),
            distance_feature(bomb_path_distance),
            (
                1.0
                if (
                    m.is_on_bomb_site(self.dust2, site, agent)
                    if site_id_known
                    else any(
                        m.is_on_bomb_site(self.dust2, candidate, agent)
                        for candidate in self.dust2.bomb_sites.values()
                    )
                )
                else -1.0
            ),
            1.0 if can_commit_plant(side, agent, site, state, self.dust2, self.config) else -1.0,
            1.0 if can_commit_defuse(side, agent, state, site, self.config) else -1.0,
            1.0 if aim_blocked else -1.0,
            distance_feature(m.distance3(agent.position, aim_endpoint)),
            action_label_feature(agent.action_label, "search-point"),
            action_label_feature(agent.action_label, "contact-clear"),
            action_label_feature(agent.action_label, "engage-visible"),
            action_label_feature(agent.action_label, "plant"),
            action_label_feature(agent.action_label, "defuse"),
        ])
        values.extend(one_hot_index(PRIMITIVES, agent.action_label.replace("rl-", ""), default=-1))
        padded = (values + [0.0] * OBSERVATION_SIZE)[:OBSERVATION_SIZE]
        return np.asarray([clamp_unit(value) for value in padded], dtype=np.float32)

    def _build_observation(self, state: m.RoundState) -> np.ndarray:
        return self.build_observation_for_side(state, self.scenario.learner_side)


def primitive_to_dust2_action(
    action_tuple: tuple[int, int, int, int],
    side: Side,
    dust2: m.Dust2Map,
    config: m.Dust2Config,
    visibility: m.Visibility,
    path_cache: m.PathCache,
    state: m.RoundState,
    *,
    lock_current_site: bool = False,
    literal_actions: bool = False,
    rotate_target_site_id: str | None = None,
    strategic_target_site_id: str | None = None,
    emit_site_override: bool = True,
) -> dict[str, Any]:
    if literal_actions:
        return primitive_to_literal_dust2_action(
            action_tuple,
            side,
            dust2,
            config,
            visibility,
            path_cache,
            state,
            rotate_target_site_id=rotate_target_site_id,
            strategic_target_site_id=strategic_target_site_id,
            emit_site_override=emit_site_override,
        )
    primitive = PRIMITIVES[action_tuple[0]]
    aim_mode = AIM_MODES[action_tuple[1]]
    move_mode = MOVE_MODES[action_tuple[2]]
    site_head = SITE_HEADS[action_tuple[3]]
    agent = state.agents[side]
    enemy_side: Side = "CT" if side == "T" else "T"
    enemy = state.agents[enemy_side]
    site_id = selected_site_id(site_head, state.bomb.site_id)
    site = dust2.bomb_sites[site_id]
    current_site = dust2.bomb_sites[state.bomb.site_id]
    visible_enemy = m.can_see(agent, enemy, dust2, config, visibility, state.utilities)
    site_area = m.site_representative_area_id(dust2, site)
    label = f"rl-{primitive}"
    lock_plant_route = lock_current_site and side == "T" and not state.bomb.planted

    if not agent.is_alive:
        return base_action(agent, agent.position, "dead", "hold", "walk", label="dead")

    if primitive == "reload" or agent.ammo <= 0 and primitive == "engage_visible":
        return {**base_action(agent, aim_for_mode(aim_mode, agent, enemy, state, dust2, config, visibility, path_cache, site), "reload", "hold", "walk", label=label), "reload": True}

    if primitive == "engage_visible" and visible_enemy:
        aim_target = m.visible_combat_aim_point(agent, enemy, config, visibility, state.utilities)
        return base_action(
            agent,
            aim_target,
            "enemy",
            "hold",
            "walk",
            fire=(
                agent.fire_cooldown_ticks == 0
                and agent.reload_cooldown_ticks == 0
                and agent.ammo > 0
            ),
            label=label,
        )

    if visible_enemy and primitive in {"hold_angle", "search_point", "contact_clear", "push_contact", "postplant_reposition"}:
        aim_target = m.visible_combat_aim_point(agent, enemy, config, visibility, state.utilities)
        return base_action(
            agent,
            aim_target,
            "enemy",
            "hold",
            "walk",
            fire=(
                agent.fire_cooldown_ticks == 0
                and agent.reload_cooldown_ticks == 0
                and agent.ammo > 0
            ),
            label=f"{label}-reactive-engage",
        )

    if primitive == "plant":
        target_site = current_site if side == "T" else site
        return {
            **base_action(agent, target_site.position, "bomb", "hold", "walk", plant=side == "T", label=label),
            "site_id": target_site.site_id if side == "T" else state.bomb.site_id,
        }

    if primitive == "defuse":
        bomb_position = state.bomb.position or current_site.position
        bomb_area = m.nearest_area_id(dust2, bomb_position)
        move = "hold" if distance_or_current(agent, bomb_position) <= current_site.radius * 0.55 else "route"
        return {
            **base_action(
                agent,
                bomb_position,
                "bomb",
                move,
                "walk",
                target_area=bomb_area,
                defuse=side == "CT",
                label=label,
            ),
            "site_id": state.bomb.site_id,
        }

    if side == "T" and state.bomb.planted and primitive != "engage_visible" and not visible_enemy:
        postplant_action = safe_postplant_action(
            agent,
            enemy,
            state,
            dust2,
            current_site,
            config,
            visibility,
            path_cache,
            label,
            "wide" if move_mode == "run" or site_head != "current" else "close",
        )
        if postplant_action is not None:
            return postplant_action

    if primitive in {"hold_angle", "search_point", "contact_clear", "take_cover", "postplant_reposition"}:
        auto_plant = safe_auto_plant_action(side, agent, state, dust2, current_site, config, visible_enemy, label)
        if auto_plant is not None:
            return auto_plant

    if lock_plant_route and not visible_enemy and m.recent_contact_position(agent, state, config) is None:
        current_site_area = m.site_representative_area_id(dust2, current_site)
        return {
            **route_action(
                agent,
                current_site_area,
                current_site.position,
                aim_mode,
                state,
                dust2,
                config,
                visibility,
                path_cache,
                "run" if move_mode == "run" else "walk",
                f"{label}-curriculum-route",
            ),
            "site_id": current_site.site_id,
        }

    if primitive == "move_to_a":
        site = dust2.bomb_sites["A"]
        site_area = m.site_representative_area_id(dust2, site)
        auto_plant = safe_auto_plant_action(side, agent, state, dust2, site, config, visible_enemy, label)
        if auto_plant is not None:
            return auto_plant
        return {
            **route_action(agent, site_area, site.position, aim_mode, state, dust2, config, visibility, path_cache, move_mode, label),
            "site_id": "A" if side == "T" else state.bomb.site_id,
        }

    if primitive == "move_to_b":
        site = dust2.bomb_sites["B"]
        site_area = m.site_representative_area_id(dust2, site)
        auto_plant = safe_auto_plant_action(side, agent, state, dust2, site, config, visible_enemy, label)
        if auto_plant is not None:
            return auto_plant
        return {
            **route_action(agent, site_area, site.position, aim_mode, state, dust2, config, visibility, path_cache, move_mode, label),
            "site_id": "B" if side == "T" else state.bomb.site_id,
        }

    if primitive == "rotate_site":
        next_site_id = rotate_target_site_id or ("B" if state.bomb.site_id == "A" else "A")
        site = dust2.bomb_sites[next_site_id]
        site_area = m.site_representative_area_id(dust2, site)
        auto_plant = safe_auto_plant_action(side, agent, state, dust2, site, config, visible_enemy, label)
        if auto_plant is not None:
            return auto_plant
        return {
            **route_action(agent, site_area, site.position, aim_mode, state, dust2, config, visibility, path_cache, move_mode, label),
            "site_id": next_site_id if side == "T" else state.bomb.site_id,
        }

    if primitive == "take_cover":
        if visible_enemy:
            target_area = m.choose_cover_area(dust2, config, visibility, state.utilities, agent, enemy, random.Random(state.tick + len(agent.area_id)))
            aim_target = m.visible_combat_aim_point(agent, enemy, config, visibility, state.utilities)
            return base_action(agent, aim_target, "enemy", "route", "walk", target_area=target_area, label=label)
        aim_target = aim_for_mode(aim_mode, agent, enemy, state, dust2, config, visibility, path_cache, site)
        return base_action(agent, aim_target, "scan", "hold", "walk", label=label)

    if primitive in {"search_point", "contact_clear"}:
        target_position = m.recent_contact_position(agent, state, config) or (state.bomb.position or site.position)
        target_area = m.nearest_area_id(dust2, target_position)
        aim_target = m.choose_clear_angle_target(dust2, path_cache, agent, state, target_area, target_position, config)
        move = "route" if primitive == "contact_clear" else "route"
        return base_action(agent, aim_target, "clear", move, "walk", target_area=target_area, label=label)

    if primitive == "push_contact":
        target_position = m.recent_contact_position(agent, state, config) or (state.bomb.position or site.position)
        target_area = m.nearest_area_id(dust2, target_position)
        aim_target = aim_for_mode("last_seen" if agent.last_seen_position else "sound_region", agent, enemy, state, dust2, config, visibility, path_cache, site)
        return base_action(agent, aim_target, "contact", "route", "run", target_area=target_area, label=label)

    if primitive == "postplant_reposition":
        if state.bomb.planted and side == "T":
            hold_area = m.choose_hold_area(dust2, path_cache, agent.area_id, m.site_representative_area_id(dust2, current_site), random.Random(state.tick))
            aim_target = m.choose_site_watch_target(dust2, path_cache, agent, state, current_site, config)
            return base_action(agent, aim_target, "watch", "route", "walk", target_area=hold_area, label=label)
        bomb_position = state.bomb.position or current_site.position
        bomb_area = m.nearest_area_id(dust2, bomb_position)
        aim_target = m.choose_site_watch_target(dust2, path_cache, agent, state, current_site, config)
        return base_action(agent, aim_target, "watch", "route", "run", target_area=bomb_area, label=label)

    target_area = site_area
    aim_target = aim_for_mode(aim_mode, agent, enemy, state, dust2, config, visibility, path_cache, site)
    move = "hold" if primitive == "hold_angle" or move_mode == "hold" else "route"
    return {
        **base_action(
            agent,
            aim_target,
            aim_context_for_mode(aim_mode),
            move,
            "run" if move_mode == "run" else "walk",
            target_area=target_area,
            label=label,
        ),
        "site_id": site.site_id if side == "T" else state.bomb.site_id,
    }


def primitive_to_literal_dust2_action(
    action_tuple: tuple[int, int, int, int],
    side: Side,
    dust2: m.Dust2Map,
    config: m.Dust2Config,
    visibility: m.Visibility,
    path_cache: m.PathCache,
    state: m.RoundState,
    *,
    rotate_target_site_id: str | None = None,
    strategic_target_site_id: str | None = None,
    emit_site_override: bool = True,
) -> dict[str, Any]:
    primitive = PRIMITIVES[action_tuple[0]]
    aim_mode = AIM_MODES[action_tuple[1]]
    move_mode = MOVE_MODES[action_tuple[2]]
    site_head = SITE_HEADS[action_tuple[3]]
    agent = state.agents[side]
    enemy_side: Side = "CT" if side == "T" else "T"
    enemy = state.agents[enemy_side]
    objective_site_id = (
        strategic_target_site_id
        if side == "T" and not state.bomb.planted and strategic_target_site_id in dust2.bomb_sites
        else state.bomb.site_id
    )
    selected_id = (
        selected_site_id(site_head, objective_site_id)
        if side == "T" or state.bomb.planted
        else (
            site_head
            if site_head in {"A", "B"}
            else observable_current_site_id(side, state, dust2)
        )
    )
    selected_site = dust2.bomb_sites[selected_id]
    current_site = dust2.bomb_sites[objective_site_id]
    visible_enemy = m.can_see(agent, enemy, dust2, config, visibility, state.utilities)
    label = f"rl-{primitive}"

    if not agent.is_alive:
        return base_action(agent, agent.position, "dead", "hold", "walk", label="dead")

    if primitive == "reload":
        if agent.ammo >= config.max_ammo or agent.reload_cooldown_ticks > 0:
            return literal_no_op(agent, config, visibility, state, label)
        aim_target = aim_for_mode(
            aim_mode, agent, enemy, state, dust2, config, visibility, path_cache, selected_site
        )
        return {
            **base_action(agent, aim_target, aim_context_for_mode(aim_mode), "hold", "walk", label=label),
            "reload": True,
        }

    if primitive == "engage_visible":
        if agent.ammo <= 0 or agent.reload_cooldown_ticks > 0:
            return literal_no_op(agent, config, visibility, state, label)
        if not visible_enemy:
            aim_target = aim_for_mode(
                aim_mode, agent, enemy, state, dust2, config, visibility, path_cache, selected_site
            )
            return base_action(agent, aim_target, aim_context_for_mode(aim_mode), "hold", "walk", label=label)
        return {
            **base_action(
                agent,
                literal_visible_combat_aim_point(
                    agent,
                    enemy,
                    config,
                    visibility,
                    state.utilities,
                ),
                "enemy",
                "hold",
                "walk",
                fire=(
                    agent.fire_cooldown_ticks == 0
                    and agent.reload_cooldown_ticks == 0
                    and agent.ammo > 0
                ),
                label=label,
            ),
            "force_fire": True,
        }

    if primitive == "plant":
        physical_site = next(
            (
                candidate
                for candidate in dust2.bomb_sites.values()
                if m.is_on_bomb_site(dust2, candidate, agent)
            ),
            None,
        )
        if (
            physical_site is None
            or not can_commit_plant(side, agent, physical_site, state, dust2, config)
        ):
            return literal_no_op(agent, config, visibility, state, label)
        plant_action = {
            **base_action(
                agent,
                physical_site.position,
                "bomb",
                "hold",
                "walk",
                plant=side == "T",
                label=label,
            ),
        }
        if emit_site_override:
            plant_action["site_id"] = physical_site.site_id
        return plant_action

    if primitive == "defuse":
        if not can_commit_defuse(side, agent, state, current_site, config):
            return literal_no_op(agent, config, visibility, state, label)
        bomb_position = state.bomb.position or current_site.position
        return {
            **base_action(
                agent,
                bomb_position,
                "bomb",
                "hold",
                "walk",
                defuse=side == "CT",
                label=label,
            ),
            "site_id": current_site.site_id,
        }

    if primitive in {"move_to_a", "move_to_b", "rotate_site"}:
        target_id = (
            strategic_target_site_id
            if side == "T" and strategic_target_site_id in dust2.bomb_sites
            else (
                "A"
                if primitive == "move_to_a"
                else "B"
                if primitive == "move_to_b"
                else (
                    rotate_target_site_id
                    or ("B" if objective_site_id == "A" else "A")
                )
            )
        )
        target_site = dust2.bomb_sites[target_id]
        target_area = m.site_representative_area_id(dust2, target_site)
        route = {
            **route_action(
                agent,
                target_area,
                target_site.position,
                aim_mode,
                state,
                dust2,
                config,
                visibility,
                path_cache,
                move_mode,
                label,
            ),
        }
        if emit_site_override:
            route["site_id"] = target_id if side == "T" else state.bomb.site_id
        return route
    if primitive == "take_cover":
        target_area = m.choose_cover_area(
            dust2,
            config,
            visibility,
            state.utilities,
            agent,
            enemy,
            random.Random(state.tick + (0 if side == "T" else 1)),
        )
        aim_target = aim_for_mode(
            aim_mode, agent, enemy, state, dust2, config, visibility, path_cache, selected_site
        )
        return base_action(
            agent,
            aim_target,
            aim_context_for_mode(aim_mode),
            "route",
            "walk",
            target_area=target_area,
            label=label,
        )

    if primitive in {"search_point", "contact_clear", "push_contact"}:
        target_position = m.recent_contact_position(agent, state, config) or (
            (
                state.bomb.position
                if side == "T" or can_commit_defuse(side, agent, state, current_site, config)
                else None
            )
            or selected_site.position
        )
        target_area = m.nearest_area_id(dust2, target_position)
        aim_target = (
            m.choose_clear_angle_target(
                dust2, path_cache, agent, state, target_area, target_position, config
            )
            if primitive != "push_contact"
            else aim_for_mode(
                aim_mode, agent, enemy, state, dust2, config, visibility, path_cache, selected_site
            )
        )
        return base_action(
            agent,
            aim_target,
            "clear" if primitive != "push_contact" else aim_context_for_mode(aim_mode),
            "route",
            "run" if primitive == "push_contact" else "walk",
            target_area=target_area,
            label=label,
        )

    if primitive == "postplant_reposition":
        if not state.bomb.planted:
            return literal_no_op(agent, config, visibility, state, label)
        objective_position = (
            state.bomb.position
            if side == "T" or can_commit_defuse(side, agent, state, current_site, config)
            else current_site.position
        ) or current_site.position
        objective_area = (
            m.nearest_area_id(dust2, objective_position)
            if side == "T" or can_commit_defuse(side, agent, state, current_site, config)
            else m.site_representative_area_id(dust2, current_site)
        )
        aim_target = aim_for_mode(
            aim_mode, agent, enemy, state, dust2, config, visibility, path_cache, current_site
        )
        return base_action(
            agent,
            aim_target,
            aim_context_for_mode(aim_mode),
            "route",
            move_mode,
            target_area=objective_area,
            label=label,
        )

    aim_target = aim_for_mode(
        aim_mode, agent, enemy, state, dust2, config, visibility, path_cache, selected_site
    )
    return base_action(
        agent,
        aim_target,
        aim_context_for_mode(aim_mode),
        "hold",
        "walk",
        label=label,
    )


def literal_visible_combat_aim_point(
    shooter: m.AgentState,
    target: m.AgentState,
    config: m.Dust2Config,
    visibility: m.Visibility,
    utilities: tuple[m.UtilityCloud, ...],
) -> m.Vec3:
    samples = m.visible_hit_samples(
        shooter.position,
        target.position,
        config,
        visibility,
        utilities,
    )
    if not samples:
        return m.combat_aim_point(target, config)
    origin = m.eye_position(shooter.position, config.eye_height)
    direction = m.aim_direction(shooter.aim_deg, shooter.aim_pitch_deg)
    return min(
        samples,
        key=lambda sample: (
            m.closest_distance_ray_point(origin, direction, sample.point),
            m.distance3(origin, sample.point),
        ),
    ).point


def literal_no_op(
    agent: m.AgentState,
    config: m.Dust2Config,
    visibility: m.Visibility,
    state: m.RoundState,
    label: str,
) -> dict[str, Any]:
    aim_target, _ = m.aim_ray_endpoint(agent, config, visibility, state.utilities)
    return base_action(agent, aim_target, agent.aim_context, "hold", "walk", label=label)


def rotate_target_for_decision(
    action_tuple: tuple[int, int, int, int] | None,
    state: m.RoundState,
    side: Side,
    dust2: m.Dust2Map,
) -> str | None:
    if action_tuple is None or PRIMITIVES[action_tuple[0]] != "rotate_site":
        return None
    current_site_id = observable_current_site_id(side, state, dust2)
    return "B" if current_site_id == "A" else "A"


def observable_current_site_id(
    side: Side,
    state: m.RoundState,
    dust2: m.Dust2Map,
) -> str:
    if side == "T" or state.bomb.planted:
        return state.bomb.site_id
    agent = state.agents[side]
    return min(
        ("A", "B"),
        key=lambda site_id: m.distance2(
            agent.position,
            dust2.bomb_sites[site_id].position,
        ),
    )


def compute_reward(
    side: Side,
    previous: m.RoundState,
    state: m.RoundState,
    action: dict[str, Any],
    events: list[dict[str, Any]],
    tick_metric: dict[str, Any],
    dust2: m.Dust2Map,
    config: m.Dust2Config,
    visibility: m.Visibility,
    reward_config: Dust2RewardConfig,
) -> tuple[float, dict[str, float]]:
    enemy_side: Side = "CT" if side == "T" else "T"
    parts = zero_reward_parts()
    for event in events:
        if event.get("type") == "shot":
            if event.get("shooter") == side:
                parts["damage"] += float(event.get("damage", 0.0)) * reward_config.damage_reward_coef
                parts["shotCost"] -= reward_config.shot_cost
            if event.get("target") == side:
                parts["damageTaken"] -= float(event.get("damage", 0.0)) * reward_config.damage_taken_coef
        if event.get("type") == "withheld-shot" and event.get("shooter") == side:
            parts["lowProbabilityShot"] -= reward_config.low_probability_shot_cost
        if event.get("type") == "bomb-planted":
            if side == "T":
                parts["objective"] += reward_config.plant_reward
            else:
                enemy_plant_cost = (
                    reward_config.plant_reward
                    if reward_config.enemy_plant_cost is None
                    else reward_config.enemy_plant_cost
                )
                parts["objective"] -= enemy_plant_cost
        if event.get("type") == "plant-progress" and side == "T":
            parts["objective"] += reward_config.plant_progress_reward
        if event.get("type") == "bomb-defused":
            parts["objective"] += reward_config.defuse_reward if side == "CT" else -reward_config.defuse_reward
        if event.get("type") == "defuse-progress" and side == "CT":
            parts["objective"] += reward_config.defuse_progress_reward
        if event.get("type") == "defuse-progress" and side == "T":
            parts["objective"] -= reward_config.enemy_defuse_progress_cost
    if (
        side == "T"
        and previous.bomb.plant_progress_ticks > 0
        and not state.bomb.planted
        and state.bomb.plant_progress_ticks == 0
    ):
        parts["objective"] -= reward_config.plant_interrupt_cost
    if (
        side == "CT"
        and previous.bomb.defuse_progress_ticks > 0
        and state.bomb.planted
        and state.bomb.defuse_progress_ticks == 0
    ):
        parts["objective"] -= reward_config.defuse_interrupt_cost
    if (
        side == "T"
        and previous.bomb.defuse_progress_ticks > 0
        and state.bomb.planted
        and state.bomb.defuse_progress_ticks == 0
    ):
        parts["objective"] += reward_config.defuse_interrupt_reward
    if side == "T" and state.bomb.planted and state.agents[side].is_alive and state.terminal is None:
        parts["objective"] += reward_config.postplant_alive_reward
    if previous.agents[enemy_side].is_alive and not state.agents[enemy_side].is_alive:
        parts["kill"] += reward_config.kill_bonus
        if side == "CT" and not previous.bomb.planted:
            parts["kill"] += reward_config.preplant_ct_kill_bonus
    if previous.agents[side].is_alive and not state.agents[side].is_alive:
        parts["death"] -= reward_config.death_penalty
        if side == "T" and not state.bomb.planted:
            parts["death"] -= reward_config.preplant_death_extra_penalty
    if state.terminal is not None:
        parts["terminal"] += reward_config.terminal_win_reward if state.terminal.winner == side else reward_config.terminal_loss_reward
    if action.get("fire") and previous.agents[side].ammo <= 0:
        parts["emptyFire"] -= reward_config.empty_fire_cost
    if action.get("plant") and not any(event.get("type") == "plant-progress" for event in events):
        parts["invalidObjective"] -= reward_config.invalid_objective_cost
    if action.get("defuse") and not any(event.get("type") == "defuse-progress" for event in events):
        parts["invalidObjective"] -= reward_config.invalid_objective_cost
    side_metric = tick_metric.get(side, {})
    if side_metric.get("enemyVisible") and not action.get("fire") and action.get("label") not in {"rl-take_cover"}:
        parts["visibleNoResponse"] -= reward_config.visible_no_response_cost
    agent = state.agents[side]
    if (
        agent.is_alive
        and m.vector_length(agent.velocity) <= config.stall_speed_units_per_tick
        and action.get("label") not in {"rl-hold_angle", "rl-engage_visible", "rl-plant", "rl-defuse", "rl-reload"}
    ):
        parts["idle"] -= reward_config.idle_degenerate_cost
    aim_endpoint, aim_blocked = m.aim_ray_endpoint(agent, config, visibility, state.utilities)
    if aim_blocked and m.distance3(agent.position, aim_endpoint) < 180.0 and not m.has_recent_contact(agent, state, config):
        parts["aimWall"] -= reward_config.aim_wall_cost
    coef = reward_config.potential_coef
    if coef:
        parts["potential"] += coef * (
            reward_config.potential_gamma * potential(side, state, dust2, config)
            - potential(side, previous, dust2, config)
        )
    total = sum(parts.values())
    return total, parts


def potential(side: Side, state: m.RoundState, dust2: m.Dust2Map, config: m.Dust2Config) -> float:
    agent = state.agents[side]
    site = dust2.bomb_sites[state.bomb.site_id]
    if not agent.is_alive:
        return -1.0
    if side == "T":
        if state.bomb.planted:
            elapsed = 0 if state.bomb.planted_at_tick is None else state.tick - state.bomb.planted_at_tick
            return clamp_unit(0.3 + elapsed / max(1, config.bomb_timer_ticks))
        site_distance = m.distance2(agent.position, site.position)
        site_score = 1.0 - min(site_distance / 1800.0, 1.0)
        plant_score = state.bomb.plant_progress_ticks / max(1, config.plant_ticks)
        return clamp_unit(site_score * 0.6 + plant_score * 0.4)
    if state.bomb.planted:
        bomb_position = state.bomb.position or site.position
        bomb_distance = m.distance2(agent.position, bomb_position)
        retake_score = 1.0 - min(bomb_distance / 1800.0, 1.0)
        defuse_score = state.bomb.defuse_progress_ticks / max(1, config.defuse_ticks)
        return clamp_unit(retake_score * 0.55 + defuse_score * 0.45)
    t_alive = 1.0 if state.agents["T"].is_alive else -1.0
    return clamp_unit(t_alive * -0.2 + (1.0 - state.tick / max(1, config.round_ticks)) * 0.6)


def base_action(
    agent: m.AgentState,
    aim_target: m.Vec3,
    aim_context: str,
    move: str,
    mode: str,
    *,
    target_area: str | None = None,
    fire: bool = False,
    plant: bool = False,
    defuse: bool = False,
    label: str,
) -> dict[str, Any]:
    action = {
        "move": move,
        "mode": mode,
        "target": agent.position,
        "aim_target": aim_target,
        "aim_context": aim_context,
        "fire": fire,
        "plant": plant,
        "defuse": defuse,
        "utility": None,
        "label": label,
    }
    if target_area is not None:
        action["target_area"] = target_area
    return action


def safe_auto_plant_action(
    side: Side,
    agent: m.AgentState,
    state: m.RoundState,
    dust2: m.Dust2Map,
    site: m.BombSite,
    config: m.Dust2Config,
    visible_enemy: bool,
    label: str,
) -> dict[str, Any] | None:
    if side != "T" or state.bomb.planted or visible_enemy:
        return None
    if not m.is_on_bomb_site(dust2, site, agent):
        return None
    if m.has_recent_contact(agent, state, config):
        return None
    return {
        **base_action(agent, site.position, "bomb", "hold", "walk", plant=True, label=f"{label}-auto-plant"),
        "site_id": site.site_id,
    }


def safe_postplant_action(
    agent: m.AgentState,
    enemy: m.AgentState,
    state: m.RoundState,
    dust2: m.Dust2Map,
    site: m.BombSite,
    config: m.Dust2Config,
    visibility: m.Visibility,
    path_cache: m.PathCache,
    label: str,
    style: str,
) -> dict[str, Any] | None:
    if not state.bomb.planted or not agent.is_alive:
        return None
    bomb_position = state.bomb.position or site.position
    hold_area = m.choose_postplant_hold_area(dust2, path_cache, agent, enemy, state, site, config, visibility, style)
    can_watch_now = m.can_watch_bomb_from_position(agent.position, bomb_position, config, visibility, state.utilities)
    if state.bomb.defuse_progress_ticks > 0:
        aim_target = m.default_aim_point(bomb_position, config)
        aim_context = "bomb"
    else:
        aim_target = m.choose_postplant_watch_target(dust2, path_cache, agent, state, site, config, visibility)
        aim_context = "watch"
    move = "hold" if hold_area == agent.area_id else "route"
    mode = "run" if state.bomb.defuse_progress_ticks > 0 and not can_watch_now else "walk"
    deny_defuse_fire = (
        state.bomb.defuse_progress_ticks > 0
        and can_watch_now
        and agent.fire_cooldown_ticks == 0
        and agent.reload_cooldown_ticks == 0
        and agent.ammo > 0
    )
    return {
        **base_action(
            agent,
            aim_target,
            aim_context,
            move,
            mode,
            target_area=hold_area,
            fire=deny_defuse_fire,
            label=f"{label}-postplant-anchor",
        ),
        "site_id": site.site_id,
    }


def route_action(
    agent: m.AgentState,
    target_area: str,
    fallback: m.Vec3,
    aim_mode: str,
    state: m.RoundState,
    dust2: m.Dust2Map,
    config: m.Dust2Config,
    visibility: m.Visibility,
    path_cache: m.PathCache,
    move_mode: str,
    label: str,
) -> dict[str, Any]:
    enemy = state.agents["CT" if agent.side == "T" else "T"]
    site = dust2.bomb_sites[state.bomb.site_id]
    if aim_mode == "path_frontier":
        aim_target = m.choose_path_search_target(dust2, path_cache, agent, state, target_area, fallback, config)
        aim_context = "path"
    else:
        aim_target = aim_for_mode(aim_mode, agent, enemy, state, dust2, config, visibility, path_cache, site)
        aim_context = aim_context_for_mode(aim_mode)
    move = "hold" if move_mode == "hold" else "route"
    mode = "run" if move_mode == "run" else "walk"
    return base_action(agent, aim_target, aim_context, move, mode, target_area=target_area, label=label)


def aim_for_mode(
    aim_mode: str,
    agent: m.AgentState,
    enemy: m.AgentState,
    state: m.RoundState,
    dust2: m.Dust2Map,
    config: m.Dust2Config,
    visibility: m.Visibility,
    path_cache: m.PathCache,
    site: m.BombSite,
) -> m.Vec3:
    if aim_mode == "visible_enemy" and m.can_see(agent, enemy, dust2, config, visibility, state.utilities):
        return m.combat_aim_point(enemy, config)
    if aim_mode == "last_seen" and agent.last_seen_position is not None:
        return m.default_aim_point(agent.last_seen_position, config)
    if aim_mode == "sound_region" and agent.last_sound_position is not None:
        return m.default_aim_point(agent.last_sound_position, config)
    if aim_mode == "path_frontier":
        target_area = agent.target_area_id or m.site_representative_area_id(dust2, site)
        return m.choose_path_search_target(dust2, path_cache, agent, state, target_area, site.position, config)
    if aim_mode == "site_watch":
        return m.choose_site_watch_target(dust2, path_cache, agent, state, site, config)
    if aim_mode == "bomb":
        if agent.side == "CT" and not can_commit_defuse(
            "CT", agent, state, site, config
        ):
            return site.position
        return state.bomb.position or site.position
    target, _ = m.choose_aim_target(agent, enemy, site.position, state, dust2, config, "path")
    return target


def aim_context_for_mode(aim_mode: str) -> str:
    return {
        "visible_enemy": "enemy",
        "last_seen": "last_seen",
        "sound_region": "contact",
        "path_frontier": "path",
        "site_watch": "watch",
        "bomb": "bomb",
    }.get(aim_mode, "scan")


def selected_site_id(site_head: str, current_site_id: str) -> str:
    if site_head in {"A", "B"}:
        return site_head
    return current_site_id


def normalize_action(action: np.ndarray | list[int] | tuple[int, ...]) -> tuple[int, int, int, int]:
    arr = list(np.asarray(action, dtype=np.int64).reshape(-1))
    if len(arr) != 4:
        raise ValueError("Dust2 primitive action must have four discrete heads.")
    return (
        int(arr[0]) % len(PRIMITIVES),
        int(arr[1]) % len(AIM_MODES),
        int(arr[2]) % len(MOVE_MODES),
        int(arr[3]) % len(SITE_HEADS),
    )


def describe_action(action: tuple[int, int, int, int]) -> dict[str, str]:
    return {
        "primitive": PRIMITIVES[action[0]],
        "aimMode": AIM_MODES[action[1]],
        "moveMode": MOVE_MODES[action[2]],
        "siteHead": SITE_HEADS[action[3]],
    }


def zero_reward_parts() -> dict[str, float]:
    return {
        "terminal": 0.0,
        "objective": 0.0,
        "damage": 0.0,
        "damageTaken": 0.0,
        "kill": 0.0,
        "death": 0.0,
        "shotCost": 0.0,
        "emptyFire": 0.0,
        "lowProbabilityShot": 0.0,
        "invalidObjective": 0.0,
        "visibleNoResponse": 0.0,
        "idle": 0.0,
        "aimWall": 0.0,
        "potential": 0.0,
    }


def add_reward_parts(total: dict[str, float], parts: dict[str, float]) -> None:
    for key, value in parts.items():
        total[key] = total.get(key, 0.0) + value


def map_bounds(dust2: m.Dust2Map) -> dict[str, float]:
    positions = [area.centroid for area in dust2.areas.values()]
    return {
        "minX": min(position.x for position in positions),
        "maxX": max(position.x for position in positions),
        "minY": min(position.y for position in positions),
        "maxY": max(position.y for position in positions),
        "minZ": min(position.z for position in positions),
        "maxZ": max(position.z for position in positions),
    }


def normalized_position(position: m.Vec3, bounds: dict[str, float]) -> list[float]:
    return [
        normalize_range(position.x, bounds["minX"], bounds["maxX"]),
        normalize_range(position.y, bounds["minY"], bounds["maxY"]),
        normalize_range(position.z, bounds["minZ"], bounds["maxZ"]),
    ]


def normalized_velocity(velocity: m.Vec3, max_speed: float) -> float:
    return clamp_unit(m.vector_length(velocity) / max(max_speed, 1e-6) * 2.0 - 1.0)


def relative_observation(origin: m.Vec3, target: m.Vec3 | None, bounds: dict[str, float]) -> list[float]:
    if target is None:
        return [-1.0, 0.0, 0.0, 0.0]
    dx = (target.x - origin.x) / max(bounds["maxX"] - bounds["minX"], 1e-6)
    dy = (target.y - origin.y) / max(bounds["maxY"] - bounds["minY"], 1e-6)
    dz = (target.z - origin.z) / max(bounds["maxZ"] - bounds["minZ"], 1e-6)
    return [1.0, clamp_unit(dx * 2.0), clamp_unit(dy * 2.0), clamp_unit(dz * 2.0)]


def memory_position_observation(
    agent: m.AgentState,
    position: m.Vec3 | None,
    tick: int | None,
    current_tick: int,
    bounds: dict[str, float],
    max_age_seconds: float,
    config: m.Dust2Config,
) -> list[float]:
    if position is None or tick is None:
        return [-1.0, 0.0, 0.0, 0.0, -1.0]
    age_ticks = max(0, current_tick - tick)
    age_ratio = min(age_ticks / max(1, config.ticks_for_seconds(max_age_seconds)), 1.0)
    return [*relative_observation(agent.position, position, bounds), 1.0 - 2.0 * age_ratio]


def one_hot_index(values: tuple[str, ...], key: str, default: int = -1) -> list[float]:
    index = values.index(key) if key in values else default
    return [1.0 if i == index else -1.0 for i in range(min(len(values), 8))]


def scale01(value: float, maximum: float) -> float:
    return clamp_unit((float(value) / max(float(maximum), 1e-6)) * 2.0 - 1.0)


def normalize_range(value: float, low: float, high: float) -> float:
    return clamp_unit(((value - low) / max(high - low, 1e-6)) * 2.0 - 1.0)


def distance_feature(distance: float) -> float:
    return clamp_unit(1.0 - min(distance / 2400.0, 2.0))


def action_label_feature(label: str, expected: str) -> float:
    return 1.0 if label == expected or label == f"rl-{expected}" else -1.0


def can_commit_plant(side: Side, agent: m.AgentState, site: m.BombSite, state: m.RoundState, dust2: m.Dust2Map, config: m.Dust2Config) -> bool:
    return (
        side == "T"
        and not state.bomb.planted
        and agent.is_alive
        and m.is_on_bomb_site(dust2, site, agent)
        and m.vector_length(agent.velocity) <= config.stationary_commit_speed_per_tick
    )


def can_commit_defuse(side: Side, agent: m.AgentState, state: m.RoundState, site: m.BombSite, config: m.Dust2Config) -> bool:
    bomb_position = state.bomb.position or site.position
    return (
        side == "CT"
        and state.bomb.planted
        and agent.is_alive
        and m.distance2(agent.position, bomb_position) <= site.radius * 0.55
        and m.vector_length(agent.velocity) <= config.stationary_commit_speed_per_tick
    )


def distance_or_current(agent: m.AgentState, position: m.Vec3) -> float:
    return m.distance2(agent.position, position)


def clamp_unit(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


def run_check_env(args: argparse.Namespace) -> None:
    from stable_baselines3.common.env_checker import check_env
    from sb3_contrib import RecurrentPPO

    env = Dust2PrimitiveEnv(scenario=Dust2Scenario(seed=args.seed, learner_side=args.learner_side))
    check_env(env, warn=True, skip_render_check=True)
    obs, info = env.reset(seed=args.seed)
    model = RecurrentPPO("MlpLstmPolicy", env, n_steps=32, batch_size=32, verbose=0, seed=args.seed)
    action, lstm_state = model.predict(obs, deterministic=False)
    next_obs, reward, terminated, truncated, step_info = env.step(action)
    print(json.dumps({
        "status": "ok",
        "formalTrainingStarted": False,
        "observationSize": int(next_obs.shape[0]),
        "sampleAction": step_info["action"],
        "sampleReward": reward,
        "terminated": terminated,
        "truncated": truncated,
        "resetInfo": info,
        "lstmStateReady": lstm_state is not None,
    }, indent=2, sort_keys=True))


def run_init_model(args: argparse.Namespace) -> None:
    from sb3_contrib import RecurrentPPO

    env = Dust2PrimitiveEnv(scenario=Dust2Scenario(seed=args.seed, learner_side=args.learner_side))
    model = RecurrentPPO("MlpLstmPolicy", env, n_steps=32, batch_size=32, verbose=0, seed=args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    model.save(out)
    print(json.dumps({
        "status": "saved-untrained-lstm-policy",
        "formalTrainingStarted": False,
        "checkpoint": str(out),
        "checkpointBytes": out.with_suffix(".zip").stat().st_size if out.with_suffix(".zip").exists() else out.stat().st_size,
    }, indent=2, sort_keys=True))


def run_rollout(args: argparse.Namespace) -> None:
    env = Dust2PrimitiveEnv(scenario=Dust2Scenario(seed=args.seed, learner_side=args.learner_side))
    obs, _ = env.reset(seed=args.seed)
    reward_total = 0.0
    for _ in range(args.steps):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, _ = env.step(action)
        reward_total += reward
        if terminated or truncated:
            break
    payload = env.trace_payload()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "status": "wrote-random-primitive-rollout",
        "formalTrainingStarted": False,
        "out": str(out),
        "frames": len(payload["frames"]),
        "events": len(payload["events"]),
        "rewardTotal": round(reward_total, 4),
        "lastObservationMean": round(float(np.mean(obs)), 4),
        "summary": payload["summary"],
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Dust2 RL primitive scaffold; does not start formal training.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check-env", help="Validate Gym env and instantiate an untrained LSTM policy.")
    check_parser.add_argument("--seed", type=int, default=2607)
    check_parser.add_argument("--learner-side", choices=["T", "CT"], default="T")
    check_parser.set_defaults(func=run_check_env)

    init_parser = subparsers.add_parser("init-model", help="Save an untrained RecurrentPPO LSTM policy checkpoint.")
    init_parser.add_argument("--seed", type=int, default=2607)
    init_parser.add_argument("--learner-side", choices=["T", "CT"], default="T")
    init_parser.add_argument("--out", default=".solo-clutch-runs/dust2-rl/init_lstm_policy")
    init_parser.set_defaults(func=run_init_model)

    rollout_parser = subparsers.add_parser("rollout", help="Export a random primitive rollout trace for viewer smoke testing.")
    rollout_parser.add_argument("--seed", type=int, default=2607)
    rollout_parser.add_argument("--learner-side", choices=["T", "CT"], default="T")
    rollout_parser.add_argument("--steps", type=int, default=200)
    rollout_parser.add_argument("--out", default=".solo-clutch-runs/dust2-rl-smoke/random_trace.json")
    rollout_parser.set_defaults(func=run_rollout)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
