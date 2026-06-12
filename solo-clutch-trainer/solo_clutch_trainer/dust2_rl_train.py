from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import time
from typing import Any, Literal

import numpy as np

from .dust2_rl import Dust2PrimitiveEnv, Dust2RewardConfig, Dust2Scenario


PhaseName = Literal["A", "B"]
SPAWN_MODES = [
    "uniform_walkable",
    "objective_biased",
    "clutch_like",
    "plant_curriculum",
    "postplant_curriculum",
    "mixed_curriculum",
]


@dataclass(frozen=True)
class TrainHyperparams:
    n_envs: int = 2
    max_envs: int = 6
    n_steps: int = 128
    batch_size: int = 128
    learning_rate: float = 2.5e-4
    gamma: float = 0.995
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    lstm_hidden_size: int = 256
    n_lstm_layers: int = 1
    mlp_width: int = 64


@dataclass(frozen=True)
class SupervisorConfig:
    seed: int = 2607
    run_dir: str = ".solo-clutch-runs/dust2-rl-training"
    checkpoint_cap_gb: float = 10.0
    keep_recent_checkpoints: int = 5
    keep_best_checkpoints: int = 3
    phase_a_steps: int = 2_000_000
    phase_b_steps: int = 4_000_000
    max_wall_seconds: int = 21_600
    chunk_steps: int = 8_192
    eval_episodes: int = 8
    eval_max_decisions: int = 900
    eval_wall_seconds: float = 120.0
    trace_wall_seconds: float = 60.0
    trace_episodes: int = 2
    save_every_chunks: int = 1
    eval_every_chunks: int = 1
    trace_every_chunks: int = 2
    learner_side: str = "T"
    spawn_mode: str = "clutch_like"
    phase_a_spawn_mode: str | None = None
    phase_b_spawn_mode: str | None = None
    device: str = "auto"
    cpu_high_pct: float = 92.0
    cpu_low_pct: float = 55.0
    memory_high_pct: float = 88.0
    disk_free_low_gb: float = 20.0
    min_steps_per_second: float = 1.0
    allow_env_adaptation: bool = False
    convergence_patience_evals: int = 5
    convergence_min_delta: float = 0.015
    convergence_min_behavior_score: float = 0.65
    convergence_min_objective_rate: float = 0.75
    convergence_min_win_rate: float = 0.0
    convergence_max_objective_spam_rate: float = 0.25
    convergence_max_plant_interrupt_rate: float = 0.40
    convergence_max_no_plant_rate: float = 0.35
    convergence_max_postplant_defuse_loss_rate: float = 0.70
    min_phase_eval_rounds: int = 4
    min_phase_chunks: int = 4
    load_checkpoint: str | None = None


@dataclass(frozen=True)
class ResourceSnapshot:
    timestamp: float
    cpu_percent: float | None
    memory_percent: float | None
    memory_available_gb: float | None
    process_rss_gb: float | None
    disk_free_gb: float
    disk_used_gb: float
    load_average_1m: float | None


@dataclass(frozen=True)
class EvalSummary:
    episodes: int
    win_rate: float
    terminal_rate: float
    plant_rate: float
    defuse_rate: float
    timeout_no_plant_rate: float
    avg_reward: float
    avg_seconds: float
    aim_quality_mean: float
    passed_rate: float
    objective_rate: float
    objective_miss_rate: float
    preplant_death_rate: float
    no_plant_rate: float
    objective_spam_rate: float
    plant_interrupt_rate: float
    postplant_defuse_loss_rate: float
    visible_no_shot_rate: float
    behavior_score: float


def reward_config_for_phase(phase: PhaseName) -> Dust2RewardConfig:
    if phase == "A":
        return Dust2RewardConfig(
            phase="A",
            terminal_win_reward=1.00,
            terminal_loss_reward=-1.40,
            plant_reward=3.20,
            defuse_reward=0.80,
            plant_progress_reward=0.001,
            plant_interrupt_cost=0.030,
            damage_reward_coef=0.025,
            damage_taken_coef=0.22,
            kill_bonus=0.02,
            death_penalty=0.30,
            preplant_death_extra_penalty=2.20,
            phase_a_potential_coef=0.45,
        )
    return Dust2RewardConfig(
        phase="B",
        terminal_win_reward=4.00,
        terminal_loss_reward=-5.00,
        plant_reward=1.20,
        defuse_reward=1.20,
        plant_progress_reward=0.00010,
        enemy_defuse_progress_cost=0.004,
        plant_interrupt_cost=0.030,
        defuse_interrupt_reward=0.800,
        postplant_alive_reward=0.0,
        damage_reward_coef=0.08,
        damage_taken_coef=0.12,
        kill_bonus=0.40,
        death_penalty=0.60,
        preplant_death_extra_penalty=1.20,
        shot_cost=0.001,
        empty_fire_cost=0.030,
        low_probability_shot_cost=0.005,
        invalid_objective_cost=0.050,
        visible_no_response_cost=0.0002,
        idle_degenerate_cost=0.0002,
        aim_wall_cost=0.0002,
        phase_b_potential_coef=0.01,
    )


def spawn_mode_for_phase(config: SupervisorConfig, phase: PhaseName) -> str:
    if phase == "A":
        return config.phase_a_spawn_mode or config.spawn_mode
    return config.phase_b_spawn_mode or config.spawn_mode


def make_env(seed: int, rank: int, phase: PhaseName, config: SupervisorConfig):
    def _factory():
        from stable_baselines3.common.monitor import Monitor

        scenario = Dust2Scenario(
            seed=seed + rank,
            spawn_mode=spawn_mode_for_phase(config, phase),
            learner_side=config.learner_side,  # type: ignore[arg-type]
            opponent_side="CT" if config.learner_side == "T" else "T",  # type: ignore[arg-type]
            frame_stride=20,
        )
        env = Dust2PrimitiveEnv(scenario=scenario, reward_config=reward_config_for_phase(phase))
        return Monitor(env)

    return _factory


def make_vec_env(seed: int, phase: PhaseName, config: SupervisorConfig, hp: TrainHyperparams):
    from stable_baselines3.common.vec_env import DummyVecEnv

    return DummyVecEnv([make_env(seed, rank, phase, config) for rank in range(hp.n_envs)])


def make_model(env: Any, hp: TrainHyperparams, config: SupervisorConfig):
    from sb3_contrib import RecurrentPPO

    policy_kwargs = {
        "lstm_hidden_size": hp.lstm_hidden_size,
        "n_lstm_layers": hp.n_lstm_layers,
        "net_arch": {"pi": [hp.mlp_width, hp.mlp_width], "vf": [hp.mlp_width, hp.mlp_width]},
        "shared_lstm": False,
        "enable_critic_lstm": True,
    }
    return RecurrentPPO(
        "MlpLstmPolicy",
        env,
        n_steps=hp.n_steps,
        batch_size=hp.batch_size,
        learning_rate=hp.learning_rate,
        gamma=hp.gamma,
        gae_lambda=hp.gae_lambda,
        clip_range=hp.clip_range,
        ent_coef=hp.ent_coef,
        vf_coef=hp.vf_coef,
        max_grad_norm=hp.max_grad_norm,
        policy_kwargs=policy_kwargs,
        verbose=1,
        seed=config.seed,
        device=config.device,
    )


def load_model(path: str, env: Any, hp: TrainHyperparams, config: SupervisorConfig):
    from sb3_contrib import RecurrentPPO

    checkpoint = Path(path)
    if not checkpoint.exists():
        raise FileNotFoundError(f"checkpoint not found: {checkpoint}")
    loaded = RecurrentPPO.load(str(checkpoint), env=env, device=config.device)
    rebuilt = rebuild_model_with_policy_state(loaded, env, hp, config)
    return rebuilt


def rebuild_model_with_policy_state(model: Any, env: Any, hp: TrainHyperparams, config: SupervisorConfig):
    state_dict = {key: value.detach().cpu().clone() for key, value in model.policy.state_dict().items()}
    rebuilt = make_model(env, hp, config)
    rebuilt.policy.load_state_dict(state_dict)
    rebuilt.num_timesteps = model.num_timesteps
    return rebuilt


def sample_resources(run_dir: Path) -> ResourceSnapshot:
    disk = shutil.disk_usage(run_dir)
    cpu_percent = None
    memory_percent = None
    memory_available_gb = None
    process_rss_gb = None
    try:
        import psutil  # type: ignore[import-not-found]

        cpu_percent = float(psutil.cpu_percent(interval=0.1))
        memory = psutil.virtual_memory()
        memory_percent = float(memory.percent)
        memory_available_gb = bytes_to_gb(int(memory.available))
        process_rss_gb = bytes_to_gb(int(psutil.Process(os.getpid()).memory_info().rss))
    except Exception:
        pass
    try:
        load_average_1m = float(os.getloadavg()[0])
    except OSError:
        load_average_1m = None
    if cpu_percent is None and load_average_1m is not None:
        cpu_count = max(1, os.cpu_count() or 1)
        cpu_percent = min(100.0, load_average_1m / cpu_count * 100.0)
    if memory_percent is None or memory_available_gb is None:
        fallback_memory = macos_vm_stat_memory()
        if fallback_memory is not None:
            memory_percent, memory_available_gb = fallback_memory
    if process_rss_gb is None:
        process_rss_gb = process_rss_gb_fallback()
    return ResourceSnapshot(
        timestamp=time.time(),
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        memory_available_gb=memory_available_gb,
        process_rss_gb=process_rss_gb,
        disk_free_gb=bytes_to_gb(disk.free),
        disk_used_gb=bytes_to_gb(disk.used),
        load_average_1m=load_average_1m,
    )


def macos_vm_stat_memory() -> tuple[float, float] | None:
    try:
        completed = subprocess.run(["vm_stat"], capture_output=True, check=True, text=True)
    except Exception:
        return None
    first_line, *lines = completed.stdout.splitlines()
    match = re.search(r"page size of (\d+) bytes", first_line)
    if match is None:
        return None
    page_size = int(match.group(1))
    pages: dict[str, int] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value_match = re.search(r"(\d+)", raw_value.replace(".", ""))
        if value_match is None:
            continue
        pages[key.strip().strip('"')] = int(value_match.group(1))
    free = pages.get("Pages free", 0)
    active = pages.get("Pages active", 0)
    inactive = pages.get("Pages inactive", 0)
    speculative = pages.get("Pages speculative", 0)
    wired = pages.get("Pages wired down", 0)
    compressor = pages.get("Pages occupied by compressor", 0)
    purgeable = pages.get("Pages purgeable", 0)
    total_pages = free + active + inactive + speculative + wired + compressor
    if total_pages <= 0:
        return None
    available_pages = free + inactive + speculative + purgeable
    used_pages = max(0, total_pages - available_pages)
    memory_percent = used_pages / total_pages * 100.0
    available_gb = bytes_to_gb(available_pages * page_size)
    return round(memory_percent, 3), available_gb


def process_rss_gb_fallback() -> float | None:
    try:
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        return None
    # macOS reports bytes, most Linux builds report KiB.
    bytes_value = maxrss if maxrss > 10_000_000 else maxrss * 1024
    return bytes_to_gb(int(bytes_value))


def adapt_hyperparams(
    hp: TrainHyperparams,
    resources: ResourceSnapshot,
    config: SupervisorConfig,
    steps_per_second: float,
) -> tuple[TrainHyperparams, list[str]]:
    next_hp = hp
    changes: list[str] = []
    memory_hot = resources.memory_percent is not None and resources.memory_percent >= config.memory_high_pct
    disk_low = resources.disk_free_gb <= config.disk_free_low_gb
    cpu_hot = resources.cpu_percent is not None and resources.cpu_percent >= config.cpu_high_pct
    cpu_cold = resources.cpu_percent is not None and resources.cpu_percent <= config.cpu_low_pct
    slow = steps_per_second > 0 and steps_per_second < config.min_steps_per_second

    if memory_hot or disk_low:
        reduced_envs = max(1, hp.n_envs - 1) if config.allow_env_adaptation else hp.n_envs
        reduced_batch = max(16, min(hp.batch_size, hp.n_steps * reduced_envs))
        if reduced_envs != hp.n_envs:
            next_hp = replace(next_hp, n_envs=reduced_envs, batch_size=reduced_batch)
            changes.append(f"reduced n_envs to {reduced_envs} due to memory/disk pressure")
        elif reduced_batch != hp.batch_size:
            next_hp = replace(next_hp, batch_size=reduced_batch)
            changes.append(f"reduced batch_size to {reduced_batch} due to memory/disk pressure")
    elif cpu_hot or slow:
        reduced_envs = max(1, hp.n_envs - 1) if config.allow_env_adaptation else hp.n_envs
        if reduced_envs != hp.n_envs:
            next_hp = replace(next_hp, n_envs=reduced_envs)
            changes.append(f"reduced n_envs to {reduced_envs} due to CPU pressure or low throughput")
    elif config.allow_env_adaptation and cpu_cold and not memory_hot and hp.n_envs < hp.max_envs:
        increased_envs = hp.n_envs + 1
        next_batch = min(max(hp.batch_size, 64), hp.n_steps * increased_envs)
        next_hp = replace(next_hp, n_envs=increased_envs, batch_size=next_batch)
        changes.append(f"increased n_envs to {increased_envs} because CPU has headroom")

    if next_hp.batch_size > next_hp.n_steps * next_hp.n_envs:
        next_hp = replace(next_hp, batch_size=max(16, next_hp.n_steps * next_hp.n_envs))
        changes.append(f"clamped batch_size to {next_hp.batch_size}")
    return next_hp, changes


def summary_objective_met(summary: dict[str, Any], phase: PhaseName, config: SupervisorConfig) -> bool:
    behavior = summary.get("behavior", {})
    winner = summary.get("winner")
    event_counts = behavior.get("event_counts", {})
    planted_seen = bool(behavior.get("bomb_planted")) or str(summary.get("bomb_state", "")).startswith("planted_")
    if config.learner_side == "T":
        if phase == "A":
            return planted_seen
        return winner == "T" or planted_seen
    if phase == "A":
        return winner == "CT" or bool(event_counts.get("bomb-defused", 0))
    return winner == "CT"


def summary_preplant_death(summary: dict[str, Any], config: SupervisorConfig) -> bool:
    if config.learner_side != "T":
        return False
    return str(summary.get("terminal_reason", "")).startswith("t-eliminated-before-plant")


def evaluate_model(model: Any, episodes: int, seed: int, phase: PhaseName, config: SupervisorConfig, max_decisions: int) -> EvalSummary:
    started_at = time.time()
    wins = 0
    terminal_count = 0
    plant_count = 0
    defuse_count = 0
    timeout_count = 0
    passed_count = 0
    objective_count = 0
    preplant_death_count = 0
    no_plant_count = 0
    objective_spam_count = 0
    plant_interrupt_count = 0
    postplant_defuse_loss_count = 0
    visible_no_shot_count = 0
    total_reward = 0.0
    total_seconds = 0.0
    aim_quality = 0.0
    attempted = 0
    for index in range(episodes):
        if time.time() - started_at >= config.eval_wall_seconds:
            break
        attempted += 1
        env = Dust2PrimitiveEnv(
            scenario=Dust2Scenario(
                seed=seed + index,
                spawn_mode=spawn_mode_for_phase(config, phase),
                learner_side=config.learner_side,  # type: ignore[arg-type]
                opponent_side="CT" if config.learner_side == "T" else "T",  # type: ignore[arg-type]
                frame_stride=10,
            ),
            reward_config=reward_config_for_phase(phase),
        )
        obs, _ = env.reset(seed=seed + index)
        lstm_state = None
        episode_start = np.ones((1,), dtype=bool)
        episode_reward = 0.0
        for _ in range(max_decisions):
            if time.time() - started_at >= config.eval_wall_seconds:
                break
            action, lstm_state = model.predict(obs, state=lstm_state, episode_start=episode_start, deterministic=True)
            obs, reward, terminated, truncated, _ = env.step(action)
            episode_reward += reward
            done = terminated or truncated
            episode_start = np.asarray([done], dtype=bool)
            if done:
                break
        trace = env.trace_payload()
        summary = trace["summary"]
        behavior = summary["behavior"]
        terminal_winner = summary.get("winner")
        terminal_reason = str(summary.get("terminal_reason", ""))
        wins += 1 if terminal_winner == config.learner_side else 0
        terminal_count += 1 if terminal_winner in {"T", "CT"} else 0
        planted_seen = bool(behavior.get("bomb_planted")) or str(summary.get("bomb_state", "")).startswith("planted_")
        plant_count += 1 if planted_seen else 0
        defuse_count += 1 if behavior.get("event_counts", {}).get("bomb-defused", 0) else 0
        timeout_count += 1 if "timeout" in terminal_reason else 0
        passed_count += 1 if behavior.get("passed") else 0
        objective_count += 1 if summary_objective_met(summary, phase, config) else 0
        preplant_death_count += 1 if summary_preplant_death(summary, config) else 0
        event_counts = behavior.get("event_counts", {})
        plant_attempts = behavior.get("plant_attempts", [])
        no_plant_count += 1 if not planted_seen else 0
        objective_spam_count += 1 if int(behavior.get("objective_spam_ticks", 0)) > 0 else 0
        plant_interrupt_count += 1 if len(plant_attempts) > 1 else 0
        postplant_defuse_loss_count += 1 if planted_seen and terminal_reason == "bomb-defused" else 0
        visible_no_shot_count += 1 if int(event_counts.get("visible", 0)) >= 12 and int(event_counts.get("shot", 0)) == 0 else 0
        total_reward += episode_reward
        total_seconds += float(summary.get("terminal_seconds", 0.0))
        aim_quality += float(behavior.get("aim_quality_ratio", 0.0))
    denom = max(1, attempted)
    win_rate = wins / denom
    terminal_rate = terminal_count / denom
    plant_rate = plant_count / denom
    defuse_rate = defuse_count / denom
    timeout_no_plant_rate = timeout_count / denom
    passed_rate = passed_count / denom
    objective_rate = objective_count / denom
    objective_miss_rate = 1.0 - objective_rate
    preplant_death_rate = preplant_death_count / denom
    no_plant_rate = no_plant_count / denom
    objective_spam_rate = objective_spam_count / denom
    plant_interrupt_rate = plant_interrupt_count / denom
    postplant_defuse_loss_rate = postplant_defuse_loss_count / denom
    visible_no_shot_rate = visible_no_shot_count / denom
    aim_quality_mean = aim_quality / denom
    if phase == "A":
        behavior_score = (
            0.60 * objective_rate
            + 0.12 * terminal_rate
            + 0.12 * passed_rate
            + 0.12 * aim_quality_mean
            + 0.04 * win_rate
            - 0.30 * preplant_death_rate
            - 0.30 * objective_miss_rate
            - 0.20 * objective_spam_rate
            - 0.20 * plant_interrupt_rate
            - 0.10 * timeout_no_plant_rate
            - 0.10 * visible_no_shot_rate
        )
    else:
        behavior_score = (
            0.25 * win_rate
            + 0.45 * objective_rate
            + 0.10 * terminal_rate
            + 0.10 * passed_rate
            + 0.10 * aim_quality_mean
            - 0.20 * timeout_no_plant_rate
            - 0.40 * preplant_death_rate
            - 0.25 * objective_miss_rate
            - 0.20 * objective_spam_rate
            - 0.15 * plant_interrupt_rate
            - 0.30 * postplant_defuse_loss_rate
            - 0.15 * visible_no_shot_rate
        )
    return EvalSummary(
        episodes=attempted,
        win_rate=win_rate,
        terminal_rate=terminal_rate,
        plant_rate=plant_rate,
        defuse_rate=defuse_rate,
        timeout_no_plant_rate=timeout_no_plant_rate,
        avg_reward=total_reward / denom,
        avg_seconds=total_seconds / denom,
        aim_quality_mean=aim_quality_mean,
        passed_rate=passed_rate,
        objective_rate=objective_rate,
        objective_miss_rate=objective_miss_rate,
        preplant_death_rate=preplant_death_rate,
        no_plant_rate=no_plant_rate,
        objective_spam_rate=objective_spam_rate,
        plant_interrupt_rate=plant_interrupt_rate,
        postplant_defuse_loss_rate=postplant_defuse_loss_rate,
        visible_no_shot_rate=visible_no_shot_rate,
        behavior_score=behavior_score,
    )


def run_policy_episode_trace(model: Any, seed: int, phase: PhaseName, config: SupervisorConfig, max_decisions: int, started_at: float) -> dict[str, Any]:
    env = Dust2PrimitiveEnv(
        scenario=Dust2Scenario(
            seed=seed,
            spawn_mode=spawn_mode_for_phase(config, phase),
            learner_side=config.learner_side,  # type: ignore[arg-type]
            opponent_side="CT" if config.learner_side == "T" else "T",  # type: ignore[arg-type]
            frame_stride=10,
        ),
        reward_config=reward_config_for_phase(phase),
    )
    obs, _ = env.reset(seed=seed)
    lstm_state = None
    episode_start = np.ones((1,), dtype=bool)
    for _ in range(max_decisions):
        if time.time() - started_at >= config.trace_wall_seconds:
            break
        action, lstm_state = model.predict(obs, state=lstm_state, episode_start=episode_start, deterministic=True)
        obs, _, terminated, truncated, _ = env.step(action)
        done = terminated or truncated
        episode_start = np.asarray([done], dtype=bool)
        if done:
            break
    return env.trace_payload()


def export_policy_trace(model: Any, out: Path, seed: int, phase: PhaseName, config: SupervisorConfig, max_decisions: int) -> dict[str, Any]:
    started_at = time.time()
    traces: list[dict[str, Any]] = []
    for index in range(max(1, config.trace_episodes)):
        if time.time() - started_at >= config.trace_wall_seconds:
            break
        traces.append(run_policy_episode_trace(model, seed + index, phase, config, max_decisions, started_at))
    if not traces:
        traces.append(run_policy_episode_trace(model, seed, phase, config, max_decisions, started_at))
    summaries = [trace["summary"] for trace in traces]
    objective_successes = [summary_objective_met(summary, phase, config) for summary in summaries]
    preplant_deaths = [summary_preplant_death(summary, config) for summary in summaries]
    primary_index = next((idx for idx, ok in enumerate(objective_successes) if not ok), 0)
    payload = traces[primary_index]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    batch_path = out.with_name(f"{out.stem}-batch.json")
    batch_path.write_text(
        json.dumps(
            {
                "kind": "dust2-rl-policy-trace-batch",
                "phase": phase,
                "learnerSide": config.learner_side,
                "primaryTrace": str(out),
                "episodes": traces,
                "summaries": summaries,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    denom = max(1, len(summaries))
    winner_counts: dict[str, int] = {}
    terminal_reason_counts: dict[str, int] = {}
    for summary in summaries:
        winner = str(summary.get("winner"))
        reason = str(summary.get("terminal_reason"))
        winner_counts[winner] = winner_counts.get(winner, 0) + 1
        terminal_reason_counts[reason] = terminal_reason_counts.get(reason, 0) + 1
    return {
        **payload["summary"],
        "traceEpisodes": len(summaries),
        "objectiveRate": sum(1 for ok in objective_successes if ok) / denom,
        "preplantDeathRate": sum(1 for row in preplant_deaths if row) / denom,
        "primaryObjectiveMet": objective_successes[primary_index],
        "primaryTrace": str(out),
        "batchTrace": str(batch_path),
        "winnerCounts": winner_counts,
        "terminalReasonCounts": terminal_reason_counts,
    }


def prune_checkpoints(run_dir: Path, cap_gb: float, keep_recent: int, keep_best: int, eval_rows: list[dict[str, Any]]) -> list[str]:
    checkpoints_dir = run_dir / "checkpoints"
    files = sorted(checkpoints_dir.glob("*.zip"), key=lambda path: path.stat().st_mtime)
    cap_bytes = int(cap_gb * 1024**3)
    keep: set[Path] = set(files[-keep_recent:])
    ranked = sorted(
        (row for row in eval_rows if row.get("checkpoint")),
        key=lambda row: float(row.get("behavior_score", -999.0)),
        reverse=True,
    )
    for row in ranked[:keep_best]:
        keep.add(Path(str(row["checkpoint"])))
    deleted: list[str] = []
    while total_size(files) > cap_bytes:
        victim = next((path for path in files if path not in keep and path.exists()), None)
        if victim is None:
            break
        victim.unlink()
        deleted.append(str(victim))
        files = [path for path in files if path.exists()]
    return deleted


def write_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def bytes_to_gb(value: int) -> float:
    return round(value / 1024**3, 3)


def total_size(paths: list[Path]) -> int:
    return sum(path.stat().st_size for path in paths if path.exists())


def phase_sequence(args: argparse.Namespace) -> list[tuple[PhaseName, int]]:
    if args.phase == "A":
        return [("A", args.phase_a_steps)]
    if args.phase == "B":
        return [("B", args.phase_b_steps)]
    return [("A", args.phase_a_steps), ("B", args.phase_b_steps)]


def build_config(args: argparse.Namespace) -> SupervisorConfig:
    return SupervisorConfig(
        seed=args.seed,
        run_dir=args.run_dir,
        checkpoint_cap_gb=args.checkpoint_cap_gb,
        keep_recent_checkpoints=args.keep_recent_checkpoints,
        keep_best_checkpoints=args.keep_best_checkpoints,
        phase_a_steps=args.phase_a_steps,
        phase_b_steps=args.phase_b_steps,
        max_wall_seconds=args.max_wall_seconds,
        chunk_steps=args.chunk_steps,
        eval_episodes=args.eval_episodes,
        eval_max_decisions=args.eval_max_decisions,
        eval_wall_seconds=args.eval_wall_seconds,
        trace_wall_seconds=args.trace_wall_seconds,
        trace_episodes=args.trace_episodes,
        save_every_chunks=args.save_every_chunks,
        eval_every_chunks=args.eval_every_chunks,
        trace_every_chunks=args.trace_every_chunks,
        learner_side=args.learner_side,
        spawn_mode=args.spawn_mode,
        phase_a_spawn_mode=args.phase_a_spawn_mode,
        phase_b_spawn_mode=args.phase_b_spawn_mode,
        device=args.device,
        cpu_high_pct=args.cpu_high_pct,
        cpu_low_pct=args.cpu_low_pct,
        memory_high_pct=args.memory_high_pct,
        disk_free_low_gb=args.disk_free_low_gb,
        min_steps_per_second=args.min_steps_per_second,
        allow_env_adaptation=args.allow_env_adaptation,
        convergence_patience_evals=args.convergence_patience_evals,
        convergence_min_delta=args.convergence_min_delta,
        convergence_min_behavior_score=args.convergence_min_behavior_score,
        convergence_min_objective_rate=args.convergence_min_objective_rate,
        convergence_min_win_rate=args.convergence_min_win_rate,
        convergence_max_objective_spam_rate=args.convergence_max_objective_spam_rate,
        convergence_max_plant_interrupt_rate=args.convergence_max_plant_interrupt_rate,
        convergence_max_no_plant_rate=args.convergence_max_no_plant_rate,
        convergence_max_postplant_defuse_loss_rate=args.convergence_max_postplant_defuse_loss_rate,
        min_phase_eval_rounds=args.min_phase_eval_rounds,
        min_phase_chunks=args.min_phase_chunks,
        load_checkpoint=args.load_checkpoint,
    )


def build_hyperparams(args: argparse.Namespace) -> TrainHyperparams:
    return TrainHyperparams(
        n_envs=args.n_envs,
        max_envs=args.max_envs,
        n_steps=args.n_steps,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        gamma=args.gamma,
        gae_lambda=args.gae_lambda,
        clip_range=args.clip_range,
        ent_coef=args.ent_coef,
        vf_coef=args.vf_coef,
        max_grad_norm=args.max_grad_norm,
        lstm_hidden_size=args.lstm_hidden_size,
        n_lstm_layers=args.n_lstm_layers,
        mlp_width=args.mlp_width,
    )


def plan_payload(args: argparse.Namespace) -> dict[str, Any]:
    config = build_config(args)
    hp = build_hyperparams(args)
    return {
        "status": "planned",
        "formalTrainingStarted": False,
        "runDir": config.run_dir,
        "phases": [
            {"phase": phase, "steps": steps, "spawnMode": spawn_mode_for_phase(config, phase)}
            for phase, steps in phase_sequence(args)
        ],
        "hyperparams": asdict(hp),
        "supervisor": asdict(config),
        "maxWallSecondsPerPhase": config.max_wall_seconds,
        "resourceAdaptation": {
            "enabled": True,
            "canChange": (["n_envs"] if config.allow_env_adaptation else [])
            + ["batch_size", "checkpoint pruning", "eval/trace frequency in future extension"],
            "willNotChangeOnline": ["observation_space", "action_space", "lstm architecture", "reward main definition"],
        },
    }


def run_plan(args: argparse.Namespace) -> None:
    print(json.dumps(plan_payload(args), indent=2, sort_keys=True))


def run_dry_run(args: argparse.Namespace) -> None:
    config = build_config(args)
    hp = build_hyperparams(args)
    run_dir = Path(config.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    env = Dust2PrimitiveEnv(
        scenario=Dust2Scenario(
            seed=config.seed,
            spawn_mode=spawn_mode_for_phase(config, "A"),
            learner_side=config.learner_side,  # type: ignore[arg-type]
        ),
        reward_config=reward_config_for_phase("A"),
    )
    if args.full_check_env:
        from stable_baselines3.common.env_checker import check_env

        check_env(env, warn=True, skip_render_check=True)
    else:
        obs, _ = env.reset(seed=config.seed)
        env.step(env.action_space.sample())
    vec_env = make_vec_env(config.seed, "A", config, hp)
    model = make_model(vec_env, hp, config)
    obs = vec_env.reset()
    action, lstm_state = model.predict(obs, deterministic=False)
    obs, rewards, dones, infos = vec_env.step(action)
    eval_summary = (
        evaluate_model(
            model,
            max(1, min(2, config.eval_episodes)),
            config.seed + 10_000,
            "A",
            config,
            max_decisions=min(25, config.eval_max_decisions),
        )
        if args.with_eval
        else None
    )
    resources = sample_resources(run_dir)
    payload = {
        "status": "dry-run-ok",
        "formalTrainingStarted": False,
        "eval": asdict(eval_summary) if eval_summary else None,
        "sampleStep": {
            "rewardMean": round(float(np.mean(rewards)), 6),
            "doneAny": bool(np.any(dones)),
            "infoKeys": sorted(set(key for info in infos for key in info.keys())),
            "lstmStateReady": lstm_state is not None,
        },
        "resources": asdict(resources),
        "hyperparams": asdict(hp),
        "runDir": str(run_dir),
    }
    write_json(run_dir / "dry_run.json", payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    vec_env.close()


def run_eval_checkpoint(args: argparse.Namespace) -> None:
    if args.phase == "AB":
        raise SystemExit("eval-checkpoint requires --phase A or --phase B.")
    config = build_config(args)
    hp = build_hyperparams(args)
    if not config.load_checkpoint:
        raise SystemExit("eval-checkpoint requires --load-checkpoint.")
    phase: PhaseName = args.phase
    run_dir = Path(config.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    vec_env = make_vec_env(config.seed, phase, config, hp)
    try:
        model = load_model(config.load_checkpoint, vec_env, hp, config)
        model.verbose = 0
        eval_summary = evaluate_model(
            model,
            config.eval_episodes,
            config.seed + 100_000,
            phase,
            config,
            max_decisions=config.eval_max_decisions,
        )
        trace_summary = None
        if args.trace_out:
            trace_summary = export_policy_trace(
                model,
                Path(args.trace_out),
                config.seed + 200_000,
                phase,
                config,
                max_decisions=config.eval_max_decisions,
            )
        payload = {
            "status": "eval-ok",
            "formalTrainingStarted": False,
            "checkpoint": config.load_checkpoint,
            "phase": phase,
            "spawnMode": spawn_mode_for_phase(config, phase),
            "eval": asdict(eval_summary),
            "trace": trace_summary,
            "hyperparams": asdict(hp),
            "supervisor": asdict(config),
        }
        out_path = Path(args.out) if args.out else run_dir / "eval_checkpoint.json"
        write_json(out_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        vec_env.close()


def parse_candidate_spec(spec: str) -> tuple[str, PhaseName, str]:
    if "=" in spec:
        name, rest = spec.split("=", 1)
        name = name.strip()
    else:
        rest = spec
        name = Path(rest.rsplit(":", 1)[-1]).stem
    if ":" not in rest:
        raise ValueError(f"candidate must be name=PHASE:path or PHASE:path: {spec}")
    phase_text, path = rest.split(":", 1)
    phase_text = phase_text.strip().upper()
    if phase_text not in {"A", "B"}:
        raise ValueError(f"candidate phase must be A or B: {spec}")
    if not name:
        raise ValueError(f"candidate name cannot be empty: {spec}")
    return name, phase_text, path.strip()  # type: ignore[return-value]


def suite_spawn_modes(args: argparse.Namespace, phase: PhaseName) -> list[str]:
    if phase == "A":
        return args.phase_a_suite_spawn_mode or ["plant_curriculum"]
    return args.phase_b_suite_spawn_mode or ["clutch_like", "plant_curriculum", "postplant_curriculum", "mixed_curriculum"]


def config_for_suite_row(config: SupervisorConfig, phase: PhaseName, spawn_mode: str, seed: int) -> SupervisorConfig:
    if phase == "A":
        return replace(config, seed=seed, phase_a_spawn_mode=spawn_mode)
    return replace(config, seed=seed, phase_b_spawn_mode=spawn_mode)


def suite_seeds(args: argparse.Namespace, config: SupervisorConfig) -> list[int]:
    explicit = [int(seed) for seed in (args.suite_seed or [])]
    if explicit:
        return explicit
    return [config.seed + index * args.suite_seed_stride for index in range(max(1, args.suite_seed_count))]


def suite_failures(row: dict[str, Any], args: argparse.Namespace) -> list[str]:
    failures: list[str] = []
    spawn_mode = str(row["spawnMode"])
    if row["objective_rate"] < args.suite_min_objective_rate:
        failures.append("low-objective")
    if row["behavior_score"] < args.suite_min_behavior_score:
        failures.append("low-behavior")
    if row["phase"] == "A" and row["no_plant_rate"] > args.suite_max_no_plant_rate:
        failures.append("no-plant")
    if row["phase"] == "B" and row["win_rate"] < args.suite_min_win_rate:
        failures.append("low-win")
    if spawn_mode == "postplant_curriculum" and row["postplant_defuse_loss_rate"] > args.suite_max_postplant_defuse_loss_rate:
        failures.append("postplant-defuse-loss")
    return failures


def summarize_suite_candidate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    denom = max(1, len(rows))

    def mean(key: str) -> float:
        return sum(float(row[key]) for row in rows) / denom

    failed_rows = [row for row in rows if row["failures"]]
    return {
        "candidate": rows[0]["candidate"] if rows else "-",
        "phase": rows[0]["phase"] if rows else "-",
        "rows": len(rows),
        "passed": not failed_rows,
        "failedRows": len(failed_rows),
        "meanBehaviorScore": mean("behavior_score"),
        "meanWinRate": mean("win_rate"),
        "meanObjectiveRate": mean("objective_rate"),
        "meanNoPlantRate": mean("no_plant_rate"),
        "meanPostplantDefuseLossRate": mean("postplant_defuse_loss_rate"),
        "minBehaviorScore": min(float(row["behavior_score"]) for row in rows) if rows else 0.0,
        "maxPostplantDefuseLossRate": max(float(row["postplant_defuse_loss_rate"]) for row in rows) if rows else 0.0,
        "failures": sorted({failure for row in rows for failure in row["failures"]}),
    }


def rank_suite_summaries(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        summaries,
        key=lambda row: (
            bool(row["passed"]),
            float(row["meanBehaviorScore"]),
            float(row["meanWinRate"]),
            -float(row["meanPostplantDefuseLossRate"]),
        ),
        reverse=True,
    )


def run_eval_suite(args: argparse.Namespace) -> None:
    config = build_config(args)
    hp = build_hyperparams(args)
    run_dir = Path(config.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    candidates = [parse_candidate_spec(spec) for spec in args.candidate]
    all_rows: list[dict[str, Any]] = []
    candidate_summaries: list[dict[str, Any]] = []
    for name, phase, checkpoint_path in candidates:
        vec_env = make_vec_env(config.seed, phase, config, hp)
        try:
            model = load_model(checkpoint_path, vec_env, hp, config)
            model.verbose = 0
            candidate_rows: list[dict[str, Any]] = []
            for spawn_mode in suite_spawn_modes(args, phase):
                for row_seed in suite_seeds(args, config):
                    row_config = config_for_suite_row(config, phase, spawn_mode, row_seed)
                    eval_summary = evaluate_model(
                        model,
                        config.eval_episodes,
                        row_seed + 100_000,
                        phase,
                        row_config,
                        max_decisions=config.eval_max_decisions,
                    )
                    row = {
                        "candidate": name,
                        "phase": phase,
                        "checkpoint": checkpoint_path,
                        "spawnMode": spawn_mode,
                        "seed": row_seed,
                        **asdict(eval_summary),
                    }
                    row["failures"] = suite_failures(row, args)
                    candidate_rows.append(row)
                    all_rows.append(row)
                    write_jsonl(run_dir / "eval_suite_rows.jsonl", row)
            candidate_summaries.append(summarize_suite_candidate(candidate_rows))
        finally:
            vec_env.close()
    ranked = rank_suite_summaries(candidate_summaries)
    payload = {
        "status": "eval-suite-ok",
        "formalTrainingStarted": False,
        "runDir": str(run_dir),
        "thresholds": {
            "minBehaviorScore": args.suite_min_behavior_score,
            "minObjectiveRate": args.suite_min_objective_rate,
            "minWinRate": args.suite_min_win_rate,
            "maxNoPlantRate": args.suite_max_no_plant_rate,
            "maxPostplantDefuseLossRate": args.suite_max_postplant_defuse_loss_rate,
        },
        "candidateSummaries": candidate_summaries,
        "rankedCandidates": ranked,
        "bestCandidate": ranked[0] if ranked else None,
        "rows": all_rows,
        "hyperparams": asdict(hp),
        "supervisor": asdict(config),
    }
    out_path = Path(args.out) if args.out else run_dir / "eval_suite.json"
    write_json(out_path, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


def run_train(args: argparse.Namespace) -> None:
    if not args.confirm_train:
        raise SystemExit("Refusing to start training without --confirm-train. Use plan or dry-run first.")
    config = build_config(args)
    hp = build_hyperparams(args)
    run_dir = Path(config.run_dir)
    checkpoints_dir = run_dir / "checkpoints"
    traces_dir = run_dir / "traces"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "manifest.json", {
        "status": "training-started",
        "startedAt": time.time(),
        "plan": plan_payload(args),
    })
    started_at = time.time()
    stop_reason = "phase-step-budget-complete"
    eval_rows: list[dict[str, Any]] = []
    model = None
    vec_env = None
    chunk_index = 0
    global_steps = 0
    current_hp = hp
    phase_stop_reasons: list[dict[str, Any]] = []
    for phase, phase_steps in phase_sequence(args):
        phase_started_at = time.time()
        if vec_env is not None:
            vec_env.close()
            vec_env = make_vec_env(config.seed + global_steps, phase, config, current_hp)
            if model is not None:
                model.set_env(vec_env)
        remaining = phase_steps
        phase_best_score = -float("inf")
        phase_best_objective_rate = 0.0
        phase_best_win_rate = 0.0
        phase_stale_evals = 0
        phase_eval_rounds = 0
        phase_chunks = 0
        last_eval_summary: EvalSummary | None = None
        while remaining > 0:
            if time.time() - phase_started_at >= config.max_wall_seconds:
                phase_reason = f"phase-{phase.lower()}-max-wall-seconds"
                phase_stop_reasons.append({
                    "phase": phase,
                    "reason": phase_reason,
                    "evalRounds": phase_eval_rounds,
                    "chunks": phase_chunks,
                    "bestBehaviorScore": phase_best_score if phase_best_score != -float("inf") else None,
                    "bestObjectiveRate": phase_best_objective_rate,
                    "bestWinRate": phase_best_win_rate,
                })
                if phase == "B":
                    stop_reason = phase_reason
                remaining = 0
                break
            chunk_index += 1
            phase_chunks += 1
            chunk_steps = min(config.chunk_steps, remaining)
            if vec_env is None:
                vec_env = make_vec_env(config.seed + global_steps, phase, config, current_hp)
            if model is None:
                if config.load_checkpoint:
                    model = load_model(config.load_checkpoint, vec_env, current_hp, config)
                    model.verbose = 1
                else:
                    model = make_model(vec_env, current_hp, config)
            start = time.time()
            model.learn(total_timesteps=chunk_steps, reset_num_timesteps=False, progress_bar=False)
            elapsed = max(time.time() - start, 1e-6)
            steps_per_second = chunk_steps / elapsed
            global_steps += chunk_steps
            remaining -= chunk_steps
            checkpoint = checkpoints_dir / f"{phase.lower()}-chunk-{chunk_index:05d}-steps-{global_steps}.zip"
            if chunk_index % config.save_every_chunks == 0:
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                model.save(checkpoint)
            eval_summary = None
            trace_summary = None
            if chunk_index % config.eval_every_chunks == 0:
                eval_summary = evaluate_model(
                    model,
                    config.eval_episodes,
                    config.seed + 100_000 + chunk_index * 100,
                    phase,
                    config,
                    max_decisions=config.eval_max_decisions,
                )
                eval_row = {
                    "chunk": chunk_index,
                    "phase": phase,
                    "steps": global_steps,
                    "checkpoint": str(checkpoint) if checkpoint.exists() else None,
                    **asdict(eval_summary),
                }
                eval_rows.append(eval_row)
                write_jsonl(run_dir / "eval.jsonl", eval_row)
                phase_eval_rounds += 1
                last_eval_summary = eval_summary
                phase_best_objective_rate = max(phase_best_objective_rate, eval_summary.objective_rate)
                phase_best_win_rate = max(phase_best_win_rate, eval_summary.win_rate)
                if eval_summary.behavior_score > phase_best_score + config.convergence_min_delta:
                    phase_best_score = eval_summary.behavior_score
                    phase_stale_evals = 0
                else:
                    phase_stale_evals += 1
            if chunk_index % config.trace_every_chunks == 0:
                trace_path = traces_dir / f"{phase.lower()}-chunk-{chunk_index:05d}.json"
                trace_summary = export_policy_trace(
                    model,
                    trace_path,
                    config.seed + 200_000 + chunk_index,
                    phase,
                    config,
                    max_decisions=config.eval_max_decisions,
                )
            resources = sample_resources(run_dir)
            pruned = prune_checkpoints(
                run_dir,
                config.checkpoint_cap_gb,
                config.keep_recent_checkpoints,
                config.keep_best_checkpoints,
                eval_rows,
            )
            next_hp, changes = adapt_hyperparams(current_hp, resources, config, steps_per_second)
            row = {
                "chunk": chunk_index,
                "phase": phase,
                "steps": global_steps,
                "chunkSteps": chunk_steps,
                "phaseChunks": phase_chunks,
                "phaseEvalRounds": phase_eval_rounds,
                "phaseBestBehaviorScore": round(phase_best_score, 6) if phase_best_score != -float("inf") else None,
                "phaseBestObjectiveRate": round(phase_best_objective_rate, 6),
                "phaseBestWinRate": round(phase_best_win_rate, 6),
                "phaseStaleEvals": phase_stale_evals,
                "elapsedSeconds": round(elapsed, 3),
                "phaseElapsedSeconds": round(time.time() - phase_started_at, 3),
                "wallElapsedSeconds": round(time.time() - started_at, 3),
                "stepsPerSecond": round(steps_per_second, 4),
                "hyperparams": asdict(current_hp),
                "nextHyperparams": asdict(next_hp),
                "adaptation": changes,
                "resources": asdict(resources),
                "eval": asdict(eval_summary) if eval_summary else None,
                "trace": trace_summary,
                "prunedCheckpoints": pruned,
            }
            write_jsonl(run_dir / "train_log.jsonl", row)
            phase_converged = (
                last_eval_summary is not None
                and phase_eval_rounds >= config.min_phase_eval_rounds
                and phase_chunks >= config.min_phase_chunks
                and phase_stale_evals >= config.convergence_patience_evals
                and phase_best_score >= config.convergence_min_behavior_score
                and phase_best_objective_rate >= config.convergence_min_objective_rate
                and (phase != "B" or phase_best_win_rate >= config.convergence_min_win_rate)
                and last_eval_summary.objective_spam_rate <= config.convergence_max_objective_spam_rate
                and last_eval_summary.plant_interrupt_rate <= config.convergence_max_plant_interrupt_rate
                and last_eval_summary.no_plant_rate <= config.convergence_max_no_plant_rate
                and last_eval_summary.postplant_defuse_loss_rate <= config.convergence_max_postplant_defuse_loss_rate
            )
            if phase_converged:
                phase_reason = f"phase-{phase.lower()}-converged"
                phase_stop_reasons.append({
                    "phase": phase,
                    "reason": phase_reason,
                    "evalRounds": phase_eval_rounds,
                    "chunks": phase_chunks,
                    "bestBehaviorScore": phase_best_score,
                    "bestObjectiveRate": phase_best_objective_rate,
                    "bestWinRate": phase_best_win_rate,
                })
                stop_reason = phase_reason if phase == "B" else stop_reason
                break
            if next_hp != current_hp:
                current_hp = next_hp
                if vec_env is not None:
                    vec_env.close()
                vec_env = make_vec_env(config.seed + global_steps, phase, config, current_hp)
                model = rebuild_model_with_policy_state(model, vec_env, current_hp, config)
        if stop_reason == f"phase-{phase.lower()}-max-wall-seconds":
            break
    if model is not None:
        final_path = checkpoints_dir / "final_model.zip"
        final_path.parent.mkdir(parents=True, exist_ok=True)
        model.save(final_path)
    if vec_env is not None:
        vec_env.close()
    write_json(run_dir / "complete.json", {
        "status": "complete",
        "finishedAt": time.time(),
        "stopReason": stop_reason,
        "phaseStopReasons": phase_stop_reasons,
        "steps": global_steps,
        "checkpointCapGb": config.checkpoint_cap_gb,
    })
    print(json.dumps({"status": "complete", "runDir": str(run_dir), "steps": global_steps, "stopReason": stop_reason, "phaseStopReasons": phase_stop_reasons}, indent=2, sort_keys=True))


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--phase", choices=["A", "B", "AB"], default="AB")
    parser.add_argument("--seed", type=int, default=2607)
    parser.add_argument("--run-dir", default=".solo-clutch-runs/dust2-rl-training")
    parser.add_argument("--checkpoint-cap-gb", type=float, default=10.0)
    parser.add_argument("--keep-recent-checkpoints", type=int, default=5)
    parser.add_argument("--keep-best-checkpoints", type=int, default=3)
    parser.add_argument("--phase-a-steps", type=int, default=2_000_000)
    parser.add_argument("--phase-b-steps", type=int, default=4_000_000)
    parser.add_argument("--max-wall-seconds", type=int, default=21_600)
    parser.add_argument("--chunk-steps", type=int, default=8_192)
    parser.add_argument("--eval-episodes", type=int, default=8)
    parser.add_argument("--eval-max-decisions", type=int, default=900)
    parser.add_argument("--eval-wall-seconds", type=float, default=120.0)
    parser.add_argument("--trace-wall-seconds", type=float, default=60.0)
    parser.add_argument("--trace-episodes", type=int, default=2)
    parser.add_argument("--save-every-chunks", type=int, default=1)
    parser.add_argument("--eval-every-chunks", type=int, default=1)
    parser.add_argument("--trace-every-chunks", type=int, default=2)
    parser.add_argument("--learner-side", choices=["T", "CT"], default="T")
    parser.add_argument("--spawn-mode", choices=SPAWN_MODES, default="clutch_like")
    parser.add_argument("--phase-a-spawn-mode", choices=SPAWN_MODES, default="plant_curriculum")
    parser.add_argument("--phase-b-spawn-mode", choices=SPAWN_MODES, default="clutch_like")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--cpu-high-pct", type=float, default=92.0)
    parser.add_argument("--cpu-low-pct", type=float, default=55.0)
    parser.add_argument("--memory-high-pct", type=float, default=88.0)
    parser.add_argument("--disk-free-low-gb", type=float, default=20.0)
    parser.add_argument("--min-steps-per-second", type=float, default=1.0)
    parser.add_argument("--allow-env-adaptation", action="store_true")
    parser.add_argument("--n-envs", type=int, default=2)
    parser.add_argument("--max-envs", type=int, default=6)
    parser.add_argument("--n-steps", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=2.5e-4)
    parser.add_argument("--gamma", type=float, default=0.995)
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--clip-range", type=float, default=0.2)
    parser.add_argument("--ent-coef", type=float, default=0.01)
    parser.add_argument("--vf-coef", type=float, default=0.5)
    parser.add_argument("--max-grad-norm", type=float, default=0.5)
    parser.add_argument("--lstm-hidden-size", type=int, default=256)
    parser.add_argument("--n-lstm-layers", type=int, default=1)
    parser.add_argument("--mlp-width", type=int, default=64)
    parser.add_argument("--convergence-patience-evals", type=int, default=5)
    parser.add_argument("--convergence-min-delta", type=float, default=0.015)
    parser.add_argument("--convergence-min-behavior-score", type=float, default=0.65)
    parser.add_argument("--convergence-min-objective-rate", type=float, default=0.75)
    parser.add_argument("--convergence-min-win-rate", type=float, default=0.0)
    parser.add_argument("--convergence-max-objective-spam-rate", type=float, default=0.25)
    parser.add_argument("--convergence-max-plant-interrupt-rate", type=float, default=0.40)
    parser.add_argument("--convergence-max-no-plant-rate", type=float, default=0.35)
    parser.add_argument("--convergence-max-postplant-defuse-loss-rate", type=float, default=0.70)
    parser.add_argument("--min-phase-eval-rounds", type=int, default=4)
    parser.add_argument("--min-phase-chunks", type=int, default=4)
    parser.add_argument("--load-checkpoint", default=None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dust2 RL training supervisor with resource-aware chunking.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Print the planned training configuration without training.")
    add_common_args(plan_parser)
    plan_parser.set_defaults(func=run_plan)

    dry_parser = subparsers.add_parser("dry-run", help="Validate env/model/eval/resource monitoring without training.")
    add_common_args(dry_parser)
    dry_parser.add_argument("--full-check-env", action="store_true")
    dry_parser.add_argument("--with-eval", action="store_true")
    dry_parser.set_defaults(func=run_dry_run)

    eval_parser = subparsers.add_parser("eval-checkpoint", help="Evaluate a saved checkpoint without training.")
    add_common_args(eval_parser)
    eval_parser.add_argument("--out", default=None, help="Optional path for the evaluation JSON payload.")
    eval_parser.add_argument("--trace-out", default=None, help="Optional trace JSON path to export while evaluating.")
    eval_parser.set_defaults(func=run_eval_checkpoint)

    suite_parser = subparsers.add_parser("eval-suite", help="Run a multi-scenario failure suite over saved checkpoints.")
    add_common_args(suite_parser)
    suite_parser.add_argument("--candidate", action="append", required=True, help="Candidate as name=PHASE:path or PHASE:path.")
    suite_parser.add_argument("--phase-a-suite-spawn-mode", action="append", choices=SPAWN_MODES, default=None)
    suite_parser.add_argument("--phase-b-suite-spawn-mode", action="append", choices=SPAWN_MODES, default=None)
    suite_parser.add_argument("--suite-seed", action="append", type=int, default=None, help="Explicit held-out seed. Can be repeated.")
    suite_parser.add_argument("--suite-seed-count", type=int, default=1)
    suite_parser.add_argument("--suite-seed-stride", type=int, default=10_000)
    suite_parser.add_argument("--suite-min-behavior-score", type=float, default=0.65)
    suite_parser.add_argument("--suite-min-objective-rate", type=float, default=0.90)
    suite_parser.add_argument("--suite-min-win-rate", type=float, default=0.40)
    suite_parser.add_argument("--suite-max-no-plant-rate", type=float, default=0.10)
    suite_parser.add_argument("--suite-max-postplant-defuse-loss-rate", type=float, default=0.60)
    suite_parser.add_argument("--out", default=None, help="Optional path for the suite JSON payload.")
    suite_parser.set_defaults(func=run_eval_suite)

    train_parser = subparsers.add_parser("train", help="Run chunked RecurrentPPO training.")
    add_common_args(train_parser)
    train_parser.add_argument("--confirm-train", action="store_true")
    train_parser.set_defaults(func=run_train)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
