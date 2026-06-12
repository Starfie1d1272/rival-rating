from __future__ import annotations

import argparse
from dataclasses import replace
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .dust2_mvp import Dust2Config, Visibility, load_dust2_map, map_payload, simulate_round


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RL_PHASE = "B"
RL_CHECKPOINTS = {
    "A": ".solo-clutch-runs/dust2-rl-ab-20260608-a-curriculum-v2/checkpoints/a-chunk-00020-steps-40960.zip",
    "B": ".solo-clutch-runs/dust2-rl-b-20260608-a20-plantguard-v2/checkpoints/b-chunk-00016-steps-32768.zip",
    "B_CANDIDATE": ".solo-clutch-runs/dust2-rl-b-20260608-terminal-mixed-v1/checkpoints/b-chunk-00002-steps-8192.zip",
}
PHASE_C_RUN_DIR = ".solo-clutch-runs/dust2-phase-c-20260612-v8"
PHASE_C_CHECKPOINTS = {
    "C_STABLE": {
        "T": f"{PHASE_C_RUN_DIR}/checkpoints/stable/phase-c-t-stable.zip",
        "CT": f"{PHASE_C_RUN_DIR}/checkpoints/stable/phase-c-ct-stable.zip",
    },
    "C_CANDIDATE": {
        "T": f"{PHASE_C_RUN_DIR}/checkpoints/t/latest/phase-c-t-latest.zip",
        "CT": f"{PHASE_C_RUN_DIR}/checkpoints/ct/latest/phase-c-ct-latest.zip",
    },
}
_MODEL_CACHE: dict[tuple[str, str, int, int], object] = {}


def display_checkpoint_path(checkpoint: Path) -> str:
    resolved = checkpoint.resolve()
    return str(
        resolved.relative_to(REPO_ROOT)
        if resolved.is_relative_to(REPO_ROOT)
        else resolved
    )


class ViewerRequestHandler(SimpleHTTPRequestHandler):
    def address_string(self) -> str:
        return self.client_address[0]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/trace":
            self.serve_trace(parsed.query)
            return
        if parsed.path == "/api/dust2-map":
            self.serve_json(map_payload(load_dust2_map()))
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/simulate":
            self.serve_simulation()
            return
        if parsed.path == "/api/rl-simulate":
            self.serve_rl_simulation()
            return
        self.send_error(404)

    def serve_trace(self, query: str) -> None:
        params = parse_qs(query)
        raw_path = params.get("path", [""])[0]
        try:
            candidate = (REPO_ROOT / raw_path).resolve()
            if not candidate.is_relative_to(REPO_ROOT) or candidate.suffix != ".json":
                raise ValueError("trace path must be a repo-local JSON file")
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.write_json_bytes(body)

    def serve_simulation(self) -> None:
        try:
            size = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(size) if size > 0 else b"{}"
            params = json.loads(raw.decode("utf-8"))
            dust2 = load_dust2_map()
            config = replace(
                Dust2Config(),
                round_seconds=float(params.get("roundSeconds", 40.0)),
                bomb_timer_seconds=float(params.get("bombTimerSeconds", 40.0)),
                tick_seconds=float(params.get("tickSeconds", 0.01)),
                p_hit_max=float(params.get("pHitMax", 0.9)),
                max_turn_deg_per_tick=float(params.get("maxTurnDegPerTick", 18.0)),
                max_pitch_turn_deg_per_tick=float(params.get("maxPitchTurnDegPerTick", 18.0)),
            )
            trace = simulate_round(
                dust2,
                config,
                Visibility(enabled=bool(params.get("staticLos", True))),
                seed=int(params.get("seed", 2607)),
                spawn_mode=str(params.get("spawnMode", "clutch_like")),
                site_choice=str(params.get("site", "auto")),
                bomb_state=str(params.get("bombState", "unplanted")),
                t_area_id=optional_string(params.get("tAreaId")),
                ct_area_id=optional_string(params.get("ctAreaId")),
                frame_stride=max(1, int(params.get("frameStride", 10))),
            )
        except Exception as exc:  # noqa: BLE001
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.serve_json(trace)

    def serve_rl_simulation(self) -> None:
        try:
            size = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(size) if size > 0 else b"{}"
            params = json.loads(raw.decode("utf-8"))
            phase = normalize_rl_phase(params.get("modelPhase"))
            if phase in PHASE_C_CHECKPOINTS:
                defaults = PHASE_C_CHECKPOINTS[phase]
                t_checkpoint = repo_local_path(
                    str(params.get("tCheckpoint") or defaults["T"]), suffix=".zip"
                )
                ct_checkpoint = repo_local_path(
                    str(params.get("ctCheckpoint") or defaults["CT"]), suffix=".zip"
                )
            else:
                checkpoint = repo_local_path(
                    str(params.get("checkpoint") or RL_CHECKPOINTS[phase]), suffix=".zip"
                )
            config = replace(
                Dust2Config(),
                round_seconds=float(params.get("roundSeconds", 40.0)),
                bomb_timer_seconds=float(params.get("bombTimerSeconds", 40.0)),
                tick_seconds=float(params.get("tickSeconds", 0.01)),
                p_hit_max=float(params.get("pHitMax", 0.9)),
                max_turn_deg_per_tick=float(params.get("maxTurnDegPerTick", 18.0)),
                max_pitch_turn_deg_per_tick=float(params.get("maxPitchTurnDegPerTick", 18.0)),
            )
            common = {
                "seed": int(params.get("seed", 2607)),
                "site_choice": str(params.get("site", "auto")),
                "bomb_state": str(params.get("bombState", "unplanted")),
                "t_area_id": optional_string(params.get("tAreaId")),
                "ct_area_id": optional_string(params.get("ctAreaId")),
                "static_los": bool(params.get("staticLos", True)),
                "frame_stride": max(1, int(params.get("frameStride", 10))),
                "max_decisions": max(1, int(params.get("maxDecisions", 900))),
                "model_phase": phase,
            }
            if phase in PHASE_C_CHECKPOINTS:
                trace = rollout_phase_c_pair(t_checkpoint, ct_checkpoint, config, **common)
            else:
                trace = rollout_rl_policy(
                    checkpoint,
                    config,
                    spawn_mode=str(params.get("spawnMode", "clutch_like")),
                    **common,
                )
        except Exception as exc:  # noqa: BLE001
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.serve_json(trace)

    def serve_json(self, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.write_json_bytes(body)

    def write_json_bytes(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_rl_phase(value: object) -> str:
    text = str(value or DEFAULT_RL_PHASE).strip().upper()
    if text not in RL_CHECKPOINTS and text not in PHASE_C_CHECKPOINTS:
        raise ValueError(f"unknown RL model phase: {text}")
    return text


def repo_local_path(raw_path: str, *, suffix: str) -> Path:
    candidate = (REPO_ROOT / raw_path).resolve()
    if not candidate.is_relative_to(REPO_ROOT) or candidate.suffix != suffix:
        raise ValueError(f"path must be a repo-local {suffix} file")
    if not candidate.exists():
        raise FileNotFoundError(str(candidate))
    return candidate


def cached_recurrent_model(checkpoint: Path, role: str) -> object:
    from sb3_contrib import RecurrentPPO

    stat = checkpoint.stat()
    cache_key = (str(checkpoint), role, stat.st_mtime_ns, stat.st_size)
    model = _MODEL_CACHE.get(cache_key)
    if model is not None:
        return model
    stale_keys = [
        key
        for key in _MODEL_CACHE
        if key[0] == str(checkpoint) and key[1] == role
    ]
    for key in stale_keys:
        _MODEL_CACHE.pop(key, None)
    model = RecurrentPPO.load(str(checkpoint), device="auto")
    _MODEL_CACHE[cache_key] = model
    return model


def rollout_rl_policy(
    checkpoint: Path,
    config: Dust2Config,
    *,
    seed: int,
    spawn_mode: str,
    site_choice: str,
    bomb_state: str,
    t_area_id: str | None,
    ct_area_id: str | None,
    static_los: bool,
    frame_stride: int,
    max_decisions: int,
    model_phase: str,
) -> dict:
    from .dust2_rl import Dust2PrimitiveEnv, Dust2Scenario
    from .dust2_rl_train import reward_config_for_phase

    scenario = Dust2Scenario(
        seed=seed,
        spawn_mode=spawn_mode,
        site_choice=site_choice,
        bomb_state=bomb_state,
        t_area_id=t_area_id,
        ct_area_id=ct_area_id,
        learner_side="T",
        static_los=static_los,
        frame_stride=frame_stride,
    )
    reward_config = reward_config_for_phase("A" if model_phase == "A" else "B")
    env = Dust2PrimitiveEnv(scenario=scenario, reward_config=reward_config, config=config)
    model = cached_recurrent_model(checkpoint, "single-policy")
    obs, _ = env.reset(seed=seed)
    lstm_state = None
    episode_start = True
    for _ in range(max_decisions):
        action, lstm_state = model.predict(
            obs,
            state=lstm_state,
            episode_start=[episode_start],
            deterministic=False,
        )
        obs, _, terminated, truncated, _ = env.step(action)
        episode_start = terminated or truncated
        if terminated or truncated:
            break
    payload = env.trace_payload()
    payload.setdefault("rl", {})
    payload["rl"].update({
        "status": "trained-policy-rollout",
        "checkpoint": display_checkpoint_path(checkpoint),
        "modelPhase": model_phase,
        "deterministic": False,
        "maxDecisions": max_decisions,
    })
    return payload


def rollout_phase_c_pair(
    t_checkpoint: Path,
    ct_checkpoint: Path,
    config: Dust2Config,
    *,
    seed: int,
    site_choice: str,
    bomb_state: str,
    t_area_id: str | None,
    ct_area_id: str | None,
    static_los: bool,
    frame_stride: int,
    max_decisions: int,
    model_phase: str,
) -> dict:
    from .dust2_phase_c import PHASE_C_ENV_REVISION, PhaseCSelfPlayEnv

    ct_model = cached_recurrent_model(ct_checkpoint, "phase-c-ct")
    env = PhaseCSelfPlayEnv(
        learner_side="T",
        seed=seed,
        opponent_checkpoint=ct_checkpoint,
        opponent_model=ct_model,
        config=config,
        frame_stride=frame_stride,
        randomize_scenario=False,
        site_choice=site_choice,
        bomb_state=bomb_state,
        t_area_id=t_area_id,
        ct_area_id=ct_area_id,
        static_los=static_los,
    )
    model = cached_recurrent_model(t_checkpoint, "phase-c-t")
    obs, _ = env.reset(seed=seed)
    lstm_state = None
    episode_start = True
    for _ in range(max_decisions):
        action, lstm_state = model.predict(
            obs,
            state=lstm_state,
            episode_start=[episode_start],
            deterministic=False,
        )
        obs, _, terminated, truncated, _ = env.step(action)
        episode_start = terminated or truncated
        if episode_start:
            break
    payload = env.trace_payload()
    payload["rl"].update(
        {
            "status": "trained-dual-policy-rollout",
            "environmentRevision": PHASE_C_ENV_REVISION,
            "modelPhase": model_phase,
            "tCheckpoint": display_checkpoint_path(t_checkpoint),
            "ctCheckpoint": display_checkpoint_path(ct_checkpoint),
            "deterministic": False,
            "maxDecisions": max_decisions,
        }
    )
    return payload


class ViewerHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the solo-clutch trace viewer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()

    viewer_dir = Path(__file__).resolve().parents[1] / "viewer"
    handler = partial(ViewerRequestHandler, directory=str(viewer_dir))
    server = ViewerHTTPServer((args.host, args.port), handler)
    print(f"Serving solo-clutch trace viewer at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
