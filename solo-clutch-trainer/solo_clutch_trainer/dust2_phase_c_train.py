from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import random
import shutil
import time
from typing import Any, Iterable

from . import dust2_mvp as m
from .dust2_phase_c import (
    PHASE_C_ENV_REVISION,
    PHASE_C_HELD_OUT_SEEDS,
    PhaseCObjectiveCurriculumConfig,
    PhaseCSelfPlayEnv,
)
from .dust2_rl import Side


DEFAULT_PHASE_B_CHECKPOINT = (
    ".solo-clutch-runs/dust2-rl-b-20260608-a20-plantguard-v2/"
    "checkpoints/b-chunk-00016-steps-32768.zip"
)
VALID_PHASE_C_TERMINALS = {
    "bomb-defused",
    "bomb-exploded",
    "ct-eliminated-after-plant",
    "t-eliminated-before-plant",
    "ct-eliminated-before-plant",
    "t-timeout-no-plant",
}


@dataclass(frozen=True)
class PhaseCConfig:
    run_dir: str
    seed: int = 2607
    max_wall_seconds: int = 21_600
    chunk_steps: int = 4096
    n_envs: int = 2
    max_envs: int = 4
    n_steps: int = 128
    batch_size: int = 256
    learning_rate: float = 1e-4
    ent_coef: float = 0.03
    gamma: float = 0.999
    gae_lambda: float = 0.95
    checkpoint_cap_gb: float = 10.0
    history_limit: int = 8
    latest_opponent_probability: float = 0.70
    eval_episodes_per_seed: int = 2
    max_decisions: int = 900
    min_side_win_rate: float = 0.45
    min_unplanted_plant_rate: float = 0.50
    min_unplanted_t_win_rate: float = 0.35
    device: str = "auto"
    phase_b_checkpoint: str = DEFAULT_PHASE_B_CHECKPOINT
    bootstrap_t_checkpoint: str | None = None
    bootstrap_ct_checkpoint: str | None = None
    curriculum_stage: str = "C2"
    objective_shaping_coef: float | None = None
    site_entry_reward: float | None = None
    valid_plant_start_reward: float | None = None
    curriculum_plant_reward: float | None = None
    objective_near_probability: float | None = None
    objective_mid_probability: float | None = None
    objective_uniform_probability: float | None = None
    train_sides: str = "both"
    allow_stable_promotion: bool = True
    c0_max_generations: int = 5
    c0_min_plant_rate: float = 0.30
    smoke_eval: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class MatchSummary:
    episodes: int
    t_win_rate: float
    ct_win_rate: float
    terminal_rate: float
    plant_rate: float
    unplanted_episodes: int
    unplanted_plant_rate: float
    unplanted_t_win_rate: float
    defuse_rate: float
    kill_rate: float
    avg_seconds: float
    terminal_reasons: dict[str, int]
    primitive_counts: dict[str, int]
    anomaly_counts: dict[str, int]
    anomaly_rate: float
    max_repeat_streak: dict[str, int]
    abnormal_terminal_count: int
    abnormal_terminal_rate: float
    integrity_violation_counts: dict[str, int]
    integrity_violation_rate: float
    explicit_site_selection_count: int


def other_side(side: Side) -> Side:
    return "CT" if side == "T" else "T"


def objective_curriculum_for_generation(
    config: PhaseCConfig,
    generation: int,
) -> PhaseCObjectiveCurriculumConfig:
    stage = config.curriculum_stage.upper()
    if stage == "C0":
        defaults = {
            "objective_shaping_coef": 1.0,
            "site_entry_reward": 0.03,
            "valid_plant_start_reward": 0.05,
            "plant_reward": 0.20,
            "objective_near_probability": 0.60,
            "objective_mid_probability": 0.30,
            "objective_uniform_probability": 0.10,
        }
    elif stage == "C1":
        if generation <= 3:
            shaping = 1.0
            near, mid, uniform = 0.40, 0.20, 0.40
        elif generation <= 6:
            shaping = 0.5
            near, mid, uniform = 0.20, 0.10, 0.70
        elif generation <= 9:
            shaping = 0.1
            near, mid, uniform = 0.0, 0.0, 1.0
        else:
            shaping = 0.0
            near, mid, uniform = 0.0, 0.0, 1.0
        defaults = {
            "objective_shaping_coef": shaping,
            "site_entry_reward": 0.03 if shaping > 0.0 else 0.0,
            "valid_plant_start_reward": 0.05 if shaping > 0.0 else 0.0,
            "plant_reward": 0.20 if shaping > 0.0 else 0.10,
            "objective_near_probability": near,
            "objective_mid_probability": mid,
            "objective_uniform_probability": uniform,
        }
    else:
        defaults = {
            "objective_shaping_coef": 0.0,
            "site_entry_reward": 0.0,
            "valid_plant_start_reward": 0.0,
            "plant_reward": 0.10,
            "objective_near_probability": 0.0,
            "objective_mid_probability": 0.0,
            "objective_uniform_probability": 1.0,
        }
    return PhaseCObjectiveCurriculumConfig(
        stage=stage,
        objective_shaping_coef=(
            defaults["objective_shaping_coef"]
            if config.objective_shaping_coef is None
            else config.objective_shaping_coef
        ),
        site_entry_reward=(
            defaults["site_entry_reward"]
            if config.site_entry_reward is None
            else config.site_entry_reward
        ),
        valid_plant_start_reward=(
            defaults["valid_plant_start_reward"]
            if config.valid_plant_start_reward is None
            else config.valid_plant_start_reward
        ),
        plant_reward=(
            defaults["plant_reward"]
            if config.curriculum_plant_reward is None
            else config.curriculum_plant_reward
        ),
        objective_near_probability=(
            defaults["objective_near_probability"]
            if config.objective_near_probability is None
            else config.objective_near_probability
        ),
        objective_mid_probability=(
            defaults["objective_mid_probability"]
            if config.objective_mid_probability is None
            else config.objective_mid_probability
        ),
        objective_uniform_probability=(
            defaults["objective_uniform_probability"]
            if config.objective_uniform_probability is None
            else config.objective_uniform_probability
        ),
    )


def promotion_allowed_for_generation(config: PhaseCConfig, generation: int) -> bool:
    if not config.allow_stable_promotion:
        return False
    stage = config.curriculum_stage.upper()
    if stage == "C2":
        return True
    if stage != "C1":
        return False
    return (
        generation >= 12
        and objective_curriculum_for_generation(config, generation).objective_shaping_coef == 0.0
    )


def phase_c_integrity_violations(
    state: m.RoundState,
    dust2: m.Dust2Map,
    config: m.Dust2Config,
) -> tuple[str, ...]:
    violations: list[str] = []
    for side, agent in state.agents.items():
        numeric_values = (
            agent.position.x,
            agent.position.y,
            agent.position.z,
            agent.velocity.x,
            agent.velocity.y,
            agent.velocity.z,
            agent.aim_deg,
            agent.aim_pitch_deg,
            agent.hp,
        )
        if not all(math.isfinite(value) for value in numeric_values):
            violations.append(f"{side}:non-finite-state")
        if agent.area_id not in dust2.areas:
            violations.append(f"{side}:unknown-nav-area")
        if not 0.0 <= agent.hp <= 1.0:
            violations.append(f"{side}:hp-out-of-range")
        if not 0 <= agent.ammo <= config.max_ammo:
            violations.append(f"{side}:ammo-out-of-range")
        horizontal_speed = math.hypot(agent.velocity.x, agent.velocity.y)
        if horizontal_speed > config.run_speed_per_tick + 1e-6:
            violations.append(f"{side}:horizontal-speed-limit")
        if agent.aim_turn_delta_deg > config.max_turn_deg_per_tick + 1e-6:
            violations.append(f"{side}:yaw-rate-limit")
        if (
            agent.aim_pitch_turn_delta_deg
            > config.max_pitch_turn_deg_per_tick + 1e-6
        ):
            violations.append(f"{side}:pitch-rate-limit")
        if (
            not agent.is_alive
            and state.death_tick is not None
            and state.tick > state.death_tick
            and agent.action_label != "dead"
        ):
            violations.append(f"{side}:dead-action")
    if all(agent.is_alive for agent in state.agents.values()):
        separation = m.distance3(
            state.agents["T"].position,
            state.agents["CT"].position,
        )
        if separation < config.collision_radius * 2.0 - 1e-6:
            violations.append("players:collision-overlap")
    if (
        state.terminal is not None
        and state.terminal.reason not in VALID_PHASE_C_TERMINALS
    ):
        violations.append("round:invalid-terminal")
    return tuple(violations)


def checkpoint_dirs(run_dir: Path, side: Side) -> tuple[Path, Path]:
    root = run_dir / "checkpoints" / side.lower()
    return root / "latest", root / "history"


def latest_checkpoint(run_dir: Path, side: Side) -> Path:
    latest_dir, _ = checkpoint_dirs(run_dir, side)
    return latest_dir / f"phase-c-{side.lower()}-latest.zip"


def history_checkpoints(run_dir: Path, side: Side) -> list[Path]:
    _, history_dir = checkpoint_dirs(run_dir, side)
    return sorted(history_dir.glob("*.zip"))


def make_vec_env(
    config: PhaseCConfig,
    *,
    learner_side: Side,
    opponent_paths: list[Path | None],
    seed_offset: int,
    generation: int,
):
    from stable_baselines3.common.monitor import Monitor
    from stable_baselines3.common.vec_env import DummyVecEnv

    factories = []
    for rank, opponent_path in enumerate(opponent_paths):
        env_seed = config.seed + seed_offset + rank

        def factory(
            env_seed: int = env_seed,
            opponent_path: Path | None = opponent_path,
        ):
            return Monitor(
                PhaseCSelfPlayEnv(
                    learner_side=learner_side,
                    seed=env_seed,
                    opponent_checkpoint=opponent_path,
                    frame_stride=20,
                    randomize_scenario=True,
                    objective_curriculum=objective_curriculum_for_generation(
                        config,
                        generation,
                    ),
                )
            )

        factories.append(factory)
    return DummyVecEnv(factories)


def make_model(env: Any, config: PhaseCConfig, seed: int):
    from sb3_contrib import RecurrentPPO

    return RecurrentPPO(
        "MlpLstmPolicy",
        env,
        n_steps=config.n_steps,
        batch_size=config.batch_size,
        learning_rate=config.learning_rate,
        gamma=config.gamma,
        gae_lambda=config.gae_lambda,
        ent_coef=config.ent_coef,
        policy_kwargs={
            "lstm_hidden_size": 256,
            "n_lstm_layers": 1,
            "net_arch": {"pi": [64, 64], "vf": [64, 64]},
            "shared_lstm": False,
            "enable_critic_lstm": True,
        },
        verbose=1,
        seed=seed,
        device=config.device,
    )


def load_model(checkpoint: Path, env: Any, config: PhaseCConfig):
    from sb3_contrib import RecurrentPPO

    return RecurrentPPO.load(
        str(checkpoint),
        env=env,
        device=config.device,
        custom_objects={
            "n_steps": config.n_steps,
            "batch_size": config.batch_size,
            "learning_rate": config.learning_rate,
            "ent_coef": config.ent_coef,
            "gamma": config.gamma,
            "gae_lambda": config.gae_lambda,
        },
    )


def initialize_models(config: PhaseCConfig, run_dir: Path) -> None:
    for index, side in enumerate(("T", "CT")):
        checkpoint = latest_checkpoint(run_dir, side)
        if checkpoint.exists():
            continue
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        _, history_dir = checkpoint_dirs(run_dir, side)
        history_dir.mkdir(parents=True, exist_ok=True)
        bootstrap = (
            config.bootstrap_t_checkpoint
            if side == "T"
            else config.bootstrap_ct_checkpoint
        )
        if bootstrap is not None and Path(bootstrap).exists():
            shutil.copy2(bootstrap, checkpoint)
            shutil.copy2(
                bootstrap,
                history_dir / f"phase-c-{side.lower()}-generation-00000.zip",
            )
            continue
        env = make_vec_env(
            config,
            learner_side=side,
            opponent_paths=[None] * config.n_envs,
            seed_offset=1000 * index,
            generation=0,
        )
        model = make_model(env, config, config.seed + index)
        model.save(str(checkpoint.with_suffix("")))
        model.save(str((history_dir / f"phase-c-{side.lower()}-generation-00000").with_suffix("")))
        env.close()


def choose_opponents(
    config: PhaseCConfig,
    run_dir: Path,
    opponent: Side,
    generation: int,
    n_envs: int,
) -> list[Path]:
    latest = latest_checkpoint(run_dir, opponent)
    history = history_checkpoints(run_dir, opponent)[:-1]
    rng = random.Random(config.seed + generation * 97 + (0 if opponent == "T" else 1))
    choices: list[Path] = []
    for _ in range(n_envs):
        if not history or rng.random() < config.latest_opponent_probability:
            choices.append(latest)
        else:
            choices.append(rng.choice(history))
    return choices


def train_side(
    config: PhaseCConfig,
    run_dir: Path,
    side: Side,
    generation: int,
    n_envs: int,
) -> dict[str, Any]:
    opponent = other_side(side)
    opponent_paths = choose_opponents(config, run_dir, opponent, generation, n_envs)
    env = make_vec_env(
        config,
        learner_side=side,
        opponent_paths=opponent_paths,
        seed_offset=generation * 10_000 + (0 if side == "T" else 5_000),
        generation=generation,
    )
    checkpoint = latest_checkpoint(run_dir, side)
    model = load_model(checkpoint, env, config)
    started = time.monotonic()
    before_steps = int(model.num_timesteps)
    model.learn(total_timesteps=config.chunk_steps, reset_num_timesteps=False)
    elapsed = time.monotonic() - started
    model.save(str(checkpoint.with_suffix("")))
    _, history_dir = checkpoint_dirs(run_dir, side)
    history_path = history_dir / f"phase-c-{side.lower()}-generation-{generation:05d}.zip"
    model.save(str(history_path.with_suffix("")))
    env.close()
    prune_history(run_dir, side, config.history_limit)
    enforce_checkpoint_cap(run_dir, config.checkpoint_cap_gb)
    return {
        "side": side,
        "generation": generation,
        "stepsBefore": before_steps,
        "stepsAfter": int(model.num_timesteps),
        "elapsedSeconds": round(elapsed, 3),
        "nEnvs": n_envs,
        "opponents": [str(path) for path in opponent_paths],
        "checkpoint": str(checkpoint),
        "historyCheckpoint": str(history_path),
    }


def play_match(
    t_checkpoint: Path | None,
    ct_checkpoint: Path | None,
    seeds: Iterable[int],
    episodes_per_seed: int,
    max_decisions: int,
    *,
    t_uses_literal_actions: bool = True,
    learner_side: Side = "T",
    curriculum_config: PhaseCObjectiveCurriculumConfig | None = None,
) -> MatchSummary:
    from sb3_contrib import RecurrentPPO

    learner_checkpoint = t_checkpoint if learner_side == "T" else ct_checkpoint
    opponent_checkpoint = ct_checkpoint if learner_side == "T" else t_checkpoint
    if learner_checkpoint is None:
        raise ValueError(f"{learner_side} learner checkpoint is required")
    learner_model = RecurrentPPO.load(str(learner_checkpoint), device="auto")
    opponent_model = (
        RecurrentPPO.load(str(opponent_checkpoint), device="auto")
        if opponent_checkpoint is not None
        else None
    )
    seed_values = tuple(int(seed) for seed in seeds)
    if not seed_values:
        raise ValueError("at least one evaluation seed is required")
    first_seed = seed_values[0]
    env = PhaseCSelfPlayEnv(
        learner_side=learner_side,
        seed=first_seed,
        opponent_checkpoint=opponent_checkpoint,
        opponent_model=opponent_model,
        randomize_scenario=True,
        frame_stride=100,
        learner_literal_actions=(
            t_uses_literal_actions if learner_side == "T" else True
        ),
        objective_curriculum=curriculum_config,
    )
    totals = {
        "episodes": 0,
        "tWins": 0,
        "ctWins": 0,
        "terminals": 0,
        "plants": 0,
        "defuses": 0,
        "kills": 0,
        "seconds": 0.0,
        "unplantedEpisodes": 0,
        "unplantedPlants": 0,
        "unplantedTWins": 0,
    }
    terminal_reasons: dict[str, int] = {}
    primitive_counts: dict[str, int] = {}
    anomaly_counts: dict[str, int] = {}
    integrity_violation_counts: dict[str, int] = {}
    integrity_checks = 0
    global_max_repeat: dict[str, int] = {"T": 0, "CT": 0}
    for seed in seed_values:
        for episode_index in range(episodes_per_seed):
            episode_seed = int(seed) + episode_index
            from stable_baselines3.common.utils import set_random_seed

            set_random_seed(episode_seed)
            obs, _ = env.reset(seed=episode_seed)
            assert env.state is not None
            initially_unplanted = not env.state.bomb.planted
            lstm_state = None
            episode_start = True
            previous_primitive: dict[Side, str | None] = {"T": None, "CT": None}
            repeat_streak: dict[Side, int] = {"T": 0, "CT": 0}
            max_repeat_streak: dict[Side, int] = {"T": 0, "CT": 0}
            for _ in range(max_decisions):
                state_before = env.state
                action, lstm_state = learner_model.predict(
                    obs,
                    state=lstm_state,
                    episode_start=[episode_start],
                    deterministic=False,
                )
                obs, _, terminated, truncated, info = env.step(action)
                if env.state is not None:
                    integrity_checks += 1
                    for violation in phase_c_integrity_violations(
                        env.state,
                        env.dust2,
                        env.config,
                    ):
                        integrity_violation_counts[violation] = (
                            integrity_violation_counts.get(violation, 0) + 1
                        )
                described_actions = info.get("actions", {})
                if "targetSite" in info:
                    anomaly_counts["explicit-site-selection"] = (
                        anomaly_counts.get("explicit-site-selection", 0) + 1
                    )
                for side in ("T", "CT"):
                    described = described_actions.get(side, {})
                    primitive = described.get("primitive") if isinstance(described, dict) else None
                    if not primitive:
                        continue
                    primitive = str(primitive)
                    if primitive in {"move_to_a", "move_to_b", "rotate_site"}:
                        anomaly_counts["explicit-site-selection"] = (
                            anomaly_counts.get("explicit-site-selection", 0) + 1
                        )
                    if isinstance(described, dict) and "siteHead" in described:
                        anomaly_counts["explicit-site-selection"] = (
                            anomaly_counts.get("explicit-site-selection", 0) + 1
                        )
                    key = f"{side}:{primitive}"
                    primitive_counts[key] = primitive_counts.get(key, 0) + 1
                    totals["actions"] = totals.get("actions", 0) + 1
                    if previous_primitive[side] == primitive:
                        repeat_streak[side] += 1
                    else:
                        repeat_streak[side] = 1
                    previous_primitive[side] = primitive
                    max_repeat_streak[side] = max(max_repeat_streak[side], repeat_streak[side])
                    if repeat_streak[side] == 20:
                        anomaly_counts["repeat-primitive-20"] = anomaly_counts.get("repeat-primitive-20", 0) + 1
                    if state_before is None:
                        continue
                    agent = state_before.agents[side]
                    if primitive == "reload" and agent.ammo >= env.config.max_ammo:
                        anomaly_counts["full-ammo-reload"] = anomaly_counts.get("full-ammo-reload", 0) + 1
                    if primitive == "engage_visible" and agent.ammo <= 0:
                        anomaly_counts["empty-ammo-engage"] = anomaly_counts.get("empty-ammo-engage", 0) + 1
                    if side == "T" and primitive == "defuse":
                        anomaly_counts["wrong-side-objective"] = anomaly_counts.get("wrong-side-objective", 0) + 1
                    if side == "CT" and primitive == "plant":
                        anomaly_counts["wrong-side-objective"] = anomaly_counts.get("wrong-side-objective", 0) + 1
                    if side == "T" and primitive == "plant":
                        on_any_site = any(
                            m.is_on_bomb_site(env.dust2, site, agent)
                            for site in env.dust2.bomb_sites.values()
                        )
                        if state_before.bomb.planted or not on_any_site:
                            anomaly_counts["invalid-plant"] = anomaly_counts.get("invalid-plant", 0) + 1
                    if side == "CT" and primitive == "defuse":
                        if not state_before.bomb.planted:
                            anomaly_counts["invalid-defuse"] = anomaly_counts.get("invalid-defuse", 0) + 1
                episode_start = terminated or truncated
                if episode_start:
                    break
            payload = env.trace_payload()
            summary = payload["summary"]
            totals["episodes"] += 1
            totals["terminals"] += int(summary.get("winner") in {"T", "CT"})
            totals["tWins"] += int(summary.get("winner") == "T")
            totals["ctWins"] += int(summary.get("winner") == "CT")
            totals["seconds"] += float(summary.get("terminal_seconds", 0.0))
            events = payload.get("events", [])
            totals["plants"] += int(any(event.get("type") == "bomb-planted" for event in events))
            if initially_unplanted:
                totals["unplantedEpisodes"] += 1
                totals["unplantedPlants"] += int(
                    any(event.get("type") == "bomb-planted" for event in events)
                )
                totals["unplantedTWins"] += int(summary.get("winner") == "T")
            totals["defuses"] += int(any(event.get("type") == "bomb-defused" for event in events))
            totals["kills"] += int(any(event.get("type") == "death" for event in events))
            reason = str(summary.get("terminal_reason", "partial-rollout"))
            terminal_reasons[reason] = terminal_reasons.get(reason, 0) + 1
            totals["abnormalTerminals"] = totals.get("abnormalTerminals", 0) + int(
                reason not in VALID_PHASE_C_TERMINALS
            )
            for side in ("T", "CT"):
                global_max_repeat[side] = max(global_max_repeat[side], max_repeat_streak[side])
    env.close()
    episodes = max(1, totals["episodes"])
    unplanted_episodes = totals["unplantedEpisodes"]
    return MatchSummary(
        episodes=totals["episodes"],
        t_win_rate=totals["tWins"] / episodes,
        ct_win_rate=totals["ctWins"] / episodes,
        terminal_rate=totals["terminals"] / episodes,
        plant_rate=totals["plants"] / episodes,
        unplanted_episodes=unplanted_episodes,
        unplanted_plant_rate=totals["unplantedPlants"] / max(1, unplanted_episodes),
        unplanted_t_win_rate=totals["unplantedTWins"] / max(1, unplanted_episodes),
        defuse_rate=totals["defuses"] / episodes,
        kill_rate=totals["kills"] / episodes,
        avg_seconds=totals["seconds"] / episodes,
        terminal_reasons=terminal_reasons,
        primitive_counts=primitive_counts,
        anomaly_counts=anomaly_counts,
        anomaly_rate=sum(anomaly_counts.values()) / max(1, totals.get("actions", 0)),
        max_repeat_streak=global_max_repeat,
        abnormal_terminal_count=totals.get("abnormalTerminals", 0),
        abnormal_terminal_rate=totals.get("abnormalTerminals", 0) / episodes,
        integrity_violation_counts=integrity_violation_counts,
        integrity_violation_rate=sum(integrity_violation_counts.values())
        / max(1, integrity_checks),
        explicit_site_selection_count=anomaly_counts.get(
            "explicit-site-selection",
            0,
        ),
    )


def elo_from_win_rate(win_rate: float) -> float:
    bounded = min(0.999, max(0.001, win_rate))
    return 400.0 * __import__("math").log10(bounded / (1.0 - bounded))


def phase_c_promotion_eligible(
    config: PhaseCConfig,
    *,
    generation: int,
    terminal_rate: float,
    abnormal_terminal_count: int,
    integrity_violation_count: int,
    t_cross_win_rate: float,
    ct_cross_win_rate: float,
    t_history_win_rate: float,
    ct_history_win_rate: float,
    t_unplanted_plant_rate: float,
    t_unplanted_win_rate: float,
    explicit_site_selection_count: int,
    run_invalidated: bool,
    promotion_allowed: bool,
) -> bool:
    return (
        promotion_allowed
        and not run_invalidated
        and generation >= 3
        and terminal_rate >= 0.98
        and abnormal_terminal_count == 0
        and integrity_violation_count == 0
        and explicit_site_selection_count == 0
        and t_cross_win_rate >= config.min_side_win_rate
        and ct_cross_win_rate >= config.min_side_win_rate
        and t_history_win_rate >= config.min_side_win_rate
        and ct_history_win_rate >= config.min_side_win_rate
        and t_unplanted_plant_rate >= config.min_unplanted_plant_rate
        and t_unplanted_win_rate >= config.min_unplanted_t_win_rate
    )


def evaluate_generation(
    config: PhaseCConfig,
    run_dir: Path,
    generation: int,
    previous_t: Path,
    previous_ct: Path,
) -> dict[str, Any]:
    current_t = latest_checkpoint(run_dir, "T")
    current_ct = latest_checkpoint(run_dir, "CT")
    seeds = PHASE_C_HELD_OUT_SEEDS[:2] if config.dry_run else PHASE_C_HELD_OUT_SEEDS
    episodes = 1 if config.dry_run else config.eval_episodes_per_seed
    eval_curriculum = objective_curriculum_for_generation(config, generation)
    latest_pair = play_match(current_t, current_ct, seeds, episodes, config.max_decisions, curriculum_config=eval_curriculum)
    if config.smoke_eval:
        t_vs_previous_ct = latest_pair
        previous_t_vs_ct = latest_pair
        t_vs_rules = latest_pair
        ct_vs_rules = latest_pair
    else:
        t_vs_previous_ct = play_match(current_t, previous_ct, seeds, episodes, config.max_decisions, curriculum_config=eval_curriculum)
        previous_t_vs_ct = play_match(previous_t, current_ct, seeds, episodes, config.max_decisions, curriculum_config=eval_curriculum)
        t_vs_rules = play_match(current_t, None, seeds, episodes, config.max_decisions, curriculum_config=eval_curriculum)
        ct_vs_rules = play_match(
            None,
            current_ct,
            seeds,
            episodes,
            config.max_decisions,
            learner_side="CT",
            curriculum_config=eval_curriculum,
        )
    # Phase B uses the retired four-head site-selection action space and is not
    # behaviorally comparable to the site-free Phase C v8 policy.
    phase_b_vs_ct = None
    stable_dir = run_dir / "checkpoints" / "stable"
    stable_t = stable_dir / "phase-c-t-stable.zip"
    stable_ct = stable_dir / "phase-c-ct-stable.zip"
    t_vs_stable_ct = (
        play_match(
            current_t,
            stable_ct,
            seeds,
            episodes,
            config.max_decisions,
            curriculum_config=eval_curriculum,
        )
        if stable_ct.exists() and not config.smoke_eval
        else None
    )
    stable_t_vs_ct = (
        play_match(
            stable_t,
            current_ct,
            seeds,
            episodes,
            config.max_decisions,
            curriculum_config=eval_curriculum,
        )
        if stable_t.exists() and not config.smoke_eval
        else None
    )
    history_t = history_checkpoints(run_dir, "T")[:-1]
    history_ct = history_checkpoints(run_dir, "CT")[:-1]
    t_history_scores: list[float] = []
    ct_history_scores: list[float] = []
    t_history_summaries: list[MatchSummary] = []
    ct_history_summaries: list[MatchSummary] = []
    history_seed = (seeds[0],)
    for checkpoint in ([] if config.smoke_eval else history_ct):
        summary = play_match(
            current_t,
            checkpoint,
            history_seed,
            1,
            config.max_decisions,
            curriculum_config=eval_curriculum,
        )
        t_history_summaries.append(summary)
        t_history_scores.append(summary.t_win_rate)
    for checkpoint in ([] if config.smoke_eval else history_t):
        summary = play_match(
            checkpoint,
            current_ct,
            history_seed,
            1,
            config.max_decisions,
            curriculum_config=eval_curriculum,
        )
        ct_history_summaries.append(summary)
        ct_history_scores.append(summary.ct_win_rate)
    t_history_win_rate = (
        sum(t_history_scores) / len(t_history_scores)
        if t_history_scores
        else 0.5
    )
    ct_history_win_rate = (
        sum(ct_history_scores) / len(ct_history_scores)
        if ct_history_scores
        else 0.5
    )
    history_win_rate = (t_history_win_rate + ct_history_win_rate) / 2.0
    cross_win_rate = (t_vs_previous_ct.t_win_rate + previous_t_vs_ct.ct_win_rate) / 2.0
    all_match_summaries = [
        latest_pair,
        t_vs_previous_ct,
        previous_t_vs_ct,
        t_vs_rules,
        ct_vs_rules,
        *t_history_summaries,
        *ct_history_summaries,
    ]
    if phase_b_vs_ct is not None:
        all_match_summaries.append(phase_b_vs_ct)
    if t_vs_stable_ct is not None:
        all_match_summaries.append(t_vs_stable_ct)
    if stable_t_vs_ct is not None:
        all_match_summaries.append(stable_t_vs_ct)
    terminal_rate = min(
        summary.terminal_rate for summary in all_match_summaries
    )
    abnormal_terminal_count = sum(
        summary.abnormal_terminal_count for summary in all_match_summaries
    )
    integrity_violation_count = sum(
        sum(summary.integrity_violation_counts.values())
        for summary in all_match_summaries
    )
    explicit_site_selection_count = sum(
        summary.explicit_site_selection_count
        for summary in all_match_summaries
    )
    candidate_t_summaries = [
        latest_pair,
        t_vs_previous_ct,
        t_vs_rules,
        *t_history_summaries,
    ]
    if t_vs_stable_ct is not None:
        candidate_t_summaries.append(t_vs_stable_ct)
    candidate_t_unplanted = [
        summary
        for summary in candidate_t_summaries
        if summary.unplanted_episodes > 0
    ]
    t_unplanted_plant_rate = min(
        (summary.unplanted_plant_rate for summary in candidate_t_unplanted),
        default=0.0,
    )
    t_unplanted_win_rate = min(
        (summary.unplanted_t_win_rate for summary in candidate_t_unplanted),
        default=0.0,
    )
    run_invalidated = (run_dir / "INVALIDATED.json").exists()
    promoted = phase_c_promotion_eligible(
        config,
        generation=generation,
        terminal_rate=terminal_rate,
        abnormal_terminal_count=abnormal_terminal_count,
        integrity_violation_count=integrity_violation_count,
        t_cross_win_rate=t_vs_previous_ct.t_win_rate,
        ct_cross_win_rate=previous_t_vs_ct.ct_win_rate,
        t_history_win_rate=t_history_win_rate,
        ct_history_win_rate=ct_history_win_rate,
        t_unplanted_plant_rate=t_unplanted_plant_rate,
        t_unplanted_win_rate=t_unplanted_win_rate,
        explicit_site_selection_count=explicit_site_selection_count,
        run_invalidated=run_invalidated,
        promotion_allowed=promotion_allowed_for_generation(config, generation),
    )
    payload = {
        "environmentRevision": PHASE_C_ENV_REVISION,
        "generation": generation,
        "curriculum": asdict(eval_curriculum),
        "promotionAllowed": promotion_allowed_for_generation(config, generation),
        "latestPair": asdict(latest_pair),
        "tVsPreviousCt": asdict(t_vs_previous_ct),
        "previousTVsCt": asdict(previous_t_vs_ct),
        "tVsRules": asdict(t_vs_rules),
        "ctVsRules": asdict(ct_vs_rules),
        "phaseBTVsCt": None,
        "phaseBEvaluation": "skipped-incompatible-action-space",
        "smokeEval": config.smoke_eval,
        "tVsStableCt": asdict(t_vs_stable_ct) if t_vs_stable_ct else None,
        "stableTVsCt": asdict(stable_t_vs_ct) if stable_t_vs_ct else None,
        "historyWinRate": history_win_rate,
        "tHistoryWinRate": t_history_win_rate,
        "ctHistoryWinRate": ct_history_win_rate,
        "crossWinRate": cross_win_rate,
        "tCrossWinRate": t_vs_previous_ct.t_win_rate,
        "ctCrossWinRate": previous_t_vs_ct.ct_win_rate,
        "tUnplantedPlantRate": t_unplanted_plant_rate,
        "tUnplantedWinRate": t_unplanted_win_rate,
        "promotionThresholds": {
            "minSideWinRate": config.min_side_win_rate,
            "minUnplantedPlantRate": config.min_unplanted_plant_rate,
            "minUnplantedTWinRate": config.min_unplanted_t_win_rate,
        },
        "terminalRate": terminal_rate,
        "abnormalTerminalCount": abnormal_terminal_count,
        "integrityViolationCount": integrity_violation_count,
        "explicitSiteSelectionCount": explicit_site_selection_count,
        "runInvalidated": run_invalidated,
        "tEloVsPreviousCt": elo_from_win_rate(t_vs_previous_ct.t_win_rate),
        "ctEloVsPreviousT": elo_from_win_rate(previous_t_vs_ct.ct_win_rate),
        "promoted": promoted,
    }
    if promoted:
        stable_dir = run_dir / "checkpoints" / "stable"
        stable_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current_t, stable_dir / "phase-c-t-stable.zip")
        shutil.copy2(current_ct, stable_dir / "phase-c-ct-stable.zip")
        (stable_dir / "promotion.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
    return payload


def adaptive_env_count(config: PhaseCConfig, current: int) -> int:
    try:
        import psutil

        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.2)
        if memory.percent >= 88.0 or cpu >= 92.0:
            return 2
        if memory.percent <= 78.0 and cpu <= 55.0:
            return 4 if config.max_envs >= 4 else 2
    except Exception:
        pass
    return current


def prune_history(run_dir: Path, side: Side, limit: int) -> None:
    paths = history_checkpoints(run_dir, side)
    for path in paths[:-max(1, limit)]:
        path.unlink(missing_ok=True)


def enforce_checkpoint_cap(run_dir: Path, cap_gb: float) -> None:
    cap_bytes = int(cap_gb * 1024**3)
    paths = sorted(
        (run_dir / "checkpoints").rglob("*.zip"),
        key=lambda path: path.stat().st_mtime,
    )
    total = sum(path.stat().st_size for path in paths)
    protected = {
        latest_checkpoint(run_dir, "T"),
        latest_checkpoint(run_dir, "CT"),
        run_dir / "checkpoints" / "stable" / "phase-c-t-stable.zip",
        run_dir / "checkpoints" / "stable" / "phase-c-ct-stable.zip",
    }
    for path in paths:
        if total <= cap_bytes:
            break
        if path in protected:
            continue
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        total -= size


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def last_committed_generation(run_dir: Path) -> int:
    path = run_dir / "generations.jsonl"
    if not path.exists():
        return 0
    committed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        committed = max(committed, int(row.get("generation", 0)))
    return committed


def reconcile_checkpoints_to_committed_generation(run_dir: Path) -> int:
    committed = last_committed_generation(run_dir)
    for side in ("T", "CT"):
        histories = history_checkpoints(run_dir, side)
        committed_name = f"phase-c-{side.lower()}-generation-{committed:05d}.zip"
        committed_checkpoint = next(
            (path for path in histories if path.name == committed_name),
            None,
        )
        if committed_checkpoint is None:
            raise RuntimeError(
                f"missing committed {side} checkpoint for generation {committed}"
            )
        for path in histories:
            suffix = path.stem.rsplit("-", 1)[-1]
            if suffix.isdigit() and int(suffix) > committed:
                path.unlink(missing_ok=True)
        shutil.copy2(committed_checkpoint, latest_checkpoint(run_dir, side))
    return committed


def run(config: PhaseCConfig) -> dict[str, Any]:
    run_dir = Path(config.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    initialize_models(config, run_dir)
    generation = reconcile_checkpoints_to_committed_generation(run_dir)
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "kind": "dust2-phase-c-self-play",
                "environmentRevision": PHASE_C_ENV_REVISION,
                "status": "running",
                "config": asdict(config),
                "pid": os.getpid(),
                "startedAt": time.time(),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    started = time.monotonic()
    n_envs = config.n_envs
    max_generations = 2 if config.dry_run else 1_000_000
    if config.curriculum_stage.upper() == "C0":
        max_generations = min(max_generations, config.c0_max_generations)
    last_eval: dict[str, Any] | None = None
    stop_reason = "wall-time-complete"
    while generation < max_generations and time.monotonic() - started < config.max_wall_seconds:
        generation += 1
        previous_t = latest_checkpoint(run_dir, "T")
        previous_ct = latest_checkpoint(run_dir, "CT")
        previous_dir = run_dir / "checkpoints" / "previous"
        previous_dir.mkdir(parents=True, exist_ok=True)
        previous_t_copy = previous_dir / f"phase-c-t-generation-{generation - 1:05d}.zip"
        previous_ct_copy = previous_dir / f"phase-c-ct-generation-{generation - 1:05d}.zip"
        shutil.copy2(previous_t, previous_t_copy)
        shutil.copy2(previous_ct, previous_ct_copy)
        t_train = (
            train_side(config, run_dir, "T", generation, n_envs)
            if config.train_sides in {"both", "T"}
            else {"side": "T", "generation": generation, "skipped": True}
        )
        ct_train = (
            train_side(config, run_dir, "CT", generation, n_envs)
            if config.train_sides in {"both", "CT"}
            else {
                "side": "CT",
                "generation": generation,
                "skipped": True,
                "reason": "frozen-by-curriculum",
            }
        )
        last_eval = evaluate_generation(
            config,
            run_dir,
            generation,
            previous_t_copy,
            previous_ct_copy,
        )
        previous_t_copy.unlink(missing_ok=True)
        previous_ct_copy.unlink(missing_ok=True)
        row = {
            "environmentRevision": PHASE_C_ENV_REVISION,
            "generation": generation,
            "curriculum": asdict(objective_curriculum_for_generation(config, generation)),
            "elapsedSeconds": round(time.monotonic() - started, 3),
            "tTrain": t_train,
            "ctTrain": ct_train,
            "evaluation": last_eval,
        }
        append_jsonl(run_dir / "generations.jsonl", row)
        n_envs = adaptive_env_count(config, n_envs)
        enforce_checkpoint_cap(run_dir, config.checkpoint_cap_gb)
        if (
            config.curriculum_stage.upper() == "C0"
            and last_eval is not None
        ):
            plant_rate = float(last_eval.get("tUnplantedPlantRate", 0.0))
            if plant_rate >= config.c0_min_plant_rate:
                stop_reason = "c0-objective-gate-passed"
                break
            if generation >= config.c0_max_generations and plant_rate <= 0.0:
                stop_reason = "c0-zero-plant-rate-review-required"
                break
    result = {
        "environmentRevision": PHASE_C_ENV_REVISION,
        "status": "complete" if config.dry_run else stop_reason,
        "generation": generation,
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "latestEvaluation": last_eval,
        "runDir": str(run_dir),
    }
    manifest_path.write_text(
        json.dumps(
            {
                "kind": "dust2-phase-c-self-play",
                "environmentRevision": PHASE_C_ENV_REVISION,
                "status": result["status"],
                "config": asdict(config),
                "pid": os.getpid(),
                "result": result,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return result


def parse_args() -> PhaseCConfig:
    parser = argparse.ArgumentParser(description="Dust2 Phase C dual-LSTM self-play trainer")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--confirm-train", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--seed", type=int, default=2607)
    parser.add_argument("--max-wall-seconds", type=int, default=21_600)
    parser.add_argument("--chunk-steps", type=int, default=4096)
    parser.add_argument("--n-envs", type=int, default=2)
    parser.add_argument("--max-envs", type=int, default=4)
    parser.add_argument("--n-steps", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--ent-coef", type=float, default=0.03)
    parser.add_argument("--checkpoint-cap-gb", type=float, default=10.0)
    parser.add_argument("--history-limit", type=int, default=8)
    parser.add_argument("--eval-episodes-per-seed", type=int, default=2)
    parser.add_argument("--max-decisions", type=int, default=900)
    parser.add_argument("--min-side-win-rate", type=float, default=0.45)
    parser.add_argument("--min-unplanted-plant-rate", type=float, default=0.50)
    parser.add_argument("--min-unplanted-t-win-rate", type=float, default=0.35)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--phase-b-checkpoint", default=DEFAULT_PHASE_B_CHECKPOINT)
    parser.add_argument("--bootstrap-t-checkpoint")
    parser.add_argument("--bootstrap-ct-checkpoint")
    parser.add_argument("--curriculum-stage", default="C2", choices=("C0", "C1", "C2"))
    parser.add_argument("--objective-shaping-coef", type=float)
    parser.add_argument("--site-entry-reward", type=float)
    parser.add_argument("--valid-plant-start-reward", type=float)
    parser.add_argument("--curriculum-plant-reward", type=float)
    parser.add_argument("--objective-near-probability", type=float)
    parser.add_argument("--objective-mid-probability", type=float)
    parser.add_argument("--objective-uniform-probability", type=float)
    parser.add_argument("--train-sides", default="both", choices=("both", "T", "CT"))
    parser.add_argument("--allow-stable-promotion", action="store_true")
    parser.add_argument("--c0-max-generations", type=int, default=5)
    parser.add_argument("--c0-min-plant-rate", type=float, default=0.30)
    parser.add_argument("--smoke-eval", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not args.confirm_train:
        parser.error("formal Phase C training requires --confirm-train")
    chunk_steps = 256 if args.dry_run and args.chunk_steps == 4096 else args.chunk_steps
    max_wall_seconds = 1800 if args.dry_run and args.max_wall_seconds == 21_600 else args.max_wall_seconds
    return PhaseCConfig(
        run_dir=args.run_dir,
        seed=args.seed,
        max_wall_seconds=max_wall_seconds,
        chunk_steps=chunk_steps,
        n_envs=args.n_envs,
        max_envs=args.max_envs,
        n_steps=args.n_steps,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        ent_coef=args.ent_coef,
        checkpoint_cap_gb=args.checkpoint_cap_gb,
        history_limit=args.history_limit,
        eval_episodes_per_seed=args.eval_episodes_per_seed,
        max_decisions=args.max_decisions,
        min_side_win_rate=args.min_side_win_rate,
        min_unplanted_plant_rate=args.min_unplanted_plant_rate,
        min_unplanted_t_win_rate=args.min_unplanted_t_win_rate,
        device=args.device,
        phase_b_checkpoint=args.phase_b_checkpoint,
        bootstrap_t_checkpoint=args.bootstrap_t_checkpoint,
        bootstrap_ct_checkpoint=args.bootstrap_ct_checkpoint,
        curriculum_stage=args.curriculum_stage,
        objective_shaping_coef=args.objective_shaping_coef,
        site_entry_reward=args.site_entry_reward,
        valid_plant_start_reward=args.valid_plant_start_reward,
        curriculum_plant_reward=args.curriculum_plant_reward,
        objective_near_probability=args.objective_near_probability,
        objective_mid_probability=args.objective_mid_probability,
        objective_uniform_probability=args.objective_uniform_probability,
        train_sides=args.train_sides,
        allow_stable_promotion=args.allow_stable_promotion,
        c0_max_generations=args.c0_max_generations,
        c0_min_plant_rate=args.c0_min_plant_rate,
        smoke_eval=args.smoke_eval,
        dry_run=args.dry_run,
    )


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
