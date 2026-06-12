from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import math
import random
from typing import Any

from gymnasium import spaces
import numpy as np

from . import dust2_mvp as m
from .dust2_rl import (
    Dust2PrimitiveEnv,
    Dust2RewardConfig,
    Dust2Scenario,
    MOVE_MODES,
    Side,
    add_reward_parts,
    aim_context_for_mode,
    base_action,
    can_commit_defuse,
    can_commit_plant,
    compute_reward,
    literal_visible_combat_aim_point,
    literal_no_op,
    zero_reward_parts,
)


PHASE_C_HELD_OUT_SEEDS = (12_607, 22_607, 32_607, 42_607, 52_607)
PHASE_C_ENV_REVISION = "phase-c9-objective-curriculum-20260612"
PHASE_C_PRIMITIVES: tuple[str, ...] = (
    "hold_angle",
    "advance_local",
    "branch_left",
    "branch_right",
    "explore_local",
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
PHASE_C_AIM_MODES: tuple[str, ...] = (
    "visible_enemy",
    "last_seen",
    "sound_region",
    "path_frontier",
    "local_scan",
    "bomb",
)
PHASE_C_MOVE_MODES = MOVE_MODES
PHASE_C_ACTION_SIZE = 3
PHASE_C_PREPLANT_SITE_FEATURES = (7, 36, 37)
PHASE_C_ON_SITE_FEATURE = 38
PHASE_C_CAN_PLANT_FEATURE = 39
PHASE_C_PRIMITIVE_ONE_HOT = slice(48, 72)
OBJECTIVE_AREA_DISTANCE_CACHE: dict[tuple[Any, ...], list[tuple[m.NavArea, float]]] = {}


@dataclass(frozen=True)
class PhaseCObjectiveCurriculumConfig:
    stage: str = "C2"
    objective_shaping_coef: float = 0.0
    site_entry_reward: float = 0.0
    valid_plant_start_reward: float = 0.0
    plant_reward: float = 0.1
    objective_near_probability: float = 0.0
    objective_mid_probability: float = 0.0
    objective_uniform_probability: float = 1.0
    potential_scale_units: float = 2000.0
    max_potential_reward_per_tick: float = 0.02

    def active(self) -> bool:
        return (
            self.objective_shaping_coef > 0.0
            or self.site_entry_reward > 0.0
            or self.valid_plant_start_reward > 0.0
            or self.objective_near_probability > 0.0
            or self.objective_mid_probability > 0.0
        )


def phase_c_reward_config(*, plant_reward: float = 0.1) -> Dust2RewardConfig:
    return Dust2RewardConfig(
        phase="C",
        terminal_win_reward=1.0,
        terminal_loss_reward=-1.0,
        plant_reward=plant_reward,
        enemy_plant_cost=0.0,
        defuse_reward=0.0,
        plant_progress_reward=0.0,
        defuse_progress_reward=0.0,
        enemy_defuse_progress_cost=0.0,
        plant_interrupt_cost=0.0,
        defuse_interrupt_cost=0.0,
        defuse_interrupt_reward=0.0,
        postplant_alive_reward=0.0,
        damage_reward_coef=0.0,
        damage_taken_coef=0.0,
        kill_bonus=0.05,
        death_penalty=0.0,
        preplant_death_extra_penalty=0.0,
        preplant_ct_kill_bonus=0.1,
        shot_cost=0.0,
        empty_fire_cost=0.0,
        low_probability_shot_cost=0.0,
        invalid_objective_cost=0.0,
        visible_no_response_cost=0.0,
        idle_degenerate_cost=0.0,
        aim_wall_cost=0.0,
        phase_a_potential_coef=0.0,
        phase_b_potential_coef=0.0,
    )


def opponent_side(side: Side) -> Side:
    return "CT" if side == "T" else "T"


def sample_phase_c_bomb_state(rng: random.Random) -> m.BombStateInput:
    roll = rng.random()
    if roll < 0.80:
        return "unplanted"
    return "planted_a" if roll < 0.90 else "planted_b"


def is_on_any_fixed_bombsite(dust2: m.Dust2Map, agent: m.AgentState) -> bool:
    return any(
        m.is_on_bomb_site(dust2, site, agent)
        for site in dust2.bomb_sites.values()
    )


def path_distance_to_fixed_bombsite(
    dust2: m.Dust2Map,
    path_cache: m.PathCache,
    area_id: str,
    site: m.BombSite,
) -> float:
    site_area = m.site_representative_area_id(dust2, site)
    route = path_cache.path(area_id, site_area)
    if route:
        return m.path_distance(dust2, route)
    return m.distance3(dust2.areas[area_id].centroid, site.position)


def nearest_fixed_bombsite_path_distance(
    dust2: m.Dust2Map,
    path_cache: m.PathCache,
    agent: m.AgentState,
) -> float:
    if is_on_any_fixed_bombsite(dust2, agent):
        return 0.0
    distances = [
        path_distance_to_fixed_bombsite(dust2, path_cache, agent.area_id, site)
        for site in dust2.bomb_sites.values()
    ]
    finite = [distance for distance in distances if math.isfinite(distance)]
    return min(finite) if finite else 0.0


def objective_potential(
    dust2: m.Dust2Map,
    path_cache: m.PathCache,
    agent: m.AgentState,
    curriculum: PhaseCObjectiveCurriculumConfig,
) -> float:
    scale = max(1.0, curriculum.potential_scale_units)
    return -nearest_fixed_bombsite_path_distance(dust2, path_cache, agent) / scale


def objective_curriculum_reward(
    *,
    learner: Side,
    previous: m.RoundState,
    next_state: m.RoundState,
    learner_action: dict[str, Any],
    dust2: m.Dust2Map,
    config: m.Dust2Config,
    path_cache: m.PathCache,
    curriculum: PhaseCObjectiveCurriculumConfig,
    site_entry_already_awarded: bool,
    valid_plant_start_already_awarded: bool,
) -> tuple[float, dict[str, float], bool, bool]:
    parts = {
        "objectivePotential": 0.0,
        "siteEntry": 0.0,
        "validPlantStart": 0.0,
    }
    if learner != "T" or previous.bomb.planted or not previous.agents["T"].is_alive:
        return 0.0, parts, site_entry_already_awarded, valid_plant_start_already_awarded
    previous_t = previous.agents["T"]
    next_t = next_state.agents["T"]
    if curriculum.objective_shaping_coef > 0.0 and next_t.is_alive:
        delta = objective_potential(dust2, path_cache, next_t, curriculum) - objective_potential(
            dust2,
            path_cache,
            previous_t,
            curriculum,
        )
        shaped = curriculum.objective_shaping_coef * max(0.0, delta)
        shaped = min(curriculum.max_potential_reward_per_tick, shaped)
        parts["objectivePotential"] = shaped
    if (
        curriculum.site_entry_reward > 0.0
        and not site_entry_already_awarded
        and not is_on_any_fixed_bombsite(dust2, previous_t)
        and is_on_any_fixed_bombsite(dust2, next_t)
    ):
        parts["siteEntry"] = curriculum.site_entry_reward
        site_entry_already_awarded = True
    if (
        curriculum.valid_plant_start_reward > 0.0
        and not valid_plant_start_already_awarded
        and bool(learner_action.get("plant"))
        and not previous.bomb.planted
    ):
        physical_site = next(
            (
                site
                for site in dust2.bomb_sites.values()
                if m.is_on_bomb_site(dust2, site, previous_t)
            ),
            None,
        )
        if physical_site is not None and can_commit_plant(
            "T",
            previous_t,
            physical_site,
            previous,
            dust2,
            config,
        ):
            parts["validPlantStart"] = curriculum.valid_plant_start_reward
            valid_plant_start_already_awarded = True
    total = sum(parts.values())
    return total, parts, site_entry_already_awarded, valid_plant_start_already_awarded


def sample_objective_curriculum_areas(
    dust2: m.Dust2Map,
    config: m.Dust2Config,
    rng: random.Random,
    path_cache: m.PathCache,
    curriculum: PhaseCObjectiveCurriculumConfig,
    area_objective_distances: list[tuple[m.NavArea, float]] | None = None,
) -> tuple[str | None, str | None]:
    roll = rng.random()
    near_p = max(0.0, curriculum.objective_near_probability)
    mid_p = max(0.0, curriculum.objective_mid_probability)
    if roll >= near_p + mid_p:
        return None, None
    scored = area_objective_distances or objective_area_distance_scores(dust2, path_cache)
    candidates = [area for area, _ in scored]
    if roll < near_p:
        t_pool = [area for area, distance in scored if distance <= 1200.0]
    else:
        t_pool = [area for area, distance in scored if 1200.0 < distance <= 2400.0]
    for _ in range(800):
        t_area = m.weighted_area_choice(t_pool or candidates, rng).area_id
        ct_area = m.weighted_area_choice(candidates, rng).area_id
        if t_area == ct_area:
            continue
        if (
            m.distance3(dust2.areas[t_area].centroid, dust2.areas[ct_area].centroid)
            < config.collision_radius * 2.0
        ):
            continue
        if all(
            path_cache.path(t_area, m.site_representative_area_id(dust2, site))
            for site in dust2.bomb_sites.values()
        ):
            return t_area, ct_area
    return None, None


def objective_area_distance_scores(
    dust2: m.Dust2Map,
    path_cache: m.PathCache,
) -> list[tuple[m.NavArea, float]]:
    config = path_cache.config
    cache_key = (
        dust2.map_name,
        config.max_jump_up,
        config.max_drop,
        config.max_step_up,
        config.max_jump_gap,
    )
    cached = OBJECTIVE_AREA_DISTANCE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    scored: list[tuple[m.NavArea, float]] = []
    for area in dust2.areas.values():
        if area.size < 80.0:
            continue
        distance = min(
            path_distance_to_fixed_bombsite(dust2, path_cache, area.area_id, site)
            for site in dust2.bomb_sites.values()
        )
        scored.append((area, distance))
    OBJECTIVE_AREA_DISTANCE_CACHE[cache_key] = scored
    return scored


def normalize_phase_c_action(
    action: np.ndarray | list[int] | tuple[int, ...],
) -> tuple[int, int, int]:
    arr = list(np.asarray(action, dtype=np.int64).reshape(-1))
    if len(arr) != PHASE_C_ACTION_SIZE:
        raise ValueError("Phase C action must have three discrete heads.")
    return (
        int(arr[0]) % len(PHASE_C_PRIMITIVES),
        int(arr[1]) % len(PHASE_C_AIM_MODES),
        int(arr[2]) % len(PHASE_C_MOVE_MODES),
    )


def describe_phase_c_action(action: tuple[int, int, int]) -> dict[str, str]:
    return {
        "primitive": PHASE_C_PRIMITIVES[action[0]],
        "aimMode": PHASE_C_AIM_MODES[action[1]],
        "moveMode": PHASE_C_MOVE_MODES[action[2]],
    }


def choose_local_navigation_area(
    dust2: m.Dust2Map,
    config: m.Dust2Config,
    state: m.RoundState,
    side: Side,
    primitive: str,
    visit_counts: dict[str, int],
) -> str:
    agent = state.agents[side]
    if (
        primitive == "postplant_reposition"
        and side == "CT"
        and state.bomb.planted
        and state.bomb.position is not None
    ):
        return m.nearest_area_id(dust2, state.bomb.position)
    contact = m.recent_contact_position(agent, state, config)
    if primitive in {"push_contact", "contact_clear"} and contact is not None:
        return m.nearest_area_id(dust2, contact)
    if (
        primitive == "advance_local"
        and agent.target_area_id is not None
        and agent.target_area_id != agent.area_id
        and agent.target_area_id in dust2.areas
    ):
        return agent.target_area_id
    neighbors = [
        area_id
        for area_id in dust2.graph.get(agent.area_id, ())
        if area_id in dust2.areas
    ]
    if not neighbors:
        return agent.area_id
    facing = agent.aim_deg
    scored = [
        (
            m.shortest_angle_delta(
                facing,
                m.angle_to(agent.position, dust2.areas[area_id].centroid),
            ),
            area_id,
        )
        for area_id in neighbors
    ]
    if primitive == "branch_left":
        left = [(delta, area_id) for delta, area_id in scored if delta < -8.0]
        return min(left or scored, key=lambda item: (abs(item[0]), item[1]))[1]
    if primitive == "branch_right":
        right = [(delta, area_id) for delta, area_id in scored if delta > 8.0]
        return min(right or scored, key=lambda item: (abs(item[0]), item[1]))[1]
    if primitive in {"explore_local", "search_point", "postplant_reposition"}:
        return min(
            neighbors,
            key=lambda area_id: (
                visit_counts.get(area_id, 0),
                abs(
                    m.shortest_angle_delta(
                        facing,
                        m.angle_to(agent.position, dust2.areas[area_id].centroid),
                    )
                ),
                area_id,
            ),
        )
    return min(scored, key=lambda item: (abs(item[0]), item[1]))[1]


def phase_c_aim_target(
    aim_mode: str,
    agent: m.AgentState,
    enemy: m.AgentState,
    state: m.RoundState,
    dust2: m.Dust2Map,
    config: m.Dust2Config,
    visibility: m.Visibility,
    path_cache: m.PathCache,
    target_area: str,
) -> tuple[m.Vec3, str]:
    fallback = dust2.areas[target_area].centroid
    if (
        aim_mode == "visible_enemy"
        and m.can_see(agent, enemy, dust2, config, visibility, state.utilities)
    ):
        return (
            literal_visible_combat_aim_point(
                agent,
                enemy,
                config,
                visibility,
                state.utilities,
            ),
            "enemy",
        )
    if aim_mode == "last_seen" and agent.last_seen_position is not None:
        return m.default_aim_point(agent.last_seen_position, config), "last_seen"
    if aim_mode == "sound_region" and agent.last_sound_position is not None:
        return m.default_aim_point(agent.last_sound_position, config), "contact"
    if aim_mode == "bomb" and state.bomb.planted and state.bomb.position is not None:
        return m.default_aim_point(state.bomb.position, config), "bomb"
    if aim_mode == "path_frontier":
        return (
            m.choose_path_search_target(
                dust2,
                path_cache,
                agent,
                state,
                target_area,
                fallback,
                config,
            ),
            "path",
        )
    return (
        m.choose_scan_target(agent, state, dust2, fallback, config),
        "scan",
    )


def phase_c_action_to_literal(
    action_tuple: tuple[int, int, int],
    side: Side,
    dust2: m.Dust2Map,
    config: m.Dust2Config,
    visibility: m.Visibility,
    path_cache: m.PathCache,
    state: m.RoundState,
    *,
    local_target_area: str | None,
) -> dict[str, Any]:
    primitive = PHASE_C_PRIMITIVES[action_tuple[0]]
    aim_mode = PHASE_C_AIM_MODES[action_tuple[1]]
    move_mode = PHASE_C_MOVE_MODES[action_tuple[2]]
    agent = state.agents[side]
    enemy = state.agents[opponent_side(side)]
    target_area = (
        local_target_area
        if local_target_area in dust2.areas
        else agent.area_id
    )
    aim_target, aim_context = phase_c_aim_target(
        aim_mode,
        agent,
        enemy,
        state,
        dust2,
        config,
        visibility,
        path_cache,
        target_area,
    )
    label = f"rl-{primitive}"
    if not agent.is_alive:
        return literal_no_op(agent, config, visibility, state, "dead")
    if primitive == "reload":
        if agent.ammo >= config.max_ammo or agent.reload_cooldown_ticks > 0:
            return literal_no_op(agent, config, visibility, state, label)
        return {
            **base_action(
                agent,
                aim_target,
                aim_context,
                "hold",
                "walk",
                label=label,
            ),
            "reload": True,
        }
    if primitive == "engage_visible":
        visible = m.can_see(
            agent,
            enemy,
            dust2,
            config,
            visibility,
            state.utilities,
        )
        if (
            not visible
            or agent.ammo <= 0
            or agent.reload_cooldown_ticks > 0
        ):
            return literal_no_op(agent, config, visibility, state, label)
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
                fire=agent.fire_cooldown_ticks == 0,
                label=label,
            ),
            "force_fire": True,
        }
    if primitive == "plant":
        physical_site = next(
            (
                site
                for site in dust2.bomb_sites.values()
                if m.is_on_bomb_site(dust2, site, agent)
            ),
            None,
        )
        if (
            physical_site is None
            or not can_commit_plant(
                side,
                agent,
                physical_site,
                state,
                dust2,
                config,
            )
        ):
            return literal_no_op(agent, config, visibility, state, label)
        return base_action(
            agent,
            physical_site.position,
            "bomb",
            "hold",
            "walk",
            plant=True,
            label=label,
        )
    if primitive == "defuse":
        site = dust2.bomb_sites[state.bomb.site_id]
        if not can_commit_defuse(side, agent, state, site, config):
            return literal_no_op(agent, config, visibility, state, label)
        return base_action(
            agent,
            state.bomb.position or site.position,
            "bomb",
            "hold",
            "walk",
            defuse=True,
            label=label,
        )
    if primitive == "take_cover":
        target_area = local_target_area or agent.area_id
    if primitive in {
        "advance_local",
        "branch_left",
        "branch_right",
        "explore_local",
        "search_point",
        "contact_clear",
        "push_contact",
        "take_cover",
        "postplant_reposition",
    }:
        if primitive in {"search_point", "contact_clear"}:
            aim_target = m.choose_clear_angle_target(
                dust2,
                path_cache,
                agent,
                state,
                target_area,
                dust2.areas[target_area].centroid,
                config,
            )
            aim_context = "clear"
        return base_action(
            agent,
            aim_target,
            aim_context,
            "hold" if move_mode == "hold" else "route",
            "run" if move_mode == "run" else "walk",
            target_area=target_area,
            label=label,
        )
    return base_action(
        agent,
        aim_target,
        aim_context_for_mode(aim_mode),
        "hold",
        "walk",
        label=label,
    )


class PhaseCSelfPlayEnv(Dust2PrimitiveEnv):
    """Single-learner Gym facade over a simultaneous two-policy Dust2 episode."""

    def __init__(
        self,
        *,
        learner_side: Side,
        seed: int = 2607,
        opponent_checkpoint: str | Path | None = None,
        opponent_model: Any | None = None,
        config: m.Dust2Config | None = None,
        frame_stride: int = 20,
        randomize_scenario: bool = True,
        site_choice: str = "auto",
        bomb_state: m.BombStateInput = "unplanted",
        t_area_id: str | None = None,
        ct_area_id: str | None = None,
        static_los: bool = True,
        learner_literal_actions: bool = True,
        objective_curriculum: PhaseCObjectiveCurriculumConfig | None = None,
    ):
        self.objective_curriculum = objective_curriculum or PhaseCObjectiveCurriculumConfig()
        scenario = Dust2Scenario(
            seed=seed,
            spawn_mode="uniform_walkable",
            site_choice=site_choice,
            bomb_state=bomb_state,
            t_area_id=t_area_id,
            ct_area_id=ct_area_id,
            learner_side=learner_side,
            opponent_side=opponent_side(learner_side),
            static_los=static_los,
            frame_stride=frame_stride,
        )
        super().__init__(
            scenario=scenario,
            reward_config=phase_c_reward_config(
                plant_reward=self.objective_curriculum.plant_reward,
            ),
            config=config,
        )
        self.action_space = spaces.MultiDiscrete(
            [
                len(PHASE_C_PRIMITIVES),
                len(PHASE_C_AIM_MODES),
                len(PHASE_C_MOVE_MODES),
            ]
        )
        self.randomize_scenario = randomize_scenario
        self.learner_literal_actions = learner_literal_actions
        self._phase_c_base_seed = seed
        self._phase_c_episode_index = 0
        self.opponent_checkpoint = Path(opponent_checkpoint) if opponent_checkpoint else None
        self.opponent_model = opponent_model
        self.opponent_lstm_state: Any | None = None
        self.opponent_episode_start = True
        self.last_actions: dict[Side, tuple[int, int, int] | None] = {"T": None, "CT": None}
        self.decision_actions: list[dict[str, Any]] = []
        self.area_visit_counts: dict[Side, dict[str, int]] = {"T": {}, "CT": {}}
        self._objective_area_distances: list[tuple[m.NavArea, float]] | None = None
        self.site_entry_awarded = False
        self.valid_plant_start_awarded = False
        self.objective_reward_totals = {
            "objectivePotential": 0.0,
            "siteEntry": 0.0,
            "validPlantStart": 0.0,
        }

    def build_observation_for_side(
        self,
        state: m.RoundState,
        side: Side,
    ) -> np.ndarray:
        observation = super().build_observation_for_side(state, side)
        observation = observation.copy()
        if not state.bomb.planted:
            for index in PHASE_C_PREPLANT_SITE_FEATURES:
                observation[index] = 0.0
            agent = state.agents[side]
            on_any_site = any(
                m.is_on_bomb_site(self.dust2, site, agent)
                for site in self.dust2.bomb_sites.values()
            )
            observation[PHASE_C_ON_SITE_FEATURE] = 1.0 if on_any_site else -1.0
            observation[PHASE_C_CAN_PLANT_FEATURE] = (
                1.0
                if (
                    side == "T"
                    and agent.is_alive
                    and on_any_site
                    and m.vector_length(agent.velocity)
                    <= self.config.stationary_commit_speed_per_tick
                )
                else -1.0
            )
        observation[PHASE_C_PRIMITIVE_ONE_HOT] = 0.0
        primitive = state.agents[side].action_label.removeprefix("rl-")
        if primitive in PHASE_C_PRIMITIVES:
            primitive_index = PHASE_C_PRIMITIVES.index(primitive)
            if primitive_index < PHASE_C_PRIMITIVE_ONE_HOT.stop - PHASE_C_PRIMITIVE_ONE_HOT.start:
                observation[PHASE_C_PRIMITIVE_ONE_HOT.start + primitive_index] = 1.0
        return observation

    def _load_opponent(self) -> Any | None:
        if self.opponent_model is not None:
            return self.opponent_model
        if self.opponent_checkpoint is None:
            return None
        from sb3_contrib import RecurrentPPO

        self.opponent_model = RecurrentPPO.load(str(self.opponent_checkpoint), device="auto")
        return self.opponent_model

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        if seed is not None:
            self._phase_c_base_seed = int(seed)
            self._phase_c_episode_index = 0
            reset_seed = int(seed)
        else:
            self._phase_c_episode_index += 1
            reset_seed = self._phase_c_base_seed + self._phase_c_episode_index
        explicit_options = options or {}
        if self.randomize_scenario and not explicit_options:
            scenario_rng = random.Random(reset_seed)
            bomb_state = sample_phase_c_bomb_state(scenario_rng)
            site_choice = (
                "auto"
                if bomb_state == "unplanted"
                else ("A" if bomb_state == "planted_a" else "B")
            )
            t_area_id = None
            ct_area_id = None
            if bomb_state == "unplanted" and self.objective_curriculum.active():
                if self._objective_area_distances is None:
                    self._objective_area_distances = objective_area_distance_scores(
                        self.dust2,
                        self.path_cache,
                    )
                t_area_id, ct_area_id = sample_objective_curriculum_areas(
                    self.dust2,
                    self.config,
                    scenario_rng,
                    self.path_cache,
                    self.objective_curriculum,
                    self._objective_area_distances,
                )
            self.scenario = replace(
                self.scenario,
                seed=reset_seed,
                spawn_mode="uniform_walkable",
                site_choice=site_choice,
                bomb_state=bomb_state,
                t_area_id=t_area_id,
                ct_area_id=ct_area_id,
            )
        _, info = super().reset(seed=reset_seed, options=explicit_options)
        assert self.state is not None
        orientation_rng = random.Random(reset_seed ^ 0xC5_2D_20_26)
        phase_c_agents = {
            side: replace(
                agent,
                aim_deg=orientation_rng.uniform(0.0, 360.0),
                aim_pitch_deg=orientation_rng.uniform(-15.0, 15.0),
                aim_turn_delta_deg=0.0,
                aim_pitch_turn_delta_deg=0.0,
                aim_context="free",
                macro_intent="phase-c-policy",
            )
            for side, agent in self.state.agents.items()
        }
        self.state = replace(self.state, agents=phase_c_agents)
        self.events = [
            event
            for event in self.events
            if event.get("type") not in {"macro-intent", "site-choice"}
        ]
        self.frames = [
            m.frame_payload(
                self.state,
                self.events,
                {},
                self.config,
                self.visibility,
            )
        ]
        self._last_observation = self.build_observation_for_side(
            self.state,
            self.scenario.learner_side,
        )
        self.opponent_lstm_state = None
        self.opponent_episode_start = True
        self.last_actions = {"T": None, "CT": None}
        self.decision_actions = []
        self.area_visit_counts = {
            side: {agent.area_id: 1}
            for side, agent in self.state.agents.items()
        }
        self.site_entry_awarded = is_on_any_fixed_bombsite(
            self.dust2,
            self.state.agents["T"],
        )
        self.valid_plant_start_awarded = False
        self.objective_reward_totals = {
            "objectivePotential": 0.0,
            "siteEntry": 0.0,
            "validPlantStart": 0.0,
        }
        info["phase"] = "C"
        info["opponent"] = str(self.opponent_checkpoint) if self.opponent_checkpoint else "rules"
        info["objectiveCurriculum"] = asdict(self.objective_curriculum)
        return self._last_observation.copy(), info

    def step(
        self,
        action: np.ndarray | list[int] | tuple[int, ...],
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self.state is None:
            raise RuntimeError("reset() must be called before step().")
        if self.state.terminal is not None:
            return self._last_observation.copy(), 0.0, True, False, {
                "terminal": asdict(self.state.terminal)
            }

        learner = self.scenario.learner_side
        opponent = opponent_side(learner)
        learner_is_alive = self.state.agents[learner].is_alive
        learner_tuple = normalize_phase_c_action(action)
        opponent_tuple: tuple[int, int, int] | None = None
        opponent_model = self._load_opponent()
        opponent_is_policy = opponent_model is not None
        if opponent_is_policy and self.state.agents[opponent].is_alive:
            opponent_obs = self.build_observation_for_side(self.state, opponent)
            predicted, self.opponent_lstm_state = opponent_model.predict(
                opponent_obs,
                state=self.opponent_lstm_state,
                episode_start=np.asarray([self.opponent_episode_start], dtype=bool),
                deterministic=False,
            )
            opponent_tuple = normalize_phase_c_action(predicted)
            self.opponent_episode_start = False

        self.last_actions[learner] = learner_tuple
        self.last_actions[opponent] = opponent_tuple
        described_actions = {
            learner: describe_phase_c_action(learner_tuple) if learner_is_alive else "dead",
            opponent: describe_phase_c_action(opponent_tuple) if opponent_tuple is not None else "rules",
        }
        local_targets = {
            learner: self._local_target_for_action(learner, learner_tuple),
            opponent: self._local_target_for_action(opponent, opponent_tuple),
        }
        self.decision_actions.append(
            {
                "tick": self.state.tick,
                "actions": described_actions,
                "localTargets": local_targets,
            }
        )
        total_reward = 0.0
        reward_parts = zero_reward_parts()
        step_events: list[dict[str, Any]] = []

        for _ in range(max(1, self.config.decision_interval_ticks)):
            if self.state is None or self.state.terminal is not None:
                break
            previous = self.state
            overrides = {
                learner: (
                    phase_c_action_to_literal(
                        learner_tuple,
                        learner,
                        self.dust2,
                        self.config,
                        self.visibility,
                        self.path_cache,
                        previous,
                        local_target_area=local_targets[learner],
                    )
                    if previous.agents[learner].is_alive
                    else literal_no_op(
                        previous.agents[learner],
                        self.config,
                        self.visibility,
                        previous,
                        "dead",
                    )
                )
            }
            if opponent_is_policy:
                overrides[opponent] = (
                    phase_c_action_to_literal(
                        opponent_tuple,
                        opponent,
                        self.dust2,
                        self.config,
                        self.visibility,
                        self.path_cache,
                        previous,
                        local_target_area=local_targets[opponent],
                    )
                    if opponent_tuple is not None
                    else literal_no_op(
                        previous.agents[opponent],
                        self.config,
                        self.visibility,
                        previous,
                        "dead",
                    )
                )
            next_state, events, tick_metric = m.step_dust2_round(
                self.dust2,
                self.config,
                self.visibility,
                self.path_cache,
                previous,
                self.rng,
                action_overrides=overrides,
            )
            tick_reward, tick_parts = compute_reward(
                learner,
                previous,
                next_state,
                overrides[learner],
                events,
                tick_metric,
                self.dust2,
                self.config,
                self.visibility,
                self.reward_config,
            )
            objective_reward, objective_parts, self.site_entry_awarded, self.valid_plant_start_awarded = objective_curriculum_reward(
                learner=learner,
                previous=previous,
                next_state=next_state,
                learner_action=overrides[learner],
                dust2=self.dust2,
                config=self.config,
                path_cache=self.path_cache,
                curriculum=self.objective_curriculum,
                site_entry_already_awarded=self.site_entry_awarded,
                valid_plant_start_already_awarded=self.valid_plant_start_awarded,
            )
            tick_reward += objective_reward
            for key, value in objective_parts.items():
                if value:
                    self.objective_reward_totals[key] = self.objective_reward_totals.get(key, 0.0) + value
                    tick_parts[key] = tick_parts.get(key, 0.0) + value
            total_reward += tick_reward
            add_reward_parts(reward_parts, tick_parts)
            self.state = next_state
            self._record_area_visits(next_state)
            self.events.extend(events)
            self.metrics.append(tick_metric)
            step_events.extend(events)
            if (
                next_state.tick % max(1, self.scenario.frame_stride) == 0
                or next_state.terminal is not None
                or m.has_key_events(events)
            ):
                self.frames.append(
                    m.frame_payload(next_state, events, tick_metric, self.config, self.visibility)
                )

        if (
            self.state is not None
            and should_auto_resolve_terminal_grace(self.state, learner)
            and self.state.terminal is None
        ):
            for _ in range(900):
                if self.state.terminal is not None:
                    break
                opponent_tuple = (
                    self._predict_opponent_action(opponent)
                    if self.state.agents[opponent].is_alive
                    else None
                )
                local_target = self._local_target_for_action(opponent, opponent_tuple)
                self.decision_actions.append(
                    {
                        "tick": self.state.tick,
                        "actions": {
                            learner: (
                                "terminal-grace-hold"
                                if self.state.agents[learner].is_alive
                                else "dead"
                            ),
                            opponent: describe_phase_c_action(opponent_tuple)
                            if opponent_tuple is not None
                            else (
                                "rules"
                                if self.state.agents[opponent].is_alive
                                else "dead"
                            ),
                        },
                        "localTargets": {opponent: local_target},
                    }
                )
                for _ in range(max(1, self.config.decision_interval_ticks)):
                    if self.state.terminal is not None:
                        break
                    previous = self.state
                    overrides = {
                        learner: literal_no_op(
                            previous.agents[learner],
                            self.config,
                            self.visibility,
                            previous,
                            (
                                "terminal-grace-hold"
                                if previous.agents[learner].is_alive
                                else "dead"
                            ),
                        )
                    }
                    if opponent_model is not None:
                        overrides[opponent] = (
                            phase_c_action_to_literal(
                                opponent_tuple,
                                opponent,
                                self.dust2,
                                self.config,
                                self.visibility,
                                self.path_cache,
                                previous,
                                local_target_area=local_target,
                            )
                            if opponent_tuple is not None
                            else literal_no_op(
                                previous.agents[opponent],
                                self.config,
                                self.visibility,
                                previous,
                                "dead",
                            )
                        )
                    next_state, events, tick_metric = m.step_dust2_round(
                        self.dust2,
                        self.config,
                        self.visibility,
                        self.path_cache,
                        previous,
                        self.rng,
                        action_overrides=overrides,
                    )
                    tick_reward, tick_parts = compute_reward(
                        learner,
                        previous,
                        next_state,
                        overrides[learner],
                        events,
                        tick_metric,
                        self.dust2,
                        self.config,
                        self.visibility,
                        self.reward_config,
                    )
                    objective_reward, objective_parts, self.site_entry_awarded, self.valid_plant_start_awarded = objective_curriculum_reward(
                        learner=learner,
                        previous=previous,
                        next_state=next_state,
                        learner_action=overrides[learner],
                        dust2=self.dust2,
                        config=self.config,
                        path_cache=self.path_cache,
                        curriculum=self.objective_curriculum,
                        site_entry_already_awarded=self.site_entry_awarded,
                        valid_plant_start_already_awarded=self.valid_plant_start_awarded,
                    )
                    tick_reward += objective_reward
                    for key, value in objective_parts.items():
                        if value:
                            self.objective_reward_totals[key] = self.objective_reward_totals.get(key, 0.0) + value
                            tick_parts[key] = tick_parts.get(key, 0.0) + value
                    total_reward += tick_reward
                    add_reward_parts(reward_parts, tick_parts)
                    self.state = next_state
                    self._record_area_visits(next_state)
                    self.events.extend(events)
                    self.metrics.append(tick_metric)
                    step_events.extend(events)
                    if (
                        next_state.tick % max(1, self.scenario.frame_stride) == 0
                        or next_state.terminal is not None
                        or m.has_key_events(events)
                    ):
                        self.frames.append(
                            m.frame_payload(
                                next_state,
                                events,
                                tick_metric,
                                self.config,
                                self.visibility,
                            )
                        )

        self._last_observation = self.build_observation_for_side(self.state, learner)
        terminated = self.state.terminal is not None
        if terminated or not self.state.agents[opponent].is_alive:
            self.opponent_lstm_state = None
            self.opponent_episode_start = True
        return self._last_observation.copy(), float(total_reward), terminated, False, {
            "actions": described_actions,
            "events": step_events,
            "reward": reward_parts,
            "terminal": asdict(self.state.terminal) if self.state.terminal else None,
        }

    def _predict_opponent_action(
        self, side: Side
    ) -> tuple[int, int, int] | None:
        opponent_model = self._load_opponent()
        if opponent_model is None or self.state is None:
            return None
        observation = self.build_observation_for_side(self.state, side)
        predicted, self.opponent_lstm_state = opponent_model.predict(
            observation,
            state=self.opponent_lstm_state,
            episode_start=np.asarray([self.opponent_episode_start], dtype=bool),
            deterministic=False,
        )
        self.opponent_episode_start = False
        return normalize_phase_c_action(predicted)

    def _record_area_visits(self, state: m.RoundState) -> None:
        for side, agent in state.agents.items():
            counts = self.area_visit_counts[side]
            counts[agent.area_id] = counts.get(agent.area_id, 0) + 1

    def _local_target_for_action(
        self,
        side: Side,
        action: tuple[int, int, int] | None,
    ) -> str | None:
        if self.state is None or action is None:
            return None
        primitive = PHASE_C_PRIMITIVES[action[0]]
        if primitive not in {
            "advance_local",
            "branch_left",
            "branch_right",
            "explore_local",
            "push_contact",
            "contact_clear",
            "search_point",
            "take_cover",
            "postplant_reposition",
        }:
            return None
        return choose_local_navigation_area(
            self.dust2,
            self.config,
            self.state,
            side,
            primitive,
            self.area_visit_counts[side],
        )

    def trace_payload(self) -> dict[str, Any]:
        payload = super().trace_payload()
        payload["schemaVersion"] = "dust2-solo-clutch-phase-c-0.2"
        payload["summary"]["learner_side"] = self.scenario.learner_side
        payload["summary"]["site_selection"] = "none"
        payload["rl"].update(
            {
                "phase": "C",
                "literalActions": True,
                "opponentCheckpoint": str(self.opponent_checkpoint)
                if self.opponent_checkpoint
                else None,
                "decisionActions": self.decision_actions,
                "objectiveCurriculum": asdict(self.objective_curriculum),
                "objectiveRewardTotals": self.objective_reward_totals,
                "actionSpace": {
                    "primitive": list(PHASE_C_PRIMITIVES),
                    "aimMode": list(PHASE_C_AIM_MODES),
                    "moveMode": list(PHASE_C_MOVE_MODES),
                },
            }
        )
        return payload


def should_auto_resolve_terminal_grace(state: m.RoundState, learner: Side) -> bool:
    opponent = opponent_side(learner)
    if not state.agents[learner].is_alive:
        return True
    if state.agents[opponent].is_alive:
        return False
    return (
        learner == "CT" and not state.bomb.planted
    ) or (
        learner == "T" and state.bomb.planted
    )
