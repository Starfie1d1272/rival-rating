from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import dust2_mvp as m
from .dust2_phase_c import (
    PHASE_C_AIM_MODES,
    PHASE_C_MOVE_MODES,
    PHASE_C_PRIMITIVES,
    PhaseCObjectiveCurriculumConfig,
    PhaseCSelfPlayEnv,
    describe_phase_c_action,
    nearest_fixed_bombsite_path_distance,
    objective_curriculum_reward,
    path_distance_to_fixed_bombsite,
    phase_c_action_to_literal,
    phase_c_reward_config,
)
from .dust2_phase_c_train import (
    PhaseCConfig,
    choose_opponents,
    phase_c_promotion_eligible,
    phase_c_integrity_violations,
    reconcile_checkpoints_to_committed_generation,
)
from .dust2_rl import (
    AIM_MODES,
    MOVE_MODES,
    PRIMITIVES,
    SITE_HEADS,
    compute_reward,
    literal_visible_combat_aim_point,
    primitive_to_dust2_action,
)


def legacy_action_tuple(primitive: str) -> tuple[int, int, int, int]:
    return (
        PRIMITIVES.index(primitive),
        AIM_MODES.index("path_frontier"),
        MOVE_MODES.index("walk"),
        SITE_HEADS.index("current"),
    )


def action_tuple(primitive: str) -> tuple[int, int, int]:
    return (
        PHASE_C_PRIMITIVES.index(primitive),
        PHASE_C_AIM_MODES.index("path_frontier"),
        PHASE_C_MOVE_MODES.index("walk"),
    )


def phase_c_literal(
    env: PhaseCSelfPlayEnv,
    primitive: str,
    side: str,
    state: m.RoundState,
) -> dict:
    return phase_c_action_to_literal(
        action_tuple(primitive),
        side,
        env.dust2,
        env.config,
        env.visibility,
        env.path_cache,
        state,
        local_target_area=state.agents[side].area_id,
    )


class StubOpponent:
    def __init__(self, primitive: str):
        self.action = np.asarray(action_tuple(primitive), dtype=np.int64)
        self.predict_calls = 0

    def predict(self, observation, state=None, episode_start=None, deterministic=False):
        self.predict_calls += 1
        return self.action.copy(), ("opponent-hidden",)


class PhaseCTests(unittest.TestCase):
    def make_env(self, **kwargs) -> PhaseCSelfPlayEnv:
        env = PhaseCSelfPlayEnv(
            learner_side="T",
            seed=2607,
            randomize_scenario=False,
            site_choice="A",
            bomb_state="unplanted",
            **kwargs,
        )
        env.reset(seed=2607)
        return env

    def test_hidden_enemy_position_is_not_observed(self) -> None:
        env = self.make_env()
        assert env.state is not None
        first = env.state
        moved_enemy = replace(
            first.agents["CT"],
            position=m.Vec3(
                first.agents["CT"].position.x + 700.0,
                first.agents["CT"].position.y - 400.0,
                first.agents["CT"].position.z,
            ),
            velocity=m.Vec3(2.0, -1.0, 0.0),
            aim_deg=173.0,
            aim_pitch_deg=-27.0,
            hp=0.31,
            ammo=3,
            fire_cooldown_ticks=7,
            reload_cooldown_ticks=91,
            route=("1", "2", "3"),
            route_index=2,
            target_area_id="3",
            action_label="rl-engage_visible",
            aim_context="enemy",
        )
        second = replace(first, agents={**first.agents, "CT": moved_enemy})
        with patch.object(m, "can_see", return_value=False):
            obs_a = env.build_observation_for_side(first, "T")
            obs_b = env.build_observation_for_side(second, "T")
        np.testing.assert_allclose(obs_a, obs_b)

    def test_hidden_enemy_objective_progress_is_not_observed(self) -> None:
        env = self.make_env()
        assert env.state is not None
        first = env.state
        second = replace(
            first,
            bomb=replace(first.bomb, plant_progress_ticks=first.bomb.plant_progress_ticks + 50),
        )
        with patch.object(m, "can_see", return_value=False):
            obs_a = env.build_observation_for_side(first, "CT")
            obs_b = env.build_observation_for_side(second, "CT")
        np.testing.assert_allclose(obs_a, obs_b)

    def test_ct_cannot_observe_preplant_t_site_choice(self) -> None:
        env = self.make_env()
        assert env.state is not None
        site_a = replace(env.state, bomb=replace(env.state.bomb, site_id="A"))
        site_b = replace(env.state, bomb=replace(env.state.bomb, site_id="B"))
        with patch.object(m, "can_see", return_value=False):
            obs_a = env.build_observation_for_side(site_a, "CT")
            obs_b = env.build_observation_for_side(site_b, "CT")
            action_a = primitive_to_dust2_action(
                legacy_action_tuple("hold_angle"),
                "CT",
                env.dust2,
                env.config,
                env.visibility,
                env.path_cache,
                site_a,
                literal_actions=True,
            )
            action_b = primitive_to_dust2_action(
                legacy_action_tuple("hold_angle"),
                "CT",
                env.dust2,
                env.config,
                env.visibility,
                env.path_cache,
                site_b,
                literal_actions=True,
            )
        np.testing.assert_allclose(obs_a, obs_b)
        self.assertEqual(action_a["aim_target"], action_b["aim_target"])

    def test_phase_c_initial_orientation_does_not_reveal_preplant_site(self) -> None:
        env_a = self.make_env()
        env_b = PhaseCSelfPlayEnv(
            learner_side="T",
            seed=2607,
            randomize_scenario=False,
            site_choice="B",
            bomb_state="unplanted",
        )
        env_b.reset(seed=2607)
        assert env_a.state is not None
        assert env_b.state is not None
        self.assertEqual(env_a.state.agents["CT"].aim_deg, env_b.state.agents["CT"].aim_deg)
        self.assertEqual(
            env_a.state.agents["CT"].aim_pitch_deg,
            env_b.state.agents["CT"].aim_pitch_deg,
        )
        self.assertEqual(env_a.state.agents["CT"].macro_intent, "phase-c-policy")
        self.assertFalse(any(event.get("type") == "macro-intent" for event in env_a.events))
        with patch.object(m, "can_see", return_value=False):
            np.testing.assert_allclose(
                env_a.build_observation_for_side(env_a.state, "CT"),
                env_b.build_observation_for_side(env_b.state, "CT"),
            )

    def test_literal_hold_does_not_auto_engage_or_plant(self) -> None:
        env = self.make_env()
        assert env.state is not None
        with patch.object(m, "can_see", return_value=True):
            hold = primitive_to_dust2_action(
                legacy_action_tuple("hold_angle"),
                "T",
                env.dust2,
                env.config,
                env.visibility,
                env.path_cache,
                env.state,
                literal_actions=True,
            )
        self.assertFalse(hold["fire"])
        self.assertFalse(hold["plant"])
        self.assertEqual(hold["label"], "rl-hold_angle")
        with patch.object(m, "can_see", return_value=True), patch.object(
            m, "visible_combat_aim_point", return_value=env.state.agents["CT"].position
        ):
            legacy_hold = primitive_to_dust2_action(
                legacy_action_tuple("hold_angle"),
                "T",
                env.dust2,
                env.config,
                env.visibility,
                env.path_cache,
                env.state,
                literal_actions=False,
            )
        self.assertTrue(legacy_hold["fire"])
        self.assertIn("reactive-engage", legacy_hold["label"])

    def test_both_policy_actions_are_applied_in_one_decision(self) -> None:
        env = self.make_env(opponent_model=StubOpponent("branch_right"))
        with patch.object(
            m,
            "choose_action",
            side_effect=AssertionError("rules must not run when both policies act"),
        ):
            env.step(np.asarray(action_tuple("advance_local"), dtype=np.int64))
        assert env.state is not None
        self.assertEqual(env.state.agents["T"].action_label, "rl-advance_local")
        self.assertEqual(env.state.agents["CT"].action_label, "rl-branch_right")
        payload = env.trace_payload()
        self.assertEqual(
            payload["rl"]["decisionActions"][0]["actions"]["T"]["primitive"],
            "advance_local",
        )
        self.assertEqual(
            payload["rl"]["decisionActions"][0]["actions"]["CT"]["primitive"],
            "branch_right",
        )

    def test_phase_c_action_space_has_no_site_head_or_site_primitives(self) -> None:
        env = self.make_env()
        self.assertEqual(tuple(env.action_space.nvec), (
            len(PHASE_C_PRIMITIVES),
            len(PHASE_C_AIM_MODES),
            len(PHASE_C_MOVE_MODES),
        ))
        self.assertFalse(
            {"move_to_a", "move_to_b", "rotate_site"} & set(PHASE_C_PRIMITIVES)
        )
        described = describe_phase_c_action(action_tuple("advance_local"))
        self.assertNotIn("siteHead", described)

    def test_preplant_observation_is_independent_of_dummy_site(self) -> None:
        env = self.make_env()
        assert env.state is not None
        site_a = replace(env.state, bomb=replace(env.state.bomb, site_id="A"))
        site_b = replace(env.state, bomb=replace(env.state.bomb, site_id="B"))
        for side in ("T", "CT"):
            with patch.object(m, "can_see", return_value=False):
                np.testing.assert_allclose(
                    env.build_observation_for_side(site_a, side),
                    env.build_observation_for_side(site_b, side),
                )

    def test_trace_contains_no_site_selection_state_or_events(self) -> None:
        env = self.make_env(opponent_model=StubOpponent("branch_left"))
        for primitive in ("advance_local", "branch_right", "explore_local"):
            env.step(np.asarray(action_tuple(primitive), dtype=np.int64))
        payload = env.trace_payload()
        self.assertEqual(payload["summary"]["site_selection"], "none")
        for decision in payload["rl"]["decisionActions"]:
            self.assertNotIn("targetSite", decision)
            for described in decision["actions"].values():
                if isinstance(described, dict):
                    self.assertNotIn("siteHead", described)
                    self.assertNotIn(
                        described.get("primitive"),
                        {"move_to_a", "move_to_b", "rotate_site"},
                    )
        self.assertFalse(
            any(
                event.get("type") in {"site-choice", "target-site-commit"}
                for event in payload["events"]
            )
        )

    def test_plant_site_is_resolved_from_physical_bombsite(self) -> None:
        env = self.make_env()
        assert env.state is not None
        site_b = env.dust2.bomb_sites["B"]
        site_area = m.site_representative_area_id(env.dust2, site_b)
        agents = {
            **env.state.agents,
            "T": replace(
                env.state.agents["T"],
                area_id=site_area,
                position=env.dust2.areas[site_area].centroid,
                velocity=m.Vec3(0.0, 0.0, 0.0),
            ),
        }
        bomb = replace(env.state.bomb, site_id="A")
        actions = {
            "T": {"plant": True, "defuse": False},
            "CT": {"plant": False, "defuse": False},
        }
        events: list[dict] = []
        for tick in range(1, env.config.plant_ticks + 1):
            bomb = m.apply_bomb_objective(
                bomb,
                agents,
                actions,
                env.dust2,
                env.config,
                tick,
                events,
            )
        self.assertTrue(bomb.planted)
        self.assertEqual(bomb.site_id, "B")
        self.assertEqual(
            next(event["site"] for event in events if event["type"] == "bomb-planted"),
            "B",
        )

    def test_promotion_requires_each_side_and_unplanted_objective_floor(self) -> None:
        config = PhaseCConfig(run_dir="unused")
        base = {
            "generation": 3,
            "terminal_rate": 1.0,
            "abnormal_terminal_count": 0,
            "integrity_violation_count": 0,
            "t_cross_win_rate": 0.50,
            "ct_cross_win_rate": 0.50,
            "t_history_win_rate": 0.50,
            "ct_history_win_rate": 0.50,
            "t_unplanted_plant_rate": 0.50,
            "t_unplanted_win_rate": 0.35,
            "explicit_site_selection_count": 0,
            "run_invalidated": False,
            "promotion_allowed": True,
        }
        self.assertTrue(phase_c_promotion_eligible(config, **base))
        self.assertFalse(
            phase_c_promotion_eligible(
                config,
                **{**base, "t_cross_win_rate": 0.0, "ct_cross_win_rate": 1.0},
            )
        )
        self.assertFalse(
            phase_c_promotion_eligible(
                config,
                **{**base, "t_unplanted_plant_rate": 0.49},
            )
        )
        self.assertFalse(
            phase_c_promotion_eligible(
                config,
                **{**base, "explicit_site_selection_count": 1},
            )
        )

    def test_objective_curriculum_zero_reward_has_no_effect(self) -> None:
        env = self.make_env(objective_curriculum=PhaseCObjectiveCurriculumConfig())
        assert env.state is not None
        previous = env.state
        action = phase_c_literal(env, "hold_angle", "T", previous)
        next_state, events, tick_metric = m.step_dust2_round(
            env.dust2,
            env.config,
            env.visibility,
            env.path_cache,
            previous,
            env.rng,
            action_overrides={"T": action},
        )
        base_reward, _ = compute_reward(
            "T",
            previous,
            next_state,
            action,
            events,
            tick_metric,
            env.dust2,
            env.config,
            env.visibility,
            phase_c_reward_config(),
        )
        objective_reward, parts, _, _ = objective_curriculum_reward(
            learner="T",
            previous=previous,
            next_state=next_state,
            learner_action=action,
            dust2=env.dust2,
            config=env.config,
            path_cache=env.path_cache,
            curriculum=PhaseCObjectiveCurriculumConfig(),
            site_entry_already_awarded=False,
            valid_plant_start_already_awarded=False,
        )
        self.assertEqual(objective_reward, 0.0)
        self.assertTrue(all(value == 0.0 for value in parts.values()))
        self.assertEqual(base_reward + objective_reward, base_reward)

    def test_objective_distance_uses_nearest_fixed_bombsite_only(self) -> None:
        env = self.make_env()
        assert env.state is not None
        agent = env.state.agents["T"]
        expected = min(
            path_distance_to_fixed_bombsite(env.dust2, env.path_cache, agent.area_id, site)
            for site in env.dust2.bomb_sites.values()
        )
        self.assertAlmostEqual(
            nearest_fixed_bombsite_path_distance(env.dust2, env.path_cache, agent),
            expected,
        )
        payload = env.trace_payload()
        self.assertNotIn("targetSite", json.dumps(payload))
        self.assertEqual(payload["summary"]["site_selection"], "none")

    def test_ct_observation_has_no_objective_target_site_identity(self) -> None:
        env = PhaseCSelfPlayEnv(
            learner_side="CT",
            seed=2607,
            randomize_scenario=False,
            site_choice="A",
            bomb_state="unplanted",
            objective_curriculum=PhaseCObjectiveCurriculumConfig(
                objective_shaping_coef=1.0,
                objective_near_probability=1.0,
            ),
        )
        env.reset(seed=2607)
        assert env.state is not None
        a_obs = env.build_observation_for_side(env.state, "CT")
        b_state = replace(env.state, bomb=replace(env.state.bomb, site_id="B"))
        b_obs = env.build_observation_for_side(b_state, "CT")
        for index in (7, 36, 37):
            self.assertEqual(a_obs[index], 0.0)
            self.assertEqual(b_obs[index], 0.0)

    def test_objective_site_entry_and_valid_plant_start_are_once_only(self) -> None:
        env = self.make_env()
        assert env.state is not None
        site = env.dust2.bomb_sites["A"]
        site_area = m.site_representative_area_id(env.dust2, site)
        previous = env.state
        site_agent = replace(
            previous.agents["T"],
            area_id=site_area,
            position=env.dust2.areas[site_area].centroid,
            velocity=m.Vec3(0.0, 0.0, 0.0),
        )
        next_state = replace(
            previous,
            agents={**previous.agents, "T": site_agent},
        )
        curriculum = PhaseCObjectiveCurriculumConfig(
            objective_shaping_coef=0.0,
            site_entry_reward=0.03,
            valid_plant_start_reward=0.05,
        )
        reward, parts, site_awarded, plant_awarded = objective_curriculum_reward(
            learner="T",
            previous=previous,
            next_state=next_state,
            learner_action={"plant": False},
            dust2=env.dust2,
            config=env.config,
            path_cache=env.path_cache,
            curriculum=curriculum,
            site_entry_already_awarded=False,
            valid_plant_start_already_awarded=False,
        )
        self.assertAlmostEqual(reward, 0.03)
        self.assertAlmostEqual(parts["siteEntry"], 0.03)
        self.assertTrue(site_awarded)
        self.assertFalse(plant_awarded)

        plant_reward, plant_parts, _, plant_awarded = objective_curriculum_reward(
            learner="T",
            previous=next_state,
            next_state=next_state,
            learner_action={"plant": True},
            dust2=env.dust2,
            config=env.config,
            path_cache=env.path_cache,
            curriculum=curriculum,
            site_entry_already_awarded=True,
            valid_plant_start_already_awarded=False,
        )
        self.assertAlmostEqual(plant_reward, 0.05)
        self.assertAlmostEqual(plant_parts["validPlantStart"], 0.05)
        self.assertTrue(plant_awarded)
        repeat_reward, _, _, _ = objective_curriculum_reward(
            learner="T",
            previous=next_state,
            next_state=next_state,
            learner_action={"plant": True},
            dust2=env.dust2,
            config=env.config,
            path_cache=env.path_cache,
            curriculum=curriculum,
            site_entry_already_awarded=True,
            valid_plant_start_already_awarded=True,
        )
        self.assertEqual(repeat_reward, 0.0)

    def test_reload_refills_only_after_duration(self) -> None:
        env = self.make_env()
        assert env.state is not None
        agent = replace(env.state.agents["T"], ammo=7)
        reload_action = phase_c_literal(
            env,
            "reload",
            "T",
            replace(env.state, agents={**env.state.agents, "T": agent}),
        )
        hold_action = phase_c_literal(
            env,
            "hold_angle",
            "T",
            replace(env.state, agents={**env.state.agents, "T": agent}),
        )
        events: list[dict] = []
        agent = m.advance_agent(
            env.dust2, env.config, agent, reload_action, env.path_cache, events, 1
        )
        self.assertEqual(agent.ammo, 7)
        self.assertEqual(agent.reload_cooldown_ticks, env.config.reload_cooldown_ticks)
        for tick in range(2, env.config.reload_cooldown_ticks + 1):
            agent = m.advance_agent(
                env.dust2, env.config, agent, hold_action, env.path_cache, events, tick
            )
        self.assertEqual(agent.ammo, 7)
        agent = m.advance_agent(
            env.dust2,
            env.config,
            agent,
            hold_action,
            env.path_cache,
            events,
            env.config.reload_cooldown_ticks + 1,
        )
        self.assertEqual(agent.ammo, env.config.max_ammo)
        self.assertEqual(agent.reload_cooldown_ticks, 0)
        self.assertEqual(sum(event.get("type") == "reload" for event in events), 1)

    def test_invalid_objective_actions_are_literal_no_ops(self) -> None:
        env = self.make_env()
        assert env.state is not None
        state = env.state
        invalid_plant = phase_c_literal(env, "plant", "T", state)
        self.assertFalse(invalid_plant["plant"])
        self.assertEqual(invalid_plant["move"], "hold")

        planted = replace(
            state,
            bomb=replace(
                state.bomb,
                planted=True,
                position=env.dust2.bomb_sites["A"].position,
                planted_at_tick=state.tick,
            ),
        )
        invalid_defuse = phase_c_literal(env, "defuse", "CT", planted)
        self.assertFalse(invalid_defuse["defuse"])
        self.assertEqual(invalid_defuse["move"], "hold")
        self.assertNotEqual(invalid_defuse["aim_target"], planted.bomb.position)

    def test_invalid_combat_primitives_are_literal_no_ops(self) -> None:
        env = self.make_env()
        assert env.state is not None
        state = env.state
        full_reload = phase_c_literal(env, "reload", "T", state)
        self.assertFalse(full_reload.get("reload", False))
        self.assertEqual(full_reload["move"], "hold")

        empty_state = replace(
            state,
            agents={
                **state.agents,
                "T": replace(state.agents["T"], ammo=0),
            },
        )
        empty_engage = phase_c_literal(env, "engage_visible", "T", empty_state)
        self.assertFalse(empty_engage["fire"])
        self.assertEqual(empty_engage["move"], "hold")

        preplant_reposition = phase_c_literal(
            env,
            "postplant_reposition",
            "T",
            state,
        )
        self.assertFalse(preplant_reposition["plant"])

    def test_phase_c_does_not_auto_withhold_low_probability_shots(self) -> None:
        env = self.make_env()
        assert env.state is not None
        self.assertGreater(env.config.min_fire_probability, 0.0)
        actions = {
            "T": {"fire": True, "reload": False, "force_fire": True},
            "CT": {"fire": False, "reload": False},
        }
        events: list[dict] = []
        with patch.object(m, "shot_probabilities", return_value=(0.0, 0.0)):
            agents = m.apply_shots(
                env.state.agents,
                env.state.agents,
                actions,
                env.dust2,
                env.config,
                env.visibility,
                env.state.utilities,
                1,
                env.rng,
                events,
            )
        self.assertEqual(agents["T"].ammo, env.state.agents["T"].ammo - 1)
        self.assertTrue(any(event.get("type") == "shot" for event in events))
        self.assertFalse(any(event.get("type") == "withheld-shot" for event in events))

    def test_literal_visible_aim_does_not_force_head_priority(self) -> None:
        env = self.make_env()
        assert env.state is not None
        shooter = env.state.agents["T"]
        target = env.state.agents["CT"]
        origin = m.eye_position(shooter.position, env.config.eye_height)
        direction = m.aim_direction(shooter.aim_deg, shooter.aim_pitch_deg)
        body_point = m.Vec3(
            origin.x + direction.x * 500.0,
            origin.y + direction.y * 500.0,
            origin.z + direction.z * 500.0,
        )
        head_point = m.Vec3(body_point.x + 80.0, body_point.y, body_point.z + 20.0)
        samples = (
            m.HitSample("head", head_point, 3.0, 1.0),
            m.HitSample("body", body_point, 13.0, 0.5),
        )
        with patch.object(m, "visible_hit_samples", return_value=samples):
            aim_point = literal_visible_combat_aim_point(
                shooter,
                target,
                env.config,
                env.visibility,
                env.state.utilities,
            )
        self.assertEqual(aim_point, body_point)

    def test_ct_postplant_reposition_targets_site_not_hidden_bomb(self) -> None:
        env = self.make_env()
        assert env.state is not None
        site = env.dust2.bomb_sites["A"]
        hidden_bomb = replace(
            site.position,
            x=site.position.x + site.radius * 0.45,
            y=site.position.y + site.radius * 0.35,
        )
        planted = replace(
            env.state,
            bomb=replace(
                env.state.bomb,
                planted=True,
                position=hidden_bomb,
                planted_at_tick=env.state.tick,
            ),
        )
        target_area = m.nearest_area_id(env.dust2, hidden_bomb)
        action = phase_c_action_to_literal(
            action_tuple("postplant_reposition"),
            "CT",
            env.dust2,
            env.config,
            env.visibility,
            env.path_cache,
            planted,
            local_target_area=target_area,
        )
        self.assertEqual(action["target_area"], target_area)

    def test_death_terminal_waits_for_grace_period(self) -> None:
        env = self.make_env()
        assert env.state is not None
        agents = {
            **env.state.agents,
            "CT": replace(env.state.agents["CT"], is_alive=False, hp=0.0),
        }
        self.assertIsNone(
            m.resolve_terminal(agents, env.state.bomb, 100, env.config, 100)
        )
        terminal = m.resolve_terminal(
            agents,
            env.state.bomb,
            100 + env.config.death_grace_ticks,
            env.config,
            100,
        )
        assert terminal is not None
        self.assertEqual(terminal.reason, "ct-eliminated-before-plant")
        self.assertEqual(terminal.winner, "T")

    def test_dead_ct_cannot_win_by_round_timeout_during_grace(self) -> None:
        env = self.make_env()
        assert env.state is not None
        agents = {
            **env.state.agents,
            "CT": replace(env.state.agents["CT"], is_alive=False, hp=0.0),
        }
        self.assertIsNone(
            m.resolve_terminal(
                agents,
                env.state.bomb,
                env.config.round_ticks,
                env.config,
                env.config.round_ticks - 1,
            )
        )

    def test_t_can_plant_during_ct_death_grace(self) -> None:
        env = self.make_env()
        assert env.state is not None
        site = env.dust2.bomb_sites["A"]
        site_area = m.site_representative_area_id(env.dust2, site)
        agents = {
            "T": replace(
                env.state.agents["T"],
                area_id=site_area,
                position=env.dust2.areas[site_area].centroid,
                velocity=m.Vec3(0.0, 0.0, 0.0),
            ),
            "CT": replace(env.state.agents["CT"], is_alive=False, hp=0.0),
        }
        bomb = env.state.bomb
        actions = {
            "T": {"plant": True, "defuse": False},
            "CT": {"plant": False, "defuse": False},
        }
        events: list[dict] = []
        for tick in range(1, env.config.plant_ticks + 1):
            bomb = m.apply_bomb_objective(
                bomb,
                agents,
                actions,
                env.dust2,
                env.config,
                tick,
                events,
            )
        self.assertTrue(bomb.planted)
        self.assertLess(env.config.plant_ticks, env.config.death_grace_ticks)
        self.assertIsNone(
            m.resolve_terminal(
                agents,
                bomb,
                env.config.plant_ticks,
                env.config,
                0,
            )
        )

    def test_history_sampling_excludes_latest_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            latest_dir = run_dir / "checkpoints" / "ct" / "latest"
            history_dir = run_dir / "checkpoints" / "ct" / "history"
            latest_dir.mkdir(parents=True)
            history_dir.mkdir(parents=True)
            latest = latest_dir / "phase-c-ct-latest.zip"
            latest.touch()
            older = history_dir / "phase-c-ct-generation-00000.zip"
            newest_duplicate = history_dir / "phase-c-ct-generation-00001.zip"
            older.touch()
            newest_duplicate.touch()
            config = PhaseCConfig(
                run_dir=str(run_dir),
                latest_opponent_probability=0.0,
            )
            opponents = choose_opponents(config, run_dir, "CT", generation=2, n_envs=8)
            self.assertEqual(opponents, [older] * 8)

    def test_checkpoint_recovery_rolls_back_uncommitted_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            for side in ("t", "ct"):
                latest_dir = run_dir / "checkpoints" / side / "latest"
                history_dir = run_dir / "checkpoints" / side / "history"
                latest_dir.mkdir(parents=True)
                history_dir.mkdir(parents=True)
                (history_dir / f"phase-c-{side}-generation-00000.zip").write_bytes(
                    f"{side}-committed".encode()
                )
                (history_dir / f"phase-c-{side}-generation-00001.zip").write_bytes(
                    f"{side}-partial".encode()
                )
                (latest_dir / f"phase-c-{side}-latest.zip").write_bytes(
                    f"{side}-partial".encode()
                )
            generation = reconcile_checkpoints_to_committed_generation(run_dir)
            self.assertEqual(generation, 0)
            for side in ("t", "ct"):
                latest = run_dir / "checkpoints" / side / "latest" / f"phase-c-{side}-latest.zip"
                partial = (
                    run_dir
                    / "checkpoints"
                    / side
                    / "history"
                    / f"phase-c-{side}-generation-00001.zip"
                )
                self.assertEqual(latest.read_bytes(), f"{side}-committed".encode())
                self.assertFalse(partial.exists())

    def test_visible_event_only_records_sight_acquisition(self) -> None:
        env = self.make_env()
        assert env.state is not None
        events: list[dict] = []
        with patch.object(m, "can_see", return_value=True):
            agents = m.apply_information(
                env.state.agents,
                env.dust2,
                env.config,
                env.visibility,
                env.state.utilities,
                1,
                events,
            )
            agents = m.apply_information(
                agents,
                env.dust2,
                env.config,
                env.visibility,
                env.state.utilities,
                2,
                events,
            )
        self.assertEqual(
            sum(event.get("type") == "visible" for event in events),
            2,
        )

    def test_reset_clears_opponent_hidden_state(self) -> None:
        env = self.make_env(opponent_model=StubOpponent("hold_angle"))
        env.step(np.asarray(action_tuple("hold_angle"), dtype=np.int64))
        self.assertIsNotNone(env.opponent_lstm_state)
        env.reset(seed=2608)
        self.assertIsNone(env.opponent_lstm_state)
        self.assertTrue(env.opponent_episode_start)

    def test_dead_postplant_learner_is_auto_resolved_to_terminal(self) -> None:
        env = self.make_env(opponent_model=StubOpponent("defuse"))
        assert env.state is not None
        site = env.dust2.bomb_sites["A"]
        ct_area = m.nearest_area_id(env.dust2, site.position)
        env.state = replace(
            env.state,
            bomb=replace(
                env.state.bomb,
                planted=True,
                position=site.position,
                planted_at_tick=0,
            ),
            agents={
                "T": replace(env.state.agents["T"], is_alive=False, hp=0.0),
                "CT": replace(
                    env.state.agents["CT"],
                    area_id=ct_area,
                    position=site.position,
                ),
            },
            death_tick=0,
        )
        _, reward, terminated, _, _ = env.step(
            np.asarray(action_tuple("hold_angle"), dtype=np.int64)
        )
        self.assertTrue(terminated)
        assert env.state.terminal is not None
        self.assertEqual(env.state.terminal.reason, "bomb-defused")
        self.assertEqual(reward, -1.0)
        self.assertTrue(
            all(
                decision["actions"]["T"] == "dead"
                for decision in env.decision_actions
            )
        )

    def test_alive_ct_auto_resolves_preplant_kill_grace(self) -> None:
        env = PhaseCSelfPlayEnv(
            learner_side="CT",
            seed=2607,
            opponent_model=StubOpponent("hold_angle"),
            randomize_scenario=False,
            site_choice="A",
            bomb_state="unplanted",
        )
        env.reset(seed=2607)
        assert env.state is not None
        env.state = replace(
            env.state,
            agents={
                "T": replace(env.state.agents["T"], is_alive=False, hp=0.0),
                "CT": env.state.agents["CT"],
            },
            death_tick=0,
        )
        _, reward, terminated, _, _ = env.step(
            np.asarray(action_tuple("hold_angle"), dtype=np.int64)
        )
        self.assertTrue(terminated)
        assert env.state.terminal is not None
        self.assertEqual(env.state.terminal.reason, "t-eliminated-before-plant")
        self.assertEqual(reward, 1.0)

    def test_dead_policy_opponent_does_not_predict_or_fall_back_to_rules(self) -> None:
        opponent = StubOpponent("hold_angle")
        env = self.make_env(opponent_model=opponent)
        assert env.state is not None
        env.state = replace(
            env.state,
            agents={
                "T": env.state.agents["T"],
                "CT": replace(env.state.agents["CT"], is_alive=False, hp=0.0),
            },
            death_tick=0,
        )
        with patch.object(
            m,
            "choose_action",
            side_effect=AssertionError("dead policy side must not use rules"),
        ):
            env.step(np.asarray(action_tuple("hold_angle"), dtype=np.int64))
        self.assertEqual(opponent.predict_calls, 0)

    def test_implicit_resets_advance_scenario_seed(self) -> None:
        env = PhaseCSelfPlayEnv(learner_side="T", seed=2607, randomize_scenario=True)
        env.reset(seed=2607)
        first_areas = dict(env.initial_area_ids)
        env.reset()
        second_areas = dict(env.initial_area_ids)
        self.assertEqual(env._reset_seed, 2608)
        self.assertNotEqual(first_areas, second_areas)

    def test_random_start_positions_do_not_overlap(self) -> None:
        env = PhaseCSelfPlayEnv(learner_side="T", seed=2607, randomize_scenario=True)
        for seed in range(2607, 2627):
            env.reset(seed=seed)
            assert env.state is not None
            self.assertGreaterEqual(
                m.distance3(
                    env.state.agents["T"].position,
                    env.state.agents["CT"].position,
                ),
                env.config.collision_radius * 2.0,
            )

    def test_dynamic_player_collision_blocks_overlap(self) -> None:
        env = self.make_env()
        assert env.state is not None
        previous = env.state.agents
        t_start = previous["T"].position
        ct_start = m.Vec3(
            t_start.x + env.config.collision_radius * 2.0 + 2.0,
            t_start.y,
            t_start.z,
        )
        previous = {
            "T": replace(previous["T"], position=t_start),
            "CT": replace(previous["CT"], position=ct_start),
        }
        advanced = {
            "T": replace(
                previous["T"],
                position=m.Vec3(t_start.x + 3.0, t_start.y, t_start.z),
            ),
            "CT": previous["CT"],
        }
        resolved = m.resolve_player_collision(advanced, previous, env.config)
        self.assertEqual(resolved["T"].position, t_start)
        self.assertEqual(resolved["CT"].position, ct_start)

    def test_phase_c_integrity_audit_detects_physics_violations(self) -> None:
        env = self.make_env()
        assert env.state is not None
        self.assertEqual(
            phase_c_integrity_violations(env.state, env.dust2, env.config),
            (),
        )
        invalid_t = replace(
            env.state.agents["T"],
            ammo=env.config.max_ammo + 1,
            velocity=m.Vec3(env.config.run_speed_per_tick + 1.0, 0.0, 0.0),
            aim_turn_delta_deg=env.config.max_turn_deg_per_tick + 1.0,
        )
        invalid_ct = replace(
            env.state.agents["CT"],
            position=invalid_t.position,
        )
        violations = phase_c_integrity_violations(
            replace(
                env.state,
                agents={"T": invalid_t, "CT": invalid_ct},
            ),
            env.dust2,
            env.config,
        )
        self.assertIn("T:ammo-out-of-range", violations)
        self.assertIn("T:horizontal-speed-limit", violations)
        self.assertIn("T:yaw-rate-limit", violations)
        self.assertIn("players:collision-overlap", violations)

    def test_jump_velocity_cannot_exceed_horizontal_run_speed(self) -> None:
        velocity = m.limit_horizontal_speed(
            m.Vec3(0.5841614264663804, 2.103664545691089, 0.1824525559236747),
            2.15,
        )
        self.assertLessEqual(math.hypot(velocity.x, velocity.y), 2.15)
        self.assertEqual(velocity.z, 0.1824525559236747)

    def test_initial_planted_bomb_position_varies_within_site(self) -> None:
        positions: set[tuple[float, float, float]] = set()
        for seed in range(2607, 2615):
            env = PhaseCSelfPlayEnv(
                learner_side="T",
                seed=seed,
                randomize_scenario=False,
                site_choice="A",
                bomb_state="planted_a",
            )
            env.reset(seed=seed)
            assert env.state is not None
            position = env.state.bomb.position
            assert position is not None
            positions.add((position.x, position.y, position.z))
            self.assertIn(
                m.nearest_area_id(env.dust2, position),
                env.dust2.bomb_sites["A"].area_ids,
            )
        self.assertGreater(len(positions), 1)

    def test_phase_c_reward_contains_only_discrete_events(self) -> None:
        config = phase_c_reward_config()
        self.assertEqual(config.damage_reward_coef, 0.0)
        self.assertEqual(config.damage_taken_coef, 0.0)
        self.assertEqual(config.invalid_objective_cost, 0.0)
        self.assertEqual(config.visible_no_response_cost, 0.0)
        self.assertEqual(config.idle_degenerate_cost, 0.0)
        self.assertEqual(config.aim_wall_cost, 0.0)
        self.assertEqual(config.potential_coef, 0.0)

        env = self.make_env()
        assert env.state is not None
        previous = env.state
        dead_ct = replace(previous.agents["CT"], is_alive=False, hp=0.0)
        won = replace(
            previous,
            agents={**previous.agents, "CT": dead_ct},
            terminal=m.Terminal(reason="ct-eliminated-before-plant", winner="T", tick=1),
        )
        reward, parts = compute_reward(
            "T",
            previous,
            won,
            {
                "fire": False,
                "plant": False,
                "defuse": False,
                "label": "rl-hold_angle",
            },
            [],
            {"T": {"enemyVisible": True}},
            env.dust2,
            env.config,
            env.visibility,
            config,
        )
        self.assertAlmostEqual(reward, 1.05)
        self.assertAlmostEqual(parts["terminal"], 1.0)
        self.assertAlmostEqual(parts["kill"], 0.05)
        self.assertEqual(parts["visibleNoResponse"], 0.0)

        planted = replace(
            previous,
            bomb=replace(
                previous.bomb,
                planted=True,
                position=env.dust2.bomb_sites[previous.bomb.site_id].position,
                planted_at_tick=1,
            ),
        )
        plant_reward, _ = compute_reward(
            "T",
            previous,
            planted,
            {
                "fire": False,
                "plant": True,
                "defuse": False,
                "label": "rl-plant",
            },
            [{"type": "bomb-planted", "tick": 1, "side": "T"}],
            {"T": {}},
            env.dust2,
            env.config,
            env.visibility,
            config,
        )
        self.assertAlmostEqual(plant_reward, 0.1)

        lost = replace(
            previous,
            terminal=m.Terminal(reason="t-timeout-no-plant", winner="CT", tick=1),
        )
        loss_reward, _ = compute_reward(
            "T",
            previous,
            lost,
            {
                "fire": False,
                "plant": False,
                "defuse": False,
                "label": "rl-hold_angle",
            },
            [],
            {"T": {}},
            env.dust2,
            env.config,
            env.visibility,
            config,
        )
        self.assertAlmostEqual(loss_reward, -1.0)

        ct_plant_reward, _ = compute_reward(
            "CT",
            previous,
            planted,
            {
                "fire": False,
                "plant": False,
                "defuse": False,
                "label": "rl-hold_angle",
            },
            [{"type": "bomb-planted", "tick": 1, "side": "T"}],
            {"CT": {}},
            env.dust2,
            env.config,
            env.visibility,
            config,
        )
        self.assertAlmostEqual(ct_plant_reward, 0.0)

    def test_ct_preplant_kill_bonus_is_not_duplicated(self) -> None:
        env = self.make_env()
        assert env.state is not None
        previous = env.state
        dead_t = replace(previous.agents["T"], is_alive=False, hp=0.0)
        won = replace(
            previous,
            agents={**previous.agents, "T": dead_t},
            terminal=m.Terminal(reason="t-eliminated-before-plant", winner="CT", tick=1),
        )
        reward, parts = compute_reward(
            "CT",
            previous,
            won,
            {
                "fire": False,
                "plant": False,
                "defuse": False,
                "label": "rl-hold_angle",
            },
            [],
            {"CT": {}},
            env.dust2,
            env.config,
            env.visibility,
            phase_c_reward_config(),
        )
        self.assertAlmostEqual(reward, 1.15)
        self.assertAlmostEqual(parts["kill"], 0.15)


if __name__ == "__main__":
    unittest.main()
