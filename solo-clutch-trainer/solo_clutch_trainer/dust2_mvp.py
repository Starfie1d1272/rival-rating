from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
import heapq
import json
import math
import os
from pathlib import Path
import random
from typing import Any, Iterable, Literal


REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_INFO_PATH = REPO_ROOT / ".map-control-cache" / "static-info" / "de_dust2.json"
RADAR_PATH = REPO_ROOT / ".awpy-home" / ".awpy" / "maps" / "de_dust2.png"
TRI_PATH = REPO_ROOT / ".awpy-home" / ".awpy" / "tris" / "de_dust2.tri"
VISIBILITY_CACHE_QUANTUM = 16.0
DUST2_BOMB_SITE_SOURCE = "dust2_fixed_nav_area_ids_from_demo_plants_and_radar_site_boxes"
DUST2_BOMB_SITE_AREA_IDS: dict[str, tuple[str, ...]] = {
    "A": (
        "1734",
        "1782",
        "1783",
        "1784",
        "1792",
        "1795",
        "1852",
        "1853",
        "1891",
        "1903",
        "1907",
        "1908",
        "1911",
        "1912",
        "1915",
        "1920",
        "1922",
        "1930",
        "1934",
        "1936",
        "1951",
        "1957",
        "1958",
    ),
    "B": (
        "1898",
        "1904",
        "1906",
        "1950",
        "1989",
        "1990",
        "1999",
        "2002",
        "2003",
        "2004",
        "2006",
        "2011",
        "2012",
        "2013",
        "2016",
        "2021",
        "2025",
        "2026",
        "2032",
        "2035",
        "2037",
        "2052",
        "2062",
        "2064",
        "2096",
        "2097",
    ),
}

Side = Literal["T", "CT"]
BombStateInput = Literal["unplanted", "planted_a", "planted_b"]
SIDES: tuple[Side, Side] = ("T", "CT")


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class NavArea:
    area_id: str
    centroid: Vec3
    pixel_centroid: dict[str, float]
    polygon: list[dict[str, float]]
    corners: list[dict[str, float]]
    size: float
    connections: tuple[str, ...]


@dataclass(frozen=True)
class BombSite:
    site_id: str
    label: str
    position: Vec3
    radius: float
    area_ids: tuple[str, ...]
    bbox: dict[str, float]
    source: str


@dataclass(frozen=True)
class Dust2Map:
    map_name: str
    metadata: dict[str, Any]
    areas: dict[str, NavArea]
    graph: dict[str, tuple[str, ...]]
    bomb_sites: dict[str, BombSite]


@dataclass(frozen=True)
class Dust2Config:
    tick_seconds: float = 0.01
    decision_interval_ticks: int = 10
    round_seconds: float = 40.0
    bomb_timer_seconds: float = 40.0
    plant_seconds: float = 3.2
    defuse_seconds: float = 5.0
    death_grace_seconds: float = 7.0
    eye_height: float = 64.0
    player_radius: float = 16.0
    collision_radius: float = 16.0
    visibility_shoulder_radius: float = 11.5
    body_hit_radius: float = 13.0
    viewer_marker_radius: float = 8.0
    run_speed_units_per_second: float = 215.0
    walk_speed_units_per_second: float = 111.0
    max_turn_deg_per_tick: float = 18.0
    max_pitch_turn_deg_per_tick: float = 18.0
    fov_deg: float = 100.0
    vision_range: float = 3200.0
    hearing_range: float = 900.0
    sound_region_radius: float = 360.0
    sound_region_min_areas: int = 5
    sound_sample_interval_seconds: float = 0.20
    p_hit_max: float = 0.9
    hit_sigma_scale: float = 3.4
    min_hit_sigma_deg: float = 1.1
    ak_head_hit_max: float = 0.35
    ak_body_hit_max: float = 0.55
    ak_head_radius: float = 3.4
    ak_body_radius_scale: float = 1.28
    ak_min_head_sigma_deg: float = 0.35
    ak_min_body_sigma_deg: float = 1.35
    ak_walk_accuracy_penalty: float = 0.78
    ak_run_accuracy_penalty: float = 0.38
    ak_turn_penalty_per_deg: float = 0.18
    ak_turn_penalty_floor: float = 0.32
    ak_body_damage_min: float = 0.3
    ak_body_damage_mode: float = 0.42
    ak_body_damage_max: float = 0.6
    fire_cooldown_ticks: int = 10
    max_ammo: int = 30
    min_fire_probability: float = 0.08
    reload_cooldown_ticks: int = 250
    enable_utilities: bool = False
    smoke_radius: float = 155.0
    smoke_duration_seconds: float = 18.0
    fire_radius: float = 140.0
    fire_duration_seconds: float = 7.0
    fire_damage_per_second: float = 0.18
    bomb_explosion_radius: float = 1750.0
    bomb_explosion_max_damage: float = 5.0
    max_step_up: float = 18.0
    max_jump_up: float = 66.0
    max_jump_gap: float = 190.0
    max_drop: float = 160.0
    velocity_stop_ticks: int = 2
    stationary_commit_speed_units_per_second: float = 25.0
    jitter_window_ticks: int = 50
    stall_speed_units_per_tick: float = 0.2
    aim_quality_threshold: float = 0.72
    route_clear_interval_ticks: int = 330
    route_clear_hold_ticks: int = 40
    contact_clear_hold_ticks: int = 45

    def ticks_for_seconds(self, seconds: float) -> int:
        return max(1, round(seconds / self.tick_seconds))

    @property
    def round_ticks(self) -> int:
        return max(1, round(self.round_seconds / self.tick_seconds))

    @property
    def bomb_timer_ticks(self) -> int:
        return max(1, round(self.bomb_timer_seconds / self.tick_seconds))

    @property
    def plant_ticks(self) -> int:
        return max(1, round(self.plant_seconds / self.tick_seconds))

    @property
    def defuse_ticks(self) -> int:
        return max(1, round(self.defuse_seconds / self.tick_seconds))

    @property
    def death_grace_ticks(self) -> int:
        return max(0, round(self.death_grace_seconds / self.tick_seconds))

    @property
    def smoke_duration_ticks(self) -> int:
        return max(1, round(self.smoke_duration_seconds / self.tick_seconds))

    @property
    def fire_duration_ticks(self) -> int:
        return max(1, round(self.fire_duration_seconds / self.tick_seconds))

    @property
    def run_speed_per_tick(self) -> float:
        return self.run_speed_units_per_second * self.tick_seconds

    @property
    def walk_speed_per_tick(self) -> float:
        return self.walk_speed_units_per_second * self.tick_seconds

    @property
    def max_velocity_delta_per_tick(self) -> float:
        return self.run_speed_per_tick / max(1, self.velocity_stop_ticks)

    @property
    def stationary_commit_speed_per_tick(self) -> float:
        return self.stationary_commit_speed_units_per_second * self.tick_seconds

    @property
    def sound_sample_interval_ticks(self) -> int:
        return self.ticks_for_seconds(self.sound_sample_interval_seconds)


@dataclass(frozen=True)
class UtilityCloud:
    utility_id: str
    kind: Literal["smoke", "fire"]
    position: Vec3
    radius: float
    start_tick: int
    end_tick: int
    owner: Side


@dataclass(frozen=True)
class HitSample:
    group: Literal["head", "body"]
    point: Vec3
    radius: float
    priority: float


@dataclass(frozen=True)
class AgentState:
    side: Side
    area_id: str
    position: Vec3
    velocity: Vec3
    aim_deg: float
    aim_pitch_deg: float
    aim_turn_delta_deg: float
    aim_pitch_turn_delta_deg: float
    hp: float
    is_alive: bool
    ammo: int
    fire_cooldown_ticks: int
    reload_cooldown_ticks: int
    route: tuple[str, ...]
    route_index: int
    target_area_id: str | None
    last_seen_position: Vec3 | None
    last_seen_tick: int | None
    last_sound_position: Vec3 | None
    last_sound_tick: int | None
    smoke_available: bool
    fire_available: bool
    action_label: str
    aim_context: str
    macro_intent: str
    committed_ticks: int
    jump_ticks: int
    site_rotate_count: int


@dataclass(frozen=True)
class BombState:
    site_id: str
    planted: bool
    defused: bool
    position: Vec3 | None
    planted_at_tick: int | None
    plant_progress_ticks: int
    defuse_progress_ticks: int


@dataclass(frozen=True)
class Terminal:
    reason: str
    winner: Side
    tick: int


@dataclass(frozen=True)
class RoundState:
    tick: int
    agents: dict[Side, AgentState]
    utilities: tuple[UtilityCloud, ...]
    bomb: BombState
    terminal: Terminal | None
    death_tick: int | None


class PathCache:
    def __init__(self, dust2: Dust2Map, config: Dust2Config):
        self.dust2 = dust2
        self.config = config
        self._paths: dict[tuple[str, str], tuple[str, ...]] = {}

    def path(self, start: str, goal: str) -> tuple[str, ...]:
        key = (start, goal)
        if key not in self._paths:
            self._paths[key] = shortest_path(self.dust2, self.config, start, goal)
        return self._paths[key]


@lru_cache(maxsize=2)
def _visibility_checker(path: str) -> Any:
    os.environ.setdefault("HOME", str(REPO_ROOT / ".awpy-home"))
    from awpy.visibility import VisibilityChecker  # noqa: PLC0415

    return VisibilityChecker(path=Path(path))


def _visibility_segment_key(start: Vec3, end: Vec3) -> tuple[int, int, int, int, int, int]:
    a = (
        round(start.x / VISIBILITY_CACHE_QUANTUM),
        round(start.y / VISIBILITY_CACHE_QUANTUM),
        round(start.z / VISIBILITY_CACHE_QUANTUM),
    )
    b = (
        round(end.x / VISIBILITY_CACHE_QUANTUM),
        round(end.y / VISIBILITY_CACHE_QUANTUM),
        round(end.z / VISIBILITY_CACHE_QUANTUM),
    )
    low, high = (a, b) if a <= b else (b, a)
    return (*low, *high)


@lru_cache(maxsize=300_000)
def _visible_quantized(path: str, key: tuple[int, int, int, int, int, int]) -> bool:
    checker = _visibility_checker(path)
    sx, sy, sz, ex, ey, ez = (value * VISIBILITY_CACHE_QUANTUM for value in key)
    return bool(checker.is_visible((sx, sy, sz), (ex, ey, ez)))


class Visibility:
    def __init__(self, enabled: bool):
        self.enabled = enabled and TRI_PATH.exists()
        self.checker: Any | None = None
        if self.enabled:
            self.checker = _visibility_checker(str(TRI_PATH))

    def visible(self, start: Vec3, end: Vec3) -> bool:
        if self.checker is None:
            return True
        return _visible_quantized(str(TRI_PATH), _visibility_segment_key(start, end))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a Dust2 2.5D solo-clutch MVP trace")
    parser.add_argument("--out", default=".solo-clutch-runs/dust2-mvp/trace.json")
    parser.add_argument("--seed", type=int, default=2606)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--spawn-mode", choices=["uniform_walkable", "objective_biased", "clutch_like", "plant_curriculum", "postplant_curriculum", "mixed_curriculum"], default="clutch_like")
    parser.add_argument("--site", choices=["auto", "A", "B"], default="auto")
    parser.add_argument("--bomb-state", choices=["unplanted", "planted_a", "planted_b"], default="unplanted")
    parser.add_argument("--t-area-id")
    parser.add_argument("--ct-area-id")
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--no-static-los", action="store_true")
    parser.add_argument("--round-seconds", type=float, default=40.0)
    parser.add_argument("--bomb-timer-seconds", type=float, default=40.0)
    parser.add_argument("--tick-seconds", type=float, default=0.01)
    parser.add_argument("--max-turn-deg-per-tick", type=float, default=18.0)
    parser.add_argument("--p-hit-max", type=float, default=0.9)
    args = parser.parse_args()

    config = replace(
        Dust2Config(),
        round_seconds=args.round_seconds,
        bomb_timer_seconds=args.bomb_timer_seconds,
        tick_seconds=args.tick_seconds,
        max_turn_deg_per_tick=args.max_turn_deg_per_tick,
        p_hit_max=args.p_hit_max,
    )
    dust2 = load_dust2_map()
    visibility = Visibility(enabled=not args.no_static_los)

    traces = []
    for episode in range(args.episodes):
        trace = simulate_round(
            dust2,
            config,
            visibility,
            seed=args.seed + episode,
            spawn_mode=args.spawn_mode,
            site_choice=args.site,
            bomb_state=args.bomb_state,
            t_area_id=args.t_area_id,
            ct_area_id=args.ct_area_id,
            frame_stride=max(1, args.frame_stride),
        )
        traces.append(trace)

    payload = traces[0] if args.episodes == 1 else {
        "kind": "dust2-solo-clutch-batch",
        "episodes": traces,
        "summaries": [trace["summary"] for trace in traces],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload["summary"] if args.episodes == 1 else payload["summaries"], indent=2, sort_keys=True))


def load_dust2_map() -> Dust2Map:
    if not STATIC_INFO_PATH.exists():
        raise SystemExit(f"Missing Dust2 static info: {STATIC_INFO_PATH}")
    data = json.loads(STATIC_INFO_PATH.read_text(encoding="utf-8"))
    areas: dict[str, NavArea] = {}
    for row in data["map"]["areas"]:
        centroid = row["centroid"]
        areas[row["id"]] = NavArea(
            area_id=row["id"],
            centroid=Vec3(float(centroid["x"]), float(centroid["y"]), float(centroid["z"])),
            pixel_centroid=row["pixelCentroid"],
            polygon=row["polygon"],
            corners=row["corners"],
            size=float(row["size"]),
            connections=tuple(str(x) for x in row.get("connections", [])),
        )
    graph = {area_id: area.connections for area_id, area in areas.items()}
    return Dust2Map(
        map_name="de_dust2",
        metadata=data["map"]["metadata"],
        areas=areas,
        graph=graph,
        bomb_sites=build_bomb_sites(areas),
    )


def build_bomb_sites(areas: dict[str, NavArea]) -> dict[str, BombSite]:
    return {
        site_id: build_bomb_site(site_id, area_ids, areas)
        for site_id, area_ids in DUST2_BOMB_SITE_AREA_IDS.items()
    }


def build_bomb_site(site_id: str, area_ids: tuple[str, ...], areas: dict[str, NavArea]) -> BombSite:
    site_areas = [areas[area_id] for area_id in area_ids if area_id in areas]
    missing = [area_id for area_id in area_ids if area_id not in areas]
    if missing:
        raise SystemExit(f"Missing Dust2 {site_id} bombsite nav areas: {', '.join(missing)}")
    total = sum(max(area.size, 1.0) for area in site_areas)
    center = Vec3(
        sum(area.centroid.x * max(area.size, 1.0) for area in site_areas) / total,
        sum(area.centroid.y * max(area.size, 1.0) for area in site_areas) / total,
        sum(area.centroid.z * max(area.size, 1.0) for area in site_areas) / total,
    )
    corners = [corner for area in site_areas for corner in area.corners]
    bbox = {
        "minX": min(float(corner["x"]) for corner in corners),
        "maxX": max(float(corner["x"]) for corner in corners),
        "minY": min(float(corner["y"]) for corner in corners),
        "maxY": max(float(corner["y"]) for corner in corners),
        "minZ": min(float(corner["z"]) for corner in corners),
        "maxZ": max(float(corner["z"]) for corner in corners),
    }
    radius = max(distance2(center, Vec3(float(corner["x"]), float(corner["y"]), center.z)) for corner in corners) + 24.0
    return BombSite(
        site_id=site_id,
        label=f"{site_id} Site",
        position=center,
        radius=radius,
        area_ids=area_ids,
        bbox=bbox,
        source=DUST2_BOMB_SITE_SOURCE,
    )


def simulate_round(
    dust2: Dust2Map,
    config: Dust2Config,
    visibility: Visibility,
    *,
    seed: int,
    spawn_mode: str,
    site_choice: str,
    bomb_state: BombStateInput = "unplanted",
    t_area_id: str | None = None,
    ct_area_id: str | None = None,
    frame_stride: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    forced_site_id = site_id_for_scenario(site_choice, bomb_state)
    spawn_site_id = forced_site_id or rng.choice(("A", "B"))
    path_cache = PathCache(dust2, config)
    state = create_initial_state(
        dust2,
        config,
        rng,
        spawn_mode=spawn_mode,
        site_id=spawn_site_id,
        bomb_state=bomb_state,
        t_area_id=t_area_id,
        ct_area_id=ct_area_id,
        path_cache=path_cache,
    )
    initial_events: list[dict[str, Any]] = []
    if forced_site_id is None:
        chosen_site_id = choose_t_bombsite(dust2, path_cache, state.agents["T"].area_id, rng)
        state = replace(
            state,
            bomb=replace(state.bomb, site_id=chosen_site_id),
            agents={
                **state.agents,
                "T": replace(state.agents["T"], macro_intent=sample_t_macro_intent(rng, bomb_state, chosen_site_id)),
            },
        )
        initial_events.append({"type": "site-choice", "tick": 0, "side": "T", "site": chosen_site_id, "mode": "auto"})
    initial_events.append({"type": "macro-intent", "tick": 0, "side": "T", "intent": state.agents["T"].macro_intent, "site": state.bomb.site_id})
    initial_area_ids = {
        "T": state.agents["T"].area_id,
        "CT": state.agents["CT"].area_id,
    }
    frames: list[dict[str, Any]] = [frame_payload(state, initial_events, {}, config, visibility)] if initial_events else []
    all_events: list[dict[str, Any]] = list(initial_events)
    full_tick_metrics: list[dict[str, Any]] = []

    max_ticks = config.round_ticks + config.bomb_timer_ticks + config.defuse_ticks + config.death_grace_ticks + 8
    while state.terminal is None and state.tick < max_ticks:
        state, events, tick_metric = step_dust2_round(dust2, config, visibility, path_cache, state, rng)
        all_events.extend(events)
        full_tick_metrics.append(tick_metric)
        if state.tick % frame_stride == 0 or state.terminal is not None or has_key_events(events):
            frames.append(frame_payload(state, events, tick_metric, config, visibility))

    if state.terminal is None:
        state = replace(state, terminal=Terminal("safety-ct-timeout", "CT", state.tick))
        all_events.append({"type": "terminal", "tick": state.tick, "reason": state.terminal.reason, "winner": "CT"})
        frames.append(frame_payload(state, all_events[-1:], full_tick_metrics[-1] if full_tick_metrics else {}, config, visibility))

    behavior = summarize_behavior(full_tick_metrics, all_events, state, config)
    summary = {
        "winner": state.terminal.winner,
        "terminal_reason": state.terminal.reason,
        "terminal_tick": state.terminal.tick,
        "terminal_seconds": round(state.terminal.tick * config.tick_seconds, 3),
        "site": state.bomb.site_id,
        "site_choice": site_choice,
        "bomb_state": bomb_state,
        "spawn_mode": spawn_mode,
        "selected_areas": initial_area_ids,
        "behavior": behavior,
    }
    return {
        "kind": "dust2-solo-clutch-mvp-trace",
        "schemaVersion": "dust2-solo-clutch-mvp-0.1",
        "seed": seed,
        "config": config_payload(config),
        "knowledge": knowledge_payload(),
        "map": map_payload(dust2),
        "summary": summary,
        "frames": frames,
        "events": all_events,
    }


def site_id_for_scenario(site_choice: str, bomb_state: BombStateInput) -> str | None:
    if bomb_state == "planted_a":
        return "A"
    if bomb_state == "planted_b":
        return "B"
    if site_choice == "auto":
        return None
    if site_choice not in {"A", "B"}:
        raise ValueError("site_choice must be auto, A, or B")
    return site_choice


def create_initial_state(
    dust2: Dust2Map,
    config: Dust2Config,
    rng: random.Random,
    *,
    spawn_mode: str,
    site_id: str,
    bomb_state: BombStateInput,
    t_area_id: str | None,
    ct_area_id: str | None,
    path_cache: PathCache,
) -> RoundState:
    site = dust2.bomb_sites[site_id]
    site_area = site_representative_area_id(dust2, site)
    t_area, ct_area = resolve_start_areas(
        dust2,
        config,
        rng,
        spawn_mode,
        site_area,
        path_cache,
        t_area_id=t_area_id,
        ct_area_id=ct_area_id,
    )
    t_pos = dust2.areas[t_area].centroid
    ct_pos = dust2.areas[ct_area].centroid
    if distance3(t_pos, ct_pos) < config.collision_radius * 2.0:
        raise ValueError("T and CT start positions overlap")
    planted = bomb_state in {"planted_a", "planted_b"}
    bomb_position = (
        dust2.areas[rng.choice(site.area_ids)].centroid
        if planted
        else None
    )
    return RoundState(
        tick=0,
        utilities=(),
        terminal=None,
        death_tick=None,
        bomb=BombState(
            site_id=site_id,
            planted=planted,
            defused=False,
            position=bomb_position,
            planted_at_tick=0 if planted else None,
            plant_progress_ticks=0,
            defuse_progress_ticks=0,
        ),
        agents={
            "T": AgentState(
                side="T",
                area_id=t_area,
                position=t_pos,
                velocity=Vec3(0.0, 0.0, 0.0),
                aim_deg=angle_to(t_pos, site.position),
                aim_pitch_deg=pitch_to(eye_position(t_pos, config.eye_height), default_aim_point(site.position, config)),
                aim_turn_delta_deg=0.0,
                aim_pitch_turn_delta_deg=0.0,
                hp=1.0,
                is_alive=True,
                ammo=config.max_ammo,
                fire_cooldown_ticks=0,
                reload_cooldown_ticks=0,
                route=(),
                route_index=0,
                target_area_id=None,
                last_seen_position=None,
                last_seen_tick=None,
                last_sound_position=None,
                last_sound_tick=None,
                smoke_available=False,
                fire_available=False,
                action_label="spawn",
                aim_context="site",
                macro_intent=sample_t_macro_intent(rng, bomb_state, site_id),
                committed_ticks=0,
                jump_ticks=0,
                site_rotate_count=0,
            ),
            "CT": AgentState(
                side="CT",
                area_id=ct_area,
                position=ct_pos,
                velocity=Vec3(0.0, 0.0, 0.0),
                aim_deg=angle_to(ct_pos, site.position),
                aim_pitch_deg=pitch_to(eye_position(ct_pos, config.eye_height), default_aim_point(site.position, config)),
                aim_turn_delta_deg=0.0,
                aim_pitch_turn_delta_deg=0.0,
                hp=1.0,
                is_alive=True,
                ammo=config.max_ammo,
                fire_cooldown_ticks=0,
                reload_cooldown_ticks=0,
                route=(),
                route_index=0,
                target_area_id=None,
                last_seen_position=None,
                last_seen_tick=None,
                last_sound_position=None,
                last_sound_tick=None,
                smoke_available=False,
                fire_available=False,
                action_label="spawn",
                aim_context="site",
                macro_intent="reactive-rational",
                committed_ticks=0,
                jump_ticks=0,
                site_rotate_count=0,
            ),
        },
    )


def has_key_events(events: list[dict[str, Any]]) -> bool:
    key_types = {
        "smoke",
        "fire",
        "jump",
        "bomb-planted",
        "bomb-defused",
        "bomb-exploded",
        "site-rotate",
        "site-retarget",
        "search-point",
        "angle-clear",
        "reload",
        "death",
        "terminal",
        "shot",
        "withheld-shot",
    }
    return any(event.get("type") in key_types for event in events)


def resolve_start_areas(
    dust2: Dust2Map,
    config: Dust2Config,
    rng: random.Random,
    spawn_mode: str,
    site_area: str,
    path_cache: PathCache,
    *,
    t_area_id: str | None,
    ct_area_id: str | None,
) -> tuple[str, str]:
    if t_area_id is not None or ct_area_id is not None:
        fallback_t, fallback_ct = sample_start_areas(dust2, config, rng, spawn_mode, site_area, path_cache)
        t_area = validate_start_area(dust2, path_cache, t_area_id, site_area, fallback_t, "T")
        ct_area = validate_start_area(dust2, path_cache, ct_area_id, site_area, fallback_ct, "CT")
        if t_area == ct_area:
            raise ValueError("T and CT start areas must be different")
        return t_area, ct_area
    return sample_start_areas(dust2, config, rng, spawn_mode, site_area, path_cache)


def validate_start_area(
    dust2: Dust2Map,
    path_cache: PathCache,
    area_id: str | None,
    site_area: str,
    fallback: str,
    side: Side,
) -> str:
    if area_id is None:
        return fallback
    normalized = str(area_id)
    if normalized not in dust2.areas:
        raise ValueError(f"{side} start area {normalized!r} is not a Dust2 nav area")
    if not path_cache.path(normalized, site_area):
        raise ValueError(f"{side} start area {normalized!r} cannot route to selected site")
    return normalized


def sample_start_areas(
    dust2: Dust2Map,
    config: Dust2Config,
    rng: random.Random,
    spawn_mode: str,
    site_area: str,
    path_cache: PathCache,
) -> tuple[str, str]:
    if spawn_mode == "mixed_curriculum":
        roll = rng.random()
        if roll < 0.25:
            spawn_mode = "uniform_walkable"
        elif roll < 0.50:
            spawn_mode = "clutch_like"
        elif roll < 0.70:
            spawn_mode = "objective_biased"
        elif roll < 0.85:
            spawn_mode = "plant_curriculum"
        else:
            spawn_mode = "postplant_curriculum"
    candidates = [area for area in dust2.areas.values() if area.size >= 80.0]
    if spawn_mode == "uniform_walkable":
        for _ in range(800):
            t = weighted_area_choice(candidates, rng).area_id
            ct = weighted_area_choice(candidates, rng).area_id
            if (
                t != ct
                and distance3(dust2.areas[t].centroid, dust2.areas[ct].centroid)
                >= config.collision_radius * 2.0
                and path_cache.path(t, site_area)
                and path_cache.path(ct, site_area)
            ):
                return t, ct
    site = dust2.areas[site_area].centroid
    scored = []
    for area in candidates:
        d = distance2(area.centroid, site)
        scored.append((area, d))
    if spawn_mode == "plant_curriculum":
        t_pool = [area for area, d in scored if 40.0 <= d <= 850.0]
        ct_pool = [area for area, d in scored if 900.0 <= d <= 3400.0]
    elif spawn_mode == "postplant_curriculum":
        t_pool = [area for area, d in scored if 120.0 <= d <= 1300.0]
        ct_pool = [area for area, d in scored if 450.0 <= d <= 2600.0]
    elif spawn_mode == "objective_biased":
        t_pool = [area for area, d in scored if 250.0 <= d <= 1800.0]
        ct_pool = [area for area, d in scored if 400.0 <= d <= 2600.0]
    else:
        t_pool = [area for area, d in scored if 150.0 <= d <= 1800.0]
        ct_pool = [area for area, d in scored if 300.0 <= d <= 2600.0]
    for _ in range(800):
        t = weighted_area_choice(t_pool or candidates, rng).area_id
        ct = weighted_area_choice(ct_pool or candidates, rng).area_id
        if t == ct:
            continue
        if (
            distance3(dust2.areas[t].centroid, dust2.areas[ct].centroid)
            < config.collision_radius * 2.0
        ):
            continue
        t_path = path_cache.path(t, site_area)
        ct_path = path_cache.path(ct, site_area)
        if not t_path or not ct_path:
            continue
        if spawn_mode == "plant_curriculum":
            if len(ct_path) <= len(t_path) + 12:
                continue
        elif spawn_mode == "postplant_curriculum":
            if len(ct_path) <= len(t_path) + 3:
                continue
        elif abs(len(t_path) - len(ct_path)) > 140 and spawn_mode != "uniform_walkable":
            continue
        return t, ct
    for _ in range(800):
        t = weighted_area_choice(candidates, rng).area_id
        ct = weighted_area_choice(candidates, rng).area_id
        if (
            t != ct
            and distance3(dust2.areas[t].centroid, dust2.areas[ct].centroid)
            >= config.collision_radius * 2.0
            and path_cache.path(t, site_area)
            and path_cache.path(ct, site_area)
        ):
            return t, ct
    raise RuntimeError("could not sample non-overlapping Dust2 start areas")


def step_dust2_round(
    dust2: Dust2Map,
    config: Dust2Config,
    visibility: Visibility,
    path_cache: PathCache,
    state: RoundState,
    rng: random.Random,
    action_overrides: dict[Side, dict[str, Any]] | None = None,
) -> tuple[RoundState, list[dict[str, Any]], dict[str, Any]]:
    tick = state.tick + 1
    utilities = tuple(u for u in state.utilities if u.end_tick >= tick)
    rl_controls_t = bool(action_overrides and "T" in action_overrides)
    if rl_controls_t:
        events: list[dict[str, Any]] = []
        site_override = action_overrides["T"].get("site_id")
        if site_override in dust2.bomb_sites and not state.bomb.planted and site_override != state.bomb.site_id:
            events.append({
                "type": "site-choice",
                "tick": tick,
                "side": "T",
                "site": site_override,
                "mode": "rl-primitive",
            })
            state = replace(state, bomb=replace(state.bomb, site_id=site_override, plant_progress_ticks=0))
    else:
        state, events = maybe_retarget_t_site_after_ct_death(dust2, path_cache, state, tick)
        state, rotate_events = maybe_rotate_t_site(dust2, path_cache, state, tick, config, rng)
        events.extend(rotate_events)
    state_with_utilities = replace(state, utilities=utilities)
    actions = {
        side: (
            action_overrides[side]
            if action_overrides and side in action_overrides
            else choose_action(
                side,
                dust2,
                config,
                visibility,
                path_cache,
                state_with_utilities,
                rng,
            )
        )
        for side in SIDES
    }
    for side, action in actions.items():
        if action["label"] == "search-point" and state.agents[side].action_label != "search-point":
            events.append({"type": "search-point", "tick": tick, "side": side, "target": vec_payload(action["aim_target"])})
        if action["label"] in {"route-clear", "contact-clear", "clear-before-plant"} and state.agents[side].action_label != action["label"]:
            events.append({"type": "angle-clear", "tick": tick, "side": side, "kind": action["label"], "target": vec_payload(action["aim_target"])})
    agents = {
        side: advance_agent(dust2, config, state.agents[side], actions[side], path_cache, events, tick)
        for side in SIDES
    }
    agents = resolve_player_collision(agents, state.agents, config)
    agents = apply_information(agents, dust2, config, visibility, utilities, tick, events)
    new_utilities = list(utilities)
    for side in SIDES:
        utility = maybe_deploy_utility(side, agents[side], actions[side], config, tick)
        if utility is not None:
            new_utilities.append(utility)
            events.append({"type": utility.kind, "tick": tick, "side": side, "position": vec_payload(utility.position), "radius": utility.radius})
            agents[side] = replace(
                agents[side],
                smoke_available=False if utility.kind == "smoke" else agents[side].smoke_available,
                fire_available=False if utility.kind == "fire" else agents[side].fire_available,
            )
    utilities = tuple(new_utilities)
    agents = apply_fire_damage(agents, utilities, config, tick, events)
    agents = apply_shots(agents, state.agents, actions, dust2, config, visibility, utilities, tick, rng, events)
    bomb = apply_bomb_objective(state.bomb, agents, actions, dust2, config, tick, events)
    death_tick = state.death_tick
    if death_tick is None and any(not agent.is_alive for agent in agents.values()):
        death_tick = tick
        events.append({"type": "death", "tick": tick, "dead": [side for side, agent in agents.items() if not agent.is_alive]})
    terminal = resolve_terminal(agents, bomb, tick, config, death_tick)
    if terminal is not None:
        if terminal.reason == "bomb-exploded":
            events.append(bomb_explosion_event(agents, bomb, dust2, config, tick))
        events.append({"type": "terminal", "tick": tick, "reason": terminal.reason, "winner": terminal.winner})
    next_state = RoundState(tick=tick, agents=agents, utilities=utilities, bomb=bomb, terminal=terminal, death_tick=death_tick)
    tick_metric = tick_metrics(next_state, actions, dust2, config, visibility, utilities)
    return next_state, events, tick_metric


def resolve_player_collision(
    agents: dict[Side, AgentState],
    previous_agents: dict[Side, AgentState],
    config: Dust2Config,
) -> dict[Side, AgentState]:
    t_agent = agents["T"]
    ct_agent = agents["CT"]
    if (
        not t_agent.is_alive
        or not ct_agent.is_alive
        or distance3(t_agent.position, ct_agent.position) >= config.collision_radius * 2.0
    ):
        return agents

    moved = {
        side: distance3(agents[side].position, previous_agents[side].position)
        for side in SIDES
    }
    blocked = dict(agents)
    moving_sides = [side for side in SIDES if moved[side] > 1e-6]
    if not moving_sides:
        return agents
    sides_to_revert = moving_sides if len(moving_sides) == 1 else list(SIDES)
    for side in sides_to_revert:
        previous = previous_agents[side]
        blocked[side] = replace(
            blocked[side],
            area_id=previous.area_id,
            position=previous.position,
            velocity=Vec3(0.0, 0.0, 0.0),
            route=previous.route,
            route_index=previous.route_index,
        )
    return blocked


def maybe_retarget_t_site_after_ct_death(
    dust2: Dust2Map,
    path_cache: PathCache,
    state: RoundState,
    tick: int,
) -> tuple[RoundState, list[dict[str, Any]]]:
    t_agent = state.agents["T"]
    ct_agent = state.agents["CT"]
    if state.bomb.planted or not t_agent.is_alive or ct_agent.is_alive:
        return state, []
    nearest_site = nearest_bomb_site_to_agent(dust2, path_cache, t_agent)
    if nearest_site.site_id == state.bomb.site_id:
        return state, []
    next_intent = f"fast-plant-{nearest_site.site_id.lower()}-close"
    next_t = replace(
        t_agent,
        macro_intent=next_intent,
        target_area_id=None,
        route=(),
        route_index=0,
    )
    next_state = replace(
        state,
        bomb=replace(state.bomb, site_id=nearest_site.site_id, plant_progress_ticks=0),
        agents={**state.agents, "T": next_t},
    )
    return next_state, [
        {
            "type": "site-retarget",
            "tick": tick,
            "side": "T",
            "from": state.bomb.site_id,
            "to": nearest_site.site_id,
            "reason": "ct-dead-nearest-plant-site",
        },
        {"type": "macro-intent", "tick": tick, "side": "T", "intent": next_intent, "site": nearest_site.site_id},
    ]


def nearest_bomb_site_to_agent(dust2: Dust2Map, path_cache: PathCache, agent: AgentState) -> BombSite:
    scored: list[tuple[float, str, BombSite]] = []
    for site_id, site in dust2.bomb_sites.items():
        if is_on_bomb_site(dust2, site, agent):
            return site
        site_area = site_representative_area_id(dust2, site)
        route = path_cache.path(agent.area_id, site_area)
        if not route:
            continue
        scored.append((path_distance(dust2, route), site_id, site))
    if not scored:
        return min(dust2.bomb_sites.values(), key=lambda site: distance2(agent.position, site.position))
    scored.sort(key=lambda row: (row[0], row[1]))
    return scored[0][2]


def maybe_rotate_t_site(
    dust2: Dust2Map,
    path_cache: PathCache,
    state: RoundState,
    tick: int,
    config: Dust2Config,
    rng: random.Random,
) -> tuple[RoundState, list[dict[str, Any]]]:
    t_agent = state.agents["T"]
    ct_agent = state.agents["CT"]
    if state.bomb.planted or not t_agent.is_alive or not ct_agent.is_alive or t_agent.site_rotate_count >= 1:
        return state, []
    current_site = dust2.bomb_sites[state.bomb.site_id]
    if is_on_bomb_site(dust2, current_site, t_agent):
        return state, []

    contact_position: Vec3 | None = None
    contact_reason = "ct-seen-near-current-site"
    if t_agent.last_seen_position is not None and t_agent.last_seen_tick is not None and tick - t_agent.last_seen_tick <= 140:
        contact_position = t_agent.last_seen_position
    elif t_agent.last_sound_position is not None and t_agent.last_sound_tick is not None and tick - t_agent.last_sound_tick <= 80:
        contact_position = t_agent.last_sound_position
        contact_reason = "ct-heard-near-current-site"
    if contact_position is None:
        return state, []
    if distance2(contact_position, current_site.position) > current_site.radius * 3.4:
        return state, []

    next_site_id = "B" if state.bomb.site_id == "A" else "A"
    next_site = dust2.bomb_sites[next_site_id]
    current_site_area = site_representative_area_id(dust2, current_site)
    next_site_area = site_representative_area_id(dust2, next_site)
    current_path = path_cache.path(t_agent.area_id, current_site_area)
    next_path = path_cache.path(t_agent.area_id, next_site_area)
    if not current_path or not next_path:
        return state, []

    current_cost = path_distance(dust2, current_path)
    next_cost = path_distance(dust2, next_path)
    cost_delta = next_cost - current_cost
    speed = config.walk_speed_per_tick if t_route_mode(t_agent.macro_intent) == "walk" else config.run_speed_per_tick
    remaining_ticks = max(0, config.round_ticks - tick)
    next_required_ticks = math.ceil(next_cost / max(speed, 1e-6)) + config.plant_ticks
    current_required_ticks = math.ceil(current_cost / max(speed, 1e-6)) + config.plant_ticks
    rotate_time_buffer_ticks = config.ticks_for_seconds(6.0)
    if next_required_ticks + rotate_time_buffer_ticks > remaining_ticks:
        return state, []
    rotate_probability = clamp(0.94 - max(0.0, cost_delta) / 9000.0, 0.52, 0.94)
    if contact_reason.startswith("ct-heard"):
        rotate_probability *= 0.9
    if t_agent.macro_intent.startswith("fast-plant"):
        rotate_probability *= 0.96
    if t_agent.macro_intent.startswith("slow-clear"):
        rotate_probability = min(0.97, rotate_probability * 1.12)
    if t_agent.macro_intent.startswith("fake-pressure"):
        rotate_probability = min(0.96, rotate_probability * 1.08)
    if rng.random() > rotate_probability:
        return state, []

    next_intent = sample_t_macro_intent(rng, "unplanted", next_site_id)
    next_t = replace(
        t_agent,
        macro_intent=next_intent,
        site_rotate_count=t_agent.site_rotate_count + 1,
        target_area_id=None,
        route=(),
        route_index=0,
    )
    next_state = replace(
        state,
        bomb=replace(state.bomb, site_id=next_site_id, plant_progress_ticks=0),
        agents={**state.agents, "T": next_t},
    )
    return next_state, [
        {
            "type": "site-rotate",
            "tick": tick,
            "side": "T",
            "from": current_site.site_id,
            "to": next_site_id,
            "reason": contact_reason,
            "probability": round(rotate_probability, 3),
            "pathCostDelta": round(cost_delta, 1),
            "requiredTicks": next_required_ticks,
            "remainingTicks": remaining_ticks,
        },
        {"type": "macro-intent", "tick": tick, "side": "T", "intent": next_intent, "site": next_site_id},
    ]


def choose_action(
    side: Side,
    dust2: Dust2Map,
    config: Dust2Config,
    visibility: Visibility,
    path_cache: PathCache,
    state: RoundState,
    rng: random.Random,
) -> dict[str, Any]:
    self_agent = state.agents[side]
    enemy = state.agents["CT" if side == "T" else "T"]
    site = dust2.bomb_sites[state.bomb.site_id]
    visible_enemy = can_see(self_agent, enemy, dust2, config, visibility, state.utilities)
    t_objective_pressure = (
        side == "T"
        and not state.bomb.planted
        and t_has_plant_time_pressure(dust2, path_cache, self_agent, site_representative_area_id(dust2, site), state, config)
    )
    if not self_agent.is_alive:
        return {"move": "hold", "mode": "walk", "target": self_agent.position, "aim_target": self_agent.position, "aim_context": "dead", "fire": False, "plant": False, "defuse": False, "utility": None, "label": "dead"}

    if not t_objective_pressure and should_seek_cover(self_agent, enemy, state, visible_enemy, config, rng):
        cover_area = choose_cover_area(dust2, config, visibility, state.utilities, self_agent, enemy, rng)
        if cover_area != self_agent.area_id:
            aim_target, aim_context = choose_aim_target(self_agent, enemy, combat_aim_point(enemy, config), state, dust2, config, "contact")
            return {
                "move": "route",
                "mode": "run",
                "target_area": cover_area,
                "aim_target": aim_target,
                "aim_context": aim_context,
                "fire": False,
                "plant": False,
                "defuse": False,
                "utility": None,
                "label": "break-contact",
            }

    if visible_enemy:
        aim_target = visible_combat_aim_point(self_agent, enemy, config, visibility, state.utilities)
        head_probability, body_probability = shot_probabilities(self_agent, enemy, dust2, config, visibility, state.utilities)
        shot_probability = head_probability + body_probability
        if self_agent.ammo <= 0:
            return {
                "move": "hold",
                "mode": "walk",
                "target": self_agent.position,
                "aim_target": aim_target,
                "aim_context": "enemy",
                "fire": False,
                "plant": False,
                "defuse": False,
                "utility": None,
                "reload": True,
                "label": "reload",
            }
        if shot_probability < config.min_fire_probability:
            line_up_period = config.ticks_for_seconds(1.20)
            if self_agent.action_label == "line-up-shot" and state.tick % line_up_period >= line_up_period // 2:
                angle_area = choose_cover_area(dust2, config, visibility, state.utilities, self_agent, enemy, rng)
                if angle_area != self_agent.area_id:
                    return {
                        "move": "route",
                        "mode": "walk",
                        "target_area": angle_area,
                        "aim_target": aim_target,
                        "aim_context": "enemy",
                        "fire": False,
                        "plant": False,
                        "defuse": False,
                        "utility": None,
                        "label": "improve-angle",
                    }
            return {
                "move": "hold",
                "mode": "walk",
                "target": self_agent.position,
                "aim_target": aim_target,
                "aim_context": "enemy",
                "fire": False,
                "plant": False,
                "defuse": False,
                "utility": None,
                "label": "line-up-shot",
            }
        return {
            "move": "hold",
            "mode": "walk",
            "target": self_agent.position,
            "aim_target": aim_target,
            "aim_context": "enemy",
            "fire": (
                self_agent.fire_cooldown_ticks == 0
                and self_agent.reload_cooldown_ticks == 0
                and self_agent.ammo > 0
            ),
            "plant": False,
            "defuse": False,
            "utility": None,
            "label": "engage-visible",
        }

    if side == "T":
        enemy_dead_preplant = not enemy.is_alive and not state.bomb.planted
        if state.bomb.planted:
            post_style = t_post_plant_style(self_agent.macro_intent)
            hold_area = choose_postplant_hold_area(
                dust2,
                path_cache,
                self_agent,
                enemy,
                state,
                site,
                config,
                visibility,
                post_style,
            )
            target_area = hold_area if hold_area != self_agent.area_id else self_agent.area_id
            if has_recent_contact(self_agent, state, config):
                aim_target, aim_context = choose_aim_target(self_agent, enemy, site.position, state, dust2, config, "hold-post-plant")
            elif state.bomb.defuse_progress_ticks > 0:
                aim_target = default_aim_point(state.bomb.position or site.position, config)
                aim_context = "bomb"
            else:
                aim_target = choose_postplant_watch_target(dust2, path_cache, self_agent, state, site, config, visibility)
                aim_context = "watch"
            return {
                "move": "route",
                "mode": "walk",
                "target_area": target_area,
                "aim_target": aim_target,
                "aim_context": aim_context,
                "fire": False,
                "plant": False,
                "defuse": False,
                "utility": None,
                "label": f"post-plant-{post_style}",
            }
        on_site = is_on_bomb_site(dust2, site, self_agent)
        if on_site:
            urgent_plant = config.round_ticks - state.tick <= config.plant_ticks + config.ticks_for_seconds(3.0)
            if not enemy_dead_preplant and not urgent_plant and should_clear_before_plant(self_agent, state, config):
                site_area = site_representative_area_id(dust2, site)
                aim_target = choose_clear_angle_target(dust2, path_cache, self_agent, state, site_area, recent_contact_position(self_agent, state, config) or site.position, config)
                return {"move": "hold", "mode": "walk", "target": self_agent.position, "aim_target": aim_target, "aim_context": "clear", "fire": False, "plant": False, "defuse": False, "utility": None, "label": "clear-before-plant"}
            return {"move": "hold", "mode": "walk", "target": self_agent.position, "aim_target": site.position, "aim_context": "bomb", "fire": False, "plant": True, "defuse": False, "utility": None, "label": "plant"}
        route_site = site if enemy_dead_preplant else t_route_site(dust2, state, config, self_agent.macro_intent)
        site_area = site_representative_area_id(dust2, route_site)
        plant_time_pressure = t_has_plant_time_pressure(dust2, path_cache, self_agent, site_area, state, config)
        if not enemy_dead_preplant and not plant_time_pressure and should_macro_pause(self_agent, route_site.position, state, config):
            aim_target, aim_context = choose_aim_target(self_agent, enemy, route_site.position, state, dust2, config, "path")
            return {"move": "hold", "mode": "walk", "target": self_agent.position, "aim_target": aim_target, "aim_context": aim_context, "fire": False, "plant": False, "defuse": False, "utility": None, "label": "macro-pause"}
        if not enemy_dead_preplant and not plant_time_pressure and should_contact_clear(self_agent, state, config, rng):
            search_target = choose_clear_angle_target(dust2, path_cache, self_agent, state, site_area, recent_contact_position(self_agent, state, config) or route_site.position, config)
            return {
                "move": "route",
                "mode": "walk",
                "target_area": site_area,
                "aim_target": search_target,
                "aim_context": "clear",
                "fire": False,
                "plant": False,
                "defuse": False,
                "utility": None,
                "label": "contact-clear",
            }
        if not enemy_dead_preplant and not plant_time_pressure and should_search_point(self_agent, state, config, rng):
            search_target = choose_clear_angle_target(dust2, path_cache, self_agent, state, site_area, route_site.position, config)
            return {
                "move": "route",
                "mode": "walk",
                "target_area": site_area,
                "aim_target": search_target,
                "aim_context": "clear",
                "fire": False,
                "plant": False,
                "defuse": False,
                "utility": None,
                "label": "search-point",
            }
        aim_target, aim_context = choose_aim_target(self_agent, enemy, route_site.position, state, dust2, config, "path")
        utility = "smoke" if self_agent.smoke_available and should_throw_smoke_for_intent(self_agent, route_site.position, state.tick, config, rng) else None
        return {
            "move": "route",
            "mode": "run" if enemy_dead_preplant or plant_time_pressure else t_route_mode(self_agent.macro_intent),
            "target_area": site_area,
            "aim_target": aim_target,
            "aim_context": aim_context,
            "fire": False,
            "plant": False,
            "defuse": False,
            "utility": utility,
            "label": "plant-after-kill" if enemy_dead_preplant else "take-site",
        }

    if state.bomb.planted:
        bomb_position = state.bomb.position or site.position
        on_bomb = distance2(self_agent.position, bomb_position) <= site.radius * 0.55
        last_seen_stale = self_agent.last_seen_tick is None or state.tick - self_agent.last_seen_tick > config.ticks_for_seconds(2.5)
        if on_bomb and (not enemy.is_alive or last_seen_stale):
            return {"move": "hold", "mode": "walk", "target": self_agent.position, "aim_target": bomb_position, "aim_context": "bomb", "fire": False, "plant": False, "defuse": True, "utility": None, "label": "defuse"}
        bomb_area = nearest_area_id(dust2, bomb_position)
        if should_contact_clear(self_agent, state, config, rng):
            aim_target = choose_clear_angle_target(dust2, path_cache, self_agent, state, bomb_area, recent_contact_position(self_agent, state, config) or bomb_position, config)
            return {"move": "route", "mode": "walk", "target_area": bomb_area, "aim_target": aim_target, "aim_context": "clear", "fire": False, "plant": False, "defuse": False, "utility": None, "label": "contact-clear"}
        if not has_recent_contact(self_agent, state, config) and should_search_point(self_agent, state, config, rng):
            aim_target = choose_clear_angle_target(dust2, path_cache, self_agent, state, bomb_area, bomb_position, config)
            return {"move": "route", "mode": "walk", "target_area": bomb_area, "aim_target": aim_target, "aim_context": "clear", "fire": False, "plant": False, "defuse": False, "utility": None, "label": "search-point"}
        if has_recent_contact(self_agent, state, config):
            aim_target, aim_context = choose_aim_target(self_agent, enemy, bomb_position, state, dust2, config, "retake")
        else:
            aim_target = choose_site_watch_target(dust2, path_cache, self_agent, state, site, config)
            aim_context = "watch"
        utility = "fire" if self_agent.fire_available and should_throw_fire(self_agent, bomb_position, config, state.tick, rng) else None
        return {"move": "route", "mode": "run", "target_area": bomb_area, "aim_target": aim_target, "aim_context": aim_context, "fire": False, "plant": False, "defuse": False, "utility": utility, "label": "retake"}

    defended_site = choose_ct_defended_site(dust2, self_agent)
    has_recent_seen = self_agent.last_seen_tick is not None and state.tick - self_agent.last_seen_tick <= config.ticks_for_seconds(3.5)
    has_recent_sound = self_agent.last_sound_tick is not None and state.tick - self_agent.last_sound_tick <= config.ticks_for_seconds(2.0)
    if not has_recent_seen and not has_recent_sound:
        anchor_area = choose_ct_anchor_area(dust2, defended_site, state.tick, config)
        if should_search_point(self_agent, state, config, rng):
            aim_target = choose_clear_angle_target(dust2, path_cache, self_agent, state, anchor_area, defended_site.position, config)
            return {
                "move": "hold" if self_agent.area_id == anchor_area else "route",
                "mode": "walk",
                "target_area": anchor_area,
                "aim_target": aim_target,
                "aim_context": "clear",
                "fire": False,
                "plant": False,
                "defuse": False,
                "utility": None,
                "label": "search-point",
            }
        aim_target = choose_scan_target(self_agent, state, dust2, defended_site.position, config)
        return {
            "move": "hold" if self_agent.area_id == anchor_area else "route",
            "mode": "walk",
            "target_area": anchor_area,
            "aim_target": aim_target,
            "aim_context": "scan",
            "fire": False,
            "plant": False,
            "defuse": False,
            "utility": None,
            "label": "anchor-scan",
        }

    target_position = self_agent.last_seen_position if has_recent_seen else self_agent.last_sound_position if has_recent_sound else defended_site.position
    target_area = nearest_area_id(dust2, target_position)
    if should_contact_clear(self_agent, state, config, rng):
        aim_target = choose_clear_angle_target(dust2, path_cache, self_agent, state, target_area, target_position, config)
        return {"move": "route", "mode": "walk", "target_area": target_area, "aim_target": aim_target, "aim_context": "clear", "fire": False, "plant": False, "defuse": False, "utility": None, "label": "contact-clear"}
    aim_target, aim_context = choose_aim_target(self_agent, enemy, target_position, state, dust2, config, "search")
    utility = "fire" if self_agent.fire_available and should_throw_fire(self_agent, target_position, config, state.tick, rng) else None
    return {"move": "route", "mode": "run", "target_area": target_area, "aim_target": aim_target, "aim_context": aim_context, "fire": False, "plant": False, "defuse": False, "utility": utility, "label": "deny-plant"}


def advance_agent(
    dust2: Dust2Map,
    config: Dust2Config,
    agent: AgentState,
    action: dict[str, Any],
    path_cache: PathCache,
    events: list[dict[str, Any]],
    tick: int,
) -> AgentState:
    if not agent.is_alive:
        return replace(
            agent,
            velocity=Vec3(0.0, 0.0, 0.0),
            aim_turn_delta_deg=0.0,
            aim_pitch_turn_delta_deg=0.0,
            fire_cooldown_ticks=max(0, agent.fire_cooldown_ticks - 1),
            reload_cooldown_ticks=max(0, agent.reload_cooldown_ticks - 1),
            action_label=action["label"],
            aim_context=action["aim_context"],
        )
    aim_target = action["aim_target"]
    eye = eye_position(agent.position, config.eye_height)
    aim_delta = clamp(shortest_angle_delta(agent.aim_deg, angle_to(agent.position, aim_target)), -config.max_turn_deg_per_tick, config.max_turn_deg_per_tick)
    aim_pitch_delta = clamp(pitch_to(eye, aim_target) - agent.aim_pitch_deg, -config.max_pitch_turn_deg_per_tick, config.max_pitch_turn_deg_per_tick)
    aim_deg = normalize_deg(agent.aim_deg + aim_delta)
    aim_pitch_deg = clamp(agent.aim_pitch_deg + aim_pitch_delta, -89.0, 89.0)
    reloading = bool(action.get("reload"))
    next_ammo = (
        config.max_ammo
        if agent.reload_cooldown_ticks == 1
        else agent.ammo
    )
    next_fire_cooldown = max(0, agent.fire_cooldown_ticks - 1)
    next_reload_cooldown = max(0, agent.reload_cooldown_ticks - 1)
    if reloading and agent.ammo < config.max_ammo and agent.reload_cooldown_ticks == 0:
        next_reload_cooldown = config.reload_cooldown_ticks
        events.append({"type": "reload", "tick": tick, "side": agent.side})
    if action["plant"] or action["defuse"] or action["move"] == "hold":
        velocity = limit_velocity_change(agent.velocity, Vec3(0.0, 0.0, 0.0), config)
        return replace(
            agent,
            velocity=velocity,
            aim_deg=aim_deg,
            aim_pitch_deg=aim_pitch_deg,
            aim_turn_delta_deg=abs(aim_delta),
            aim_pitch_turn_delta_deg=abs(aim_pitch_delta),
            ammo=next_ammo,
            fire_cooldown_ticks=next_fire_cooldown,
            reload_cooldown_ticks=next_reload_cooldown,
            action_label=action["label"],
            aim_context=action["aim_context"],
            committed_ticks=agent.committed_ticks + 1 if action["plant"] or action["defuse"] else 0,
            jump_ticks=max(0, agent.jump_ticks - 1),
        )
    target_area = action.get("target_area") or agent.area_id
    route = agent.route
    route_index = agent.route_index
    if agent.target_area_id != target_area or not route:
        route = path_cache.path(agent.area_id, target_area)
        route_index = 0
    speed = config.run_speed_per_tick if action["mode"] == "run" else config.walk_speed_per_tick
    next_area_id = route[min(route_index + 1, len(route) - 1)] if route else agent.area_id
    next_area = dust2.areas.get(next_area_id, dust2.areas[agent.area_id])
    current_area = dust2.areas[agent.area_id]
    transition = classify_transition(current_area, next_area, config)
    jump_ticks = max(0, agent.jump_ticks - 1)
    if transition == "blocked":
        velocity = limit_velocity_change(agent.velocity, Vec3(0.0, 0.0, 0.0), config)
        return replace(agent, velocity=velocity, aim_deg=aim_deg, aim_pitch_deg=aim_pitch_deg, aim_turn_delta_deg=abs(aim_delta), aim_pitch_turn_delta_deg=abs(aim_pitch_delta), ammo=next_ammo, fire_cooldown_ticks=next_fire_cooldown, reload_cooldown_ticks=next_reload_cooldown, target_area_id=target_area, route=route, route_index=route_index, action_label="blocked-route", aim_context=action["aim_context"], jump_ticks=jump_ticks)
    if transition == "jump" and agent.jump_ticks == 0:
        jump_ticks = config.ticks_for_seconds(0.30)
        events.append({"type": "jump", "tick": tick, "side": agent.side, "fromArea": agent.area_id, "toArea": next_area_id, "deltaZ": round(next_area.centroid.z - current_area.centroid.z, 2)})
    target = next_area.centroid
    delta = subtract(target, agent.position)
    flat_dist = math.hypot(delta.x, delta.y)
    if flat_dist <= 1e-6:
        position = target
        area_id = next_area_id
        route_index = min(route_index + 1, len(route) - 1) if route else route_index
    else:
        ratio = min(1.0, speed / flat_dist)
        z_ratio = ratio if transition != "jump" else min(1.0, ratio * 0.65)
        desired_velocity = Vec3(delta.x * ratio, delta.y * ratio, delta.z * z_ratio)
        velocity = limit_velocity_change(agent.velocity, desired_velocity, config)
        velocity = limit_horizontal_speed(
            velocity,
            config.run_speed_per_tick,
        )
        if math.hypot(velocity.x, velocity.y) >= flat_dist:
            position = target
            area_id = next_area_id
            route_index = min(route_index + 1, len(route) - 1) if route else route_index
        else:
            position = add(agent.position, velocity)
            area_id = agent.area_id
    velocity = subtract(position, agent.position)
    return replace(
        agent,
        area_id=area_id,
        position=position,
        velocity=velocity,
        aim_deg=aim_deg,
        aim_pitch_deg=aim_pitch_deg,
        aim_turn_delta_deg=abs(aim_delta),
        aim_pitch_turn_delta_deg=abs(aim_pitch_delta),
        ammo=next_ammo,
        fire_cooldown_ticks=next_fire_cooldown,
        reload_cooldown_ticks=next_reload_cooldown,
        route=route,
        route_index=route_index,
        target_area_id=target_area,
        action_label=action["label"],
        aim_context=action["aim_context"],
        committed_ticks=0,
        jump_ticks=jump_ticks,
    )


def apply_information(
    agents: dict[Side, AgentState],
    dust2: Dust2Map,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
    tick: int,
    events: list[dict[str, Any]],
) -> dict[Side, AgentState]:
    next_agents = dict(agents)
    for side in SIDES:
        other: Side = "CT" if side == "T" else "T"
        viewer = next_agents[side]
        target = next_agents[other]
        seen = can_see(viewer, target, dust2, config, visibility, utilities)
        if seen:
            next_agents[side] = replace(viewer, last_seen_position=target.position, last_seen_tick=tick)
            if viewer.last_seen_tick != tick - 1:
                events.append({"type": "visible", "tick": tick, "viewer": side, "target": other})
        elif (
            target.is_alive
            and tick % config.sound_sample_interval_ticks == 0
            and vector_length(target.velocity) > config.walk_speed_per_tick
            and distance2(viewer.position, target.position) <= config.hearing_range
        ):
            sound_position, area_ids = coarse_sound_region(dust2, target.area_id, target.position, config)
            next_agents[side] = replace(next_agents[side], last_sound_position=sound_position, last_sound_tick=tick)
            events.append({
                "type": "sound",
                "tick": tick,
                "listener": side,
                "source": other,
                "areaIds": list(area_ids),
                "centroid": vec_payload(sound_position),
                "radius": config.sound_region_radius,
            })
    return next_agents


def maybe_deploy_utility(side: Side, agent: AgentState, action: dict[str, Any], config: Dust2Config, tick: int) -> UtilityCloud | None:
    if not config.enable_utilities:
        return None
    if action.get("utility") == "smoke" and agent.smoke_available:
        target = action["aim_target"]
        position = Vec3((agent.position.x + target.x) / 2.0, (agent.position.y + target.y) / 2.0, min(agent.position.z, target.z))
        return UtilityCloud(f"smoke-{side}-{tick}", "smoke", position, config.smoke_radius, tick, tick + config.smoke_duration_ticks, side)
    if action.get("utility") == "fire" and agent.fire_available:
        target = action["aim_target"]
        return UtilityCloud(f"fire-{side}-{tick}", "fire", target, config.fire_radius, tick, tick + config.fire_duration_ticks, side)
    return None


def apply_fire_damage(
    agents: dict[Side, AgentState],
    utilities: tuple[UtilityCloud, ...],
    config: Dust2Config,
    tick: int,
    events: list[dict[str, Any]],
) -> dict[Side, AgentState]:
    next_agents = dict(agents)
    for side, agent in agents.items():
        if not agent.is_alive:
            continue
        touching = [u for u in utilities if u.kind == "fire" and distance2(agent.position, u.position) <= u.radius]
        if not touching:
            continue
        hp = max(0.0, agent.hp - config.fire_damage_per_second * config.tick_seconds * len(touching))
        next_agents[side] = replace(agent, hp=hp, is_alive=hp > 0.0)
        events.append({"type": "fire-damage", "tick": tick, "side": side, "hp": round(hp, 3)})
    return next_agents


def apply_shots(
    agents: dict[Side, AgentState],
    previous_agents: dict[Side, AgentState],
    actions: dict[Side, dict[str, Any]],
    dust2: Dust2Map,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
    tick: int,
    rng: random.Random,
    events: list[dict[str, Any]],
) -> dict[Side, AgentState]:
    next_agents = dict(agents)
    pending_damage: dict[Side, float] = {"T": 0.0, "CT": 0.0}
    for side in SIDES:
        target_side: Side = "CT" if side == "T" else "T"
        shooter = next_agents[side]
        target = next_agents[target_side]
        if not actions[side].get("fire") or actions[side].get("reload") or not shooter.is_alive or not target.is_alive:
            continue
        if (
            previous_agents[side].fire_cooldown_ticks > 0
            or previous_agents[side].reload_cooldown_ticks > 0
            or shooter.ammo <= 0
        ):
            continue
        head_probability, body_probability = shot_probabilities(shooter, target, dust2, config, visibility, utilities)
        probability = head_probability + body_probability
        if (
            probability < config.min_fire_probability
            and not actions[side].get("force_fire")
        ):
            events.append({
                "type": "withheld-shot",
                "tick": tick,
                "shooter": side,
                "target": target_side,
                "probability": round(probability, 4),
                "reason": "below-fire-threshold",
            })
            continue
        roll = rng.random()
        hit_group = "miss"
        damage = 0.0
        if roll < head_probability:
            hit_group = "head"
            damage = 1.0
        elif roll < probability:
            hit_group = "body"
            damage = sample_body_damage(config, rng)
        hit = damage > 0.0
        next_agents[side] = replace(shooter, ammo=max(0, shooter.ammo - 1), fire_cooldown_ticks=config.fire_cooldown_ticks)
        events.append({
            "type": "shot",
            "tick": tick,
            "shooter": side,
            "target": target_side,
            "probability": round(probability, 4),
            "headProbability": round(head_probability, 4),
            "bodyProbability": round(body_probability, 4),
            "hit": hit,
            "hitGroup": hit_group,
            "damage": round(damage, 3),
            "targetHp": round(max(0.0, target.hp - damage), 3),
        })
        if hit:
            pending_damage[target_side] += damage
    for side, damage in pending_damage.items():
        if damage <= 0.0:
            continue
        agent = next_agents[side]
        hp = max(0.0, agent.hp - damage)
        next_agents[side] = replace(agent, hp=hp, is_alive=hp > 0.0, velocity=Vec3(0.0, 0.0, 0.0) if hp <= 0.0 else agent.velocity)
    return next_agents


def apply_bomb_objective(
    bomb: BombState,
    agents: dict[Side, AgentState],
    actions: dict[Side, dict[str, Any]],
    dust2: Dust2Map,
    config: Dust2Config,
    tick: int,
    events: list[dict[str, Any]],
) -> BombState:
    site = dust2.bomb_sites[bomb.site_id]
    if not bomb.planted:
        physical_site = next(
            (
                candidate
                for candidate in dust2.bomb_sites.values()
                if is_on_bomb_site(dust2, candidate, agents["T"])
            ),
            None,
        )
        if (
            actions["T"]["plant"]
            and physical_site is not None
            and physical_site.site_id != bomb.site_id
        ):
            bomb = replace(
                bomb,
                site_id=physical_site.site_id,
                plant_progress_ticks=0,
            )
            site = physical_site
        can_plant = (
            agents["T"].is_alive
            and actions["T"]["plant"]
            and physical_site is not None
            and vector_length(agents["T"].velocity) <= config.stationary_commit_speed_per_tick
        )
        progress = bomb.plant_progress_ticks + 1 if can_plant else 0
        if can_plant:
            events.append({"type": "plant-progress", "tick": tick, "progressTicks": progress, "requiredTicks": config.plant_ticks})
        if progress >= config.plant_ticks:
            events.append({"type": "bomb-planted", "tick": tick, "site": bomb.site_id, "areaId": agents["T"].area_id, "position": vec_payload(agents["T"].position)})
            return BombState(bomb.site_id, True, False, agents["T"].position, tick, 0, 0)
        return replace(bomb, plant_progress_ticks=progress, defuse_progress_ticks=0)
    if bomb.defused:
        return bomb
    bomb_position = bomb.position or site.position
    can_defuse = (
        agents["CT"].is_alive
        and actions["CT"]["defuse"]
        and distance2(agents["CT"].position, bomb_position) <= site.radius * 0.55
        and vector_length(agents["CT"].velocity) <= config.stationary_commit_speed_per_tick
    )
    progress = bomb.defuse_progress_ticks + 1 if can_defuse else 0
    if can_defuse:
        events.append({"type": "defuse-progress", "tick": tick, "progressTicks": progress, "requiredTicks": config.defuse_ticks})
    if progress >= config.defuse_ticks:
        events.append({"type": "bomb-defused", "tick": tick})
        return replace(bomb, planted=False, defused=True, defuse_progress_ticks=progress)
    return replace(bomb, plant_progress_ticks=0, defuse_progress_ticks=progress)


def bomb_explosion_event(
    agents: dict[Side, AgentState],
    bomb: BombState,
    dust2: Dust2Map,
    config: Dust2Config,
    tick: int,
) -> dict[str, Any]:
    site = dust2.bomb_sites[bomb.site_id]
    position = bomb.position or site.position
    affected: list[dict[str, Any]] = []
    for side, agent in agents.items():
        distance = distance3(agent.position, position)
        if distance > config.bomb_explosion_radius:
            continue
        falloff = max(0.0, 1.0 - distance / config.bomb_explosion_radius)
        damage = config.bomb_explosion_max_damage * falloff * falloff
        affected.append({"side": side, "distance": round(distance, 1), "damage": round(damage, 3)})
    return {
        "type": "bomb-exploded",
        "tick": tick,
        "position": vec_payload(position),
        "radius": config.bomb_explosion_radius,
        "affected": affected,
    }


def resolve_terminal(
    agents: dict[Side, AgentState],
    bomb: BombState,
    tick: int,
    config: Dust2Config,
    death_tick: int | None,
) -> Terminal | None:
    t_alive = agents["T"].is_alive
    ct_alive = agents["CT"].is_alive
    death_grace_expired = (
        death_tick is not None
        and tick - death_tick >= config.death_grace_ticks
    )
    if bomb.defused:
        return Terminal("bomb-defused", "CT", tick)
    if bomb.planted and bomb.planted_at_tick is not None and tick - bomb.planted_at_tick >= config.bomb_timer_ticks:
        return Terminal("bomb-exploded", "T", tick)
    if bomb.planted:
        if not ct_alive and death_grace_expired:
            return Terminal("ct-eliminated-after-plant", "T", tick)
        return None
    if not t_alive and death_grace_expired:
        return Terminal("t-eliminated-before-plant", "CT", tick)
    if not ct_alive and death_grace_expired:
        return Terminal("ct-eliminated-before-plant", "T", tick)
    if t_alive and ct_alive and tick >= config.round_ticks:
        return Terminal("t-timeout-no-plant", "CT", tick)
    return None


def tick_metrics(
    state: RoundState,
    actions: dict[Side, dict[str, Any]],
    dust2: Dust2Map,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {"tick": state.tick}
    for side in SIDES:
        agent = state.agents[side]
        other = state.agents["CT" if side == "T" else "T"]
        metrics[side] = {
            "alive": agent.is_alive,
            "speed": round(vector_length(agent.velocity), 4),
            "areaId": agent.area_id,
            "action": agent.action_label,
            "aimContext": agent.aim_context,
            "macroIntent": agent.macro_intent,
            "siteRotateCount": agent.site_rotate_count,
            "aimGood": agent.aim_context in {"enemy", "last_seen", "path", "contact", "site", "bomb", "retake", "scan", "search", "clear", "watch"},
            "enemyVisible": can_see(agent, other, dust2, config, visibility, utilities),
            "plant": bool(actions[side]["plant"]),
            "defuse": bool(actions[side]["defuse"]),
            "reload": bool(actions[side].get("reload")),
        }
    return metrics


def progress_attempt_ranges(events: list[dict[str, Any]], event_type: str) -> list[tuple[int, int, int]]:
    ticks = sorted(int(event["tick"]) for event in events if event.get("type") == event_type)
    if not ticks:
        return []
    ranges: list[tuple[int, int, int]] = []
    start = ticks[0]
    previous = ticks[0]
    for tick in ticks[1:]:
        if tick == previous + 1:
            previous = tick
            continue
        ranges.append((start, previous, previous - start + 1))
        start = previous = tick
    ranges.append((start, previous, previous - start + 1))
    return ranges


def summarize_behavior(
    metrics: list[dict[str, Any]],
    events: list[dict[str, Any]],
    state: RoundState,
    config: Dust2Config,
) -> dict[str, Any]:
    aim_good = 0
    aim_total = 0
    low_speed_ticks = {"T": 0, "CT": 0}
    objective_commitment_ticks = 0
    jump_count = 0
    for row in metrics:
        for side in SIDES:
            side_row = row.get(side, {})
            if side_row.get("alive"):
                aim_total += 1
                aim_good += 1 if side_row.get("aimGood") else 0
                if float(side_row.get("speed", 0.0)) <= config.stall_speed_units_per_tick and side_row.get("action") not in {"plant", "defuse", "post-plant-hold", "post-plant-close", "post-plant-wide", "engage-visible", "line-up-shot", "reload", "macro-pause", "clear-before-plant", "anchor-scan", "break-contact", "improve-angle", "search-point", "route-clear", "contact-clear"}:
                    low_speed_ticks[side] += 1
                if side_row.get("plant") or side_row.get("defuse"):
                    objective_commitment_ticks += 1
    event_types = [event["type"] for event in events]
    jump_count = event_types.count("jump")
    plant_attempts = progress_attempt_ranges(events, "plant-progress")
    defuse_attempts = progress_attempt_ranges(events, "defuse-progress")
    objective_spam_ticks = sum(max(0, length - config.plant_ticks) for _, _, length in plant_attempts)
    objective_spam_ticks += sum(max(0, length - config.defuse_ticks) for _, _, length in defuse_attempts)
    if len(plant_attempts) > 3:
        objective_spam_ticks += (len(plant_attempts) - 3) * config.plant_ticks
    if len(defuse_attempts) > 2:
        objective_spam_ticks += (len(defuse_attempts) - 2) * config.defuse_ticks
    aim_quality_ratio = aim_good / aim_total if aim_total else 1.0
    terminal_winner = state.terminal.winner if state.terminal else None
    terminal_reason = state.terminal.reason if state.terminal else None
    return {
        "passed": (
            terminal_winner in {"T", "CT"}
            and terminal_reason != "t-timeout-no-plant"
            and aim_quality_ratio >= config.aim_quality_threshold
            and objective_spam_ticks == 0
            and max(low_speed_ticks.values() or [0]) < config.round_ticks * 0.45
        ),
        "draw_rate": 0.0 if terminal_winner in {"T", "CT"} else 1.0,
        "aim_quality_ratio": round(aim_quality_ratio, 4),
        "aim_quality_threshold": config.aim_quality_threshold,
        "low_speed_ticks": low_speed_ticks,
        "objective_commitment_ticks": objective_commitment_ticks,
        "objective_spam_ticks": objective_spam_ticks,
        "plant_attempts": [list(row) for row in plant_attempts],
        "defuse_attempts": [list(row) for row in defuse_attempts],
        "jump_or_climb_transitions": jump_count,
        "smoke_deployed": "smoke" in event_types,
        "fire_deployed": "fire" in event_types,
        "bomb_planted": "bomb-planted" in event_types,
        "visible_engagement": "visible" in event_types and "shot" in event_types,
        "terminal_has_winner": terminal_winner in {"T", "CT"},
        "event_counts": {kind: event_types.count(kind) for kind in sorted(set(event_types))},
    }


def can_see(
    viewer: AgentState,
    target: AgentState,
    dust2: Dust2Map,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
) -> bool:
    if not viewer.is_alive or not target.is_alive:
        return False
    if distance3(viewer.position, target.position) > config.vision_range:
        return False
    start = eye_position(viewer.position, config.eye_height)
    for end in target_visibility_points(viewer.position, target.position, config):
        if view_angle_error_deg(viewer, start, end) > config.fov_deg / 2.0:
            continue
        if any(u.kind == "smoke" and segment_intersects_circle(start, end, u.position, u.radius) for u in utilities):
            continue
        if visibility.visible(start, end):
            return True
    return False


def target_visibility_points(viewer_position: Vec3, target_position: Vec3, config: Dust2Config) -> tuple[Vec3, ...]:
    dx = target_position.x - viewer_position.x
    dy = target_position.y - viewer_position.y
    length = max(math.hypot(dx, dy), 1e-6)
    offset_x = -dy / length * config.visibility_shoulder_radius
    offset_y = dx / length * config.visibility_shoulder_radius
    head = target_head_point(target_position, config)
    chest = default_aim_point(target_position, config)
    shoulder_z = target_position.z + config.eye_height * 0.72
    left_shoulder = Vec3(target_position.x + offset_x, target_position.y + offset_y, shoulder_z)
    right_shoulder = Vec3(target_position.x - offset_x, target_position.y - offset_y, shoulder_z)
    return head, chest, left_shoulder, right_shoulder


def physical_los_between(
    start_position: Vec3,
    target_position: Vec3,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
) -> bool:
    start = eye_position(start_position, config.eye_height)
    for end in target_visibility_points(start_position, target_position, config):
        if any(u.kind == "smoke" and segment_intersects_circle(start, end, u.position, u.radius) for u in utilities):
            continue
        if visibility.visible(start, end):
            return True
    return False


def hit_probability(
    shooter: AgentState,
    target: AgentState,
    dust2: Dust2Map,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
) -> float:
    head_probability, body_probability = shot_probabilities(shooter, target, dust2, config, visibility, utilities)
    return head_probability + body_probability


def target_hit_samples(viewer_position: Vec3, target_position: Vec3, config: Dust2Config) -> tuple[HitSample, ...]:
    dx = target_position.x - viewer_position.x
    dy = target_position.y - viewer_position.y
    length = max(math.hypot(dx, dy), 1e-6)
    right_x = -dy / length
    right_y = dx / length
    head_center = target_head_point(target_position, config)
    body_top, body_bottom = target_body_segment(target_position, config)
    body_mid = default_aim_point(target_position, config)
    samples: list[HitSample] = [
        HitSample("head", head_center, config.ak_head_radius, 1.0),
        HitSample("head", Vec3(head_center.x + right_x * config.ak_head_radius, head_center.y + right_y * config.ak_head_radius, head_center.z), config.ak_head_radius * 0.55, 0.84),
        HitSample("head", Vec3(head_center.x - right_x * config.ak_head_radius, head_center.y - right_y * config.ak_head_radius, head_center.z), config.ak_head_radius * 0.55, 0.84),
    ]
    body_r = config.body_hit_radius
    for z_ratio, priority in ((0.72, 0.92), (0.60, 0.88), (0.48, 0.82), (0.34, 0.68), (0.22, 0.5)):
        z = target_position.z + config.eye_height * z_ratio
        center = Vec3(target_position.x, target_position.y, z)
        edge_radius = body_r * 0.45
        samples.append(HitSample("body", center, body_r, priority))
        samples.append(HitSample("body", Vec3(center.x + right_x * body_r, center.y + right_y * body_r, center.z), edge_radius, priority * 0.82))
        samples.append(HitSample("body", Vec3(center.x - right_x * body_r, center.y - right_y * body_r, center.z), edge_radius, priority * 0.82))
    samples.append(HitSample("body", body_top, body_r * 0.7, 0.78))
    samples.append(HitSample("body", body_mid, body_r, 0.86))
    samples.append(HitSample("body", body_bottom, body_r * 0.65, 0.46))
    return tuple(samples)


def visible_hit_samples(
    viewer_position: Vec3,
    target_position: Vec3,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
) -> tuple[HitSample, ...]:
    origin = eye_position(viewer_position, config.eye_height)
    return tuple(sample for sample in target_hit_samples(viewer_position, target_position, config) if line_of_fire_clear(origin, sample.point, visibility, utilities))


def visible_combat_aim_point(
    shooter: AgentState,
    target: AgentState,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
) -> Vec3:
    samples = visible_hit_samples(shooter.position, target.position, config, visibility, utilities)
    if not samples:
        return combat_aim_point(target, config)
    current_direction = aim_direction(shooter.aim_deg, shooter.aim_pitch_deg)
    origin = eye_position(shooter.position, config.eye_height)
    head_samples = [sample for sample in samples if sample.group == "head"]
    pool = head_samples if head_samples else [sample for sample in samples if sample.group == "body"]
    best = min(
        pool,
        key=lambda sample: (
            -sample.priority,
            closest_distance_ray_point(origin, current_direction, sample.point),
            distance3(origin, sample.point),
        ),
    )
    return best.point


def min_sample_overage(origin: Vec3, direction: Vec3, samples: list[HitSample]) -> float:
    if not samples:
        return float("inf")
    return min(max(0.0, closest_distance_ray_point(origin, direction, sample.point) - sample.radius) for sample in samples)


def shot_probabilities(
    shooter: AgentState,
    target: AgentState,
    dust2: Dust2Map,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
) -> tuple[float, float]:
    if not shooter.is_alive or not target.is_alive:
        return 0.0, 0.0
    origin = eye_position(shooter.position, config.eye_height)
    direction = aim_direction(shooter.aim_deg, shooter.aim_pitch_deg)
    samples = visible_hit_samples(shooter.position, target.position, config, visibility, utilities)
    head_samples = [sample for sample in samples if sample.group == "head"]
    body_samples = [sample for sample in samples if sample.group == "body"]
    if not head_samples and not body_samples:
        return 0.0, 0.0
    body_center = default_aim_point(target.position, config)
    d = max(distance3(origin, body_center), 1e-6)
    head_over = min_sample_overage(origin, direction, head_samples)
    body_over = min_sample_overage(origin, direction, body_samples)
    movement_penalty = movement_accuracy_penalty(shooter, config)
    turn_penalty = turn_accuracy_penalty(shooter, config)
    penalty = movement_penalty * turn_penalty
    distance_softening = clamp(d / 1800.0, 0.18, 1.25)
    head_sigma = max(1.0, config.ak_head_radius * (0.65 + distance_softening))
    body_sigma = max(2.5, config.body_hit_radius * (0.72 + distance_softening))
    head_probability = config.ak_head_hit_max * penalty * math.exp(-((head_over / head_sigma) ** 2)) if head_samples else 0.0
    body_probability = config.ak_body_hit_max * penalty * math.exp(-((body_over / body_sigma) ** 2)) if body_samples else 0.0
    head_probability = clamp(head_probability, 0.0, config.ak_head_hit_max)
    body_probability = clamp(body_probability, 0.0, config.ak_body_hit_max)
    total = head_probability + body_probability
    if total > config.p_hit_max and total > 0.0:
        scale = config.p_hit_max / total
        head_probability *= scale
        body_probability *= scale
    return head_probability, body_probability


def movement_accuracy_penalty(agent: AgentState, config: Dust2Config) -> float:
    speed = vector_length(agent.velocity)
    if speed > config.walk_speed_per_tick:
        return config.ak_run_accuracy_penalty
    if speed > config.stall_speed_units_per_tick:
        return config.ak_walk_accuracy_penalty
    return 1.0


def turn_accuracy_penalty(agent: AgentState, config: Dust2Config) -> float:
    turn_delta = math.hypot(agent.aim_turn_delta_deg, agent.aim_pitch_turn_delta_deg)
    penalty = math.exp(-turn_delta * config.ak_turn_penalty_per_deg)
    return clamp(penalty, config.ak_turn_penalty_floor, 1.0)


def sample_body_damage(config: Dust2Config, rng: random.Random) -> float:
    return rng.triangular(config.ak_body_damage_min, config.ak_body_damage_max, config.ak_body_damage_mode)


def choose_aim_target(
    agent: AgentState,
    enemy: AgentState,
    fallback: Vec3,
    state: RoundState,
    dust2: Dust2Map,
    config: Dust2Config,
    mode: str,
) -> tuple[Vec3, str]:
    if agent.last_seen_position is not None and agent.last_seen_tick is not None and state.tick - agent.last_seen_tick <= config.ticks_for_seconds(1.8):
        return default_aim_point(agent.last_seen_position, config), "last_seen"
    if agent.last_sound_position is not None and agent.last_sound_tick is not None and state.tick - agent.last_sound_tick <= config.ticks_for_seconds(2.0):
        sound_area = nearest_area_id(dust2, agent.last_sound_position)
        if sound_area == agent.area_id or sound_area in dust2.graph.get(agent.area_id, ()):
            return default_aim_point(dust2.areas[sound_area].centroid, config), "contact"
        if agent.route and agent.route_index + 1 < len(agent.route):
            return default_aim_point(dust2.areas[agent.route[agent.route_index + 1]].centroid, config), "path"
        return choose_scan_target(agent, state, dust2, fallback, config), "scan"
    if agent.route and agent.route_index + 1 < len(agent.route):
        return default_aim_point(dust2.areas[agent.route[agent.route_index + 1]].centroid, config), "path"
    context = "retake" if mode == "retake" else "site" if mode in {"search", "path"} else "contact"
    return default_aim_point(fallback, config) if context in {"site", "contact", "retake"} else fallback, context


def should_seek_cover(agent: AgentState, enemy: AgentState, state: RoundState, visible_enemy: bool, config: Dust2Config, rng: random.Random) -> bool:
    if agent.hp > 0.68 or not enemy.is_alive:
        return False
    if agent.action_label == "break-contact" and agent.target_area_id and agent.target_area_id != agent.area_id:
        return True
    recent_seen = agent.last_seen_tick is not None and state.tick - agent.last_seen_tick <= config.ticks_for_seconds(1.8)
    recent_sound = agent.last_sound_tick is not None and state.tick - agent.last_sound_tick <= config.ticks_for_seconds(2.0)
    if not (visible_enemy or recent_seen or recent_sound):
        return False
    probability = 0.52 if visible_enemy else 0.28
    if agent.side == "T" and not state.bomb.planted and agent.hp > 0.35:
        probability *= 0.45
    return rng.random() < probability


def choose_cover_area(
    dust2: Dust2Map,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
    agent: AgentState,
    enemy: AgentState,
    rng: random.Random,
) -> str:
    candidates = {agent.area_id}
    for neighbor in dust2.graph.get(agent.area_id, ()):
        if neighbor in dust2.areas:
            candidates.add(neighbor)
            candidates.update(next_id for next_id in dust2.graph.get(neighbor, ()) if next_id in dust2.areas)
    scored: list[tuple[float, str]] = []
    for area_id in candidates:
        area = dust2.areas[area_id]
        exposed = physical_los_between(enemy.position, area.centroid, config, visibility, utilities)
        distance_from_enemy = distance2(enemy.position, area.centroid)
        distance_from_self = distance2(agent.position, area.centroid)
        score = (0.0 if exposed else 10000.0) + distance_from_enemy - distance_from_self * 0.45 + rng.uniform(-8.0, 8.0)
        scored.append((score, area_id))
    scored.sort(reverse=True)
    return scored[0][1] if scored else agent.area_id


def has_recent_contact(agent: AgentState, state: RoundState, config: Dust2Config, *, seen_seconds: float = 3.0, sound_seconds: float = 2.0) -> bool:
    seen_ticks = config.ticks_for_seconds(seen_seconds)
    sound_ticks = config.ticks_for_seconds(sound_seconds)
    return (
        (agent.last_seen_tick is not None and state.tick - agent.last_seen_tick <= seen_ticks)
        or (agent.last_sound_tick is not None and state.tick - agent.last_sound_tick <= sound_ticks)
    )


def recent_contact_position(agent: AgentState, state: RoundState, config: Dust2Config) -> Vec3 | None:
    seen_age = state.tick - agent.last_seen_tick if agent.last_seen_tick is not None else math.inf
    sound_age = state.tick - agent.last_sound_tick if agent.last_sound_tick is not None else math.inf
    if agent.last_seen_position is not None and seen_age <= sound_age and seen_age <= config.ticks_for_seconds(3.0):
        return agent.last_seen_position
    if agent.last_sound_position is not None and sound_age <= config.ticks_for_seconds(2.0):
        return agent.last_sound_position
    return None


def should_contact_clear(agent: AgentState, state: RoundState, config: Dust2Config, rng: random.Random) -> bool:
    if not has_recent_contact(agent, state, config):
        return False
    contact_period = config.ticks_for_seconds(1.1)
    if agent.action_label == "contact-clear" and state.tick % contact_period < config.contact_clear_hold_ticks:
        return True
    seen_period = config.ticks_for_seconds(2.0)
    sound_period = config.ticks_for_seconds(2.4)
    seen_offset = config.ticks_for_seconds(0.25)
    sound_offset = config.ticks_for_seconds(0.30)
    if agent.last_seen_tick is not None and state.tick - agent.last_seen_tick <= config.ticks_for_seconds(1.8):
        return seen_offset <= state.tick % seen_period <= seen_offset + config.contact_clear_hold_ticks or rng.random() < 0.055
    if agent.last_sound_tick is not None and state.tick - agent.last_sound_tick <= config.ticks_for_seconds(1.4):
        return sound_offset <= state.tick % sound_period <= sound_offset + config.contact_clear_hold_ticks or rng.random() < 0.035
    return False


def choose_scan_target(agent: AgentState, state: RoundState, dust2: Dust2Map, fallback: Vec3, config: Dust2Config) -> Vec3:
    candidates = [area_id for area_id in dust2.graph.get(agent.area_id, ()) if area_id in dust2.areas]
    if agent.route and agent.route_index + 1 < len(agent.route):
        candidates.append(agent.route[agent.route_index + 1])
    if not candidates:
        return fallback
    forward_angle = angle_to(agent.position, fallback)
    ordered = sorted(
        set(candidates),
        key=lambda area_id: (
            abs(shortest_angle_delta(forward_angle, angle_to(agent.position, dust2.areas[area_id].centroid))),
            distance2(dust2.areas[area_id].centroid, fallback),
            area_id,
        ),
    )
    return default_aim_point(dust2.areas[ordered[(state.tick // config.ticks_for_seconds(0.9)) % len(ordered)]].centroid, config)


def should_search_point(agent: AgentState, state: RoundState, config: Dust2Config, rng: random.Random) -> bool:
    if agent.last_seen_tick is not None and state.tick - agent.last_seen_tick <= config.ticks_for_seconds(1.8):
        return False
    if agent.last_sound_tick is not None and state.tick - agent.last_sound_tick <= config.ticks_for_seconds(1.4):
        return False
    if state.tick < config.ticks_for_seconds(0.5) or state.tick > config.round_ticks * 0.75:
        return False
    window = state.tick % config.route_clear_interval_ticks
    route_offset = config.ticks_for_seconds(0.45)
    if agent.action_label in {"route-clear", "search-point"} and route_offset <= window <= route_offset + config.route_clear_hold_ticks:
        return True
    intent_bonus = 0.012 if agent.macro_intent.startswith(("slow-clear", "fake-pressure")) or agent.side == "CT" else 0.004
    return route_offset <= window <= route_offset + config.route_clear_hold_ticks or rng.random() < intent_bonus


def choose_clear_angle_target(
    dust2: Dust2Map,
    path_cache: PathCache,
    agent: AgentState,
    state: RoundState,
    target_area: str,
    fallback: Vec3,
    config: Dust2Config,
) -> Vec3:
    route = agent.route if agent.target_area_id == target_area and agent.route else path_cache.path(agent.area_id, target_area)
    route_window = set(route[agent.route_index : min(len(route), agent.route_index + 4)]) if route else {agent.area_id}
    anchors = [agent.area_id]
    if route and agent.route_index + 1 < len(route):
        anchors.append(route[agent.route_index + 1])
    candidates: list[str] = []
    for anchor in anchors:
        for neighbor in dust2.graph.get(anchor, ()):
            if neighbor in dust2.areas and neighbor not in route_window:
                candidates.append(neighbor)
    if not candidates:
        return choose_scan_target(agent, state, dust2, fallback, config)
    forward_angle = angle_to(agent.position, fallback)
    recent_contact = has_recent_contact(agent, state, config)
    ordered = sorted(
        set(candidates),
        key=lambda area_id: (
            map_control_angle_penalty(dust2, agent, area_id, forward_angle, recent_contact),
            distance2(dust2.areas[area_id].centroid, fallback),
            area_id,
        ),
    )
    return default_aim_point(dust2.areas[ordered[(state.tick // config.ticks_for_seconds(0.6)) % len(ordered)]].centroid, config)


def map_control_angle_penalty(dust2: Dust2Map, agent: AgentState, area_id: str, forward_angle: float, recent_contact: bool) -> float:
    area = dust2.areas[area_id]
    delta = abs(shortest_angle_delta(forward_angle, angle_to(agent.position, area.centroid)))
    hard_limit = 145.0 if recent_contact else 112.0
    return delta + (220.0 if delta > hard_limit else 0.0)


def choose_path_search_target(
    dust2: Dust2Map,
    path_cache: PathCache,
    agent: AgentState,
    state: RoundState,
    target_area: str,
    fallback: Vec3,
    config: Dust2Config,
) -> Vec3:
    return choose_clear_angle_target(dust2, path_cache, agent, state, target_area, fallback, config)


def choose_site_watch_target(
    dust2: Dust2Map,
    path_cache: PathCache,
    agent: AgentState,
    state: RoundState,
    site: BombSite,
    config: Dust2Config,
) -> Vec3:
    site_area = site_representative_area_id(dust2, site)
    candidates = site_watch_candidate_area_ids(dust2, site_area)
    candidates.discard(agent.area_id)
    if not candidates:
        return choose_scan_target(agent, state, dust2, site.position, config)
    scored: list[tuple[float, str]] = []
    for area_id in candidates:
        area = dust2.areas[area_id]
        path = path_cache.path(agent.area_id, area_id)
        path_cost = path_distance(dust2, path) if path else distance2(agent.position, area.centroid)
        site_distance = distance2(site.position, area.centroid)
        score = path_cost + site_distance * 0.35
        scored.append((score, area_id))
    scored.sort(key=lambda row: (row[0], row[1]))
    index = (state.tick // config.ticks_for_seconds(1.5)) % min(len(scored), 4)
    return default_aim_point(dust2.areas[scored[index][1]].centroid, config)


def site_watch_candidate_area_ids(dust2: Dust2Map, site_area: str) -> set[str]:
    candidates = set(area_id for area_id in dust2.graph.get(site_area, ()) if area_id in dust2.areas)
    for neighbor in tuple(candidates):
        candidates.update(next_id for next_id in dust2.graph.get(neighbor, ()) if next_id in dust2.areas)
    return candidates


def visible_watch_targets_from_position(
    position: Vec3,
    candidates: Iterable[str],
    dust2: Dust2Map,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
) -> tuple[tuple[str, Vec3], ...]:
    start = eye_position(position, config.eye_height)
    visible_targets: list[tuple[str, Vec3]] = []
    for area_id in candidates:
        area = dust2.areas.get(area_id)
        if area is None:
            continue
        target = default_aim_point(area.centroid, config)
        if any(u.kind == "smoke" and segment_intersects_circle(start, target, u.position, u.radius) for u in utilities):
            continue
        if visibility.visible(start, target):
            visible_targets.append((area_id, target))
    return tuple(visible_targets)


def choose_ct_defended_site(dust2: Dust2Map, agent: AgentState) -> BombSite:
    return min(dust2.bomb_sites.values(), key=lambda site: distance2(agent.position, site.position))


def choose_ct_anchor_area(dust2: Dust2Map, site: BombSite, tick: int, config: Dust2Config) -> str:
    site_area = site_representative_area_id(dust2, site)
    candidates = [site_area] + [area_id for area_id in dust2.graph.get(site_area, ()) if area_id in dust2.areas]
    ordered = sorted(set(candidates), key=lambda area_id: distance2(dust2.areas[area_id].centroid, site.position))
    if not ordered:
        return site_area
    return ordered[(tick // config.ticks_for_seconds(6.0)) % len(ordered)]


def should_throw_smoke(agent: AgentState, site_position: Vec3, tick: int, config: Dust2Config, rng: random.Random) -> bool:
    if tick < config.ticks_for_seconds(0.2):
        return False
    distance_to_site = distance2(agent.position, site_position)
    if 320.0 <= distance_to_site <= 1550.0:
        return True
    return distance_to_site > 1550.0 and rng.random() < 0.08


def sample_t_macro_intent(rng: random.Random, bomb_state: BombStateInput, site_id: str) -> str:
    if bomb_state in {"planted_a", "planted_b"}:
        return weighted_choice((("post-plant-close", 0.55), ("post-plant-wide", 0.45)), rng)
    return weighted_choice(
        (
            (f"fast-plant-{site_id.lower()}-close", 0.30),
            (f"slow-clear-{site_id.lower()}-close", 0.28),
            (f"utility-plant-{site_id.lower()}-wide", 0.24),
            (f"fake-pressure-{site_id.lower()}-wide", 0.18),
        ),
        rng,
    )


def weighted_choice(options: tuple[tuple[str, float], ...], rng: random.Random) -> str:
    total = sum(weight for _, weight in options)
    pick = rng.random() * total
    running = 0.0
    for value, weight in options:
        running += weight
        if running >= pick:
            return value
    return options[-1][0]


def t_post_plant_style(intent: str) -> str:
    return "wide" if "wide" in intent else "close"


def t_route_mode(intent: str) -> str:
    return "walk" if intent.startswith("slow-clear") or intent.startswith("fake-pressure") else "run"


def t_route_site(dust2: Dust2Map, state: RoundState, config: Dust2Config, intent: str) -> BombSite:
    actual_site = dust2.bomb_sites[state.bomb.site_id]
    if not intent.startswith("fake-pressure"):
        return actual_site
    t_agent = state.agents["T"]
    has_recent_info = (
        (t_agent.last_seen_tick is not None and state.tick - t_agent.last_seen_tick <= config.ticks_for_seconds(3.0))
        or (t_agent.last_sound_tick is not None and state.tick - t_agent.last_sound_tick <= config.ticks_for_seconds(3.0))
    )
    if has_recent_info or state.tick > config.round_ticks * 0.28:
        return actual_site
    fake_site_id = "B" if state.bomb.site_id == "A" else "A"
    return dust2.bomb_sites[fake_site_id]


def t_has_plant_time_pressure(
    dust2: Dust2Map,
    path_cache: PathCache,
    agent: AgentState,
    site_area: str,
    state: RoundState,
    config: Dust2Config,
) -> bool:
    remaining_ticks = max(0, config.round_ticks - state.tick)
    path = path_cache.path(agent.area_id, site_area)
    travel_ticks = math.ceil(path_distance(dust2, path) / max(config.run_speed_per_tick, 1e-6)) if path else 0
    buffer_ticks = config.ticks_for_seconds(3.0)
    return travel_ticks + config.plant_ticks + buffer_ticks >= remaining_ticks


def should_macro_pause(agent: AgentState, target: Vec3, state: RoundState, config: Dust2Config) -> bool:
    if not agent.macro_intent.startswith("slow-clear"):
        return False
    if state.tick < config.ticks_for_seconds(0.5) or state.tick > config.round_ticks * 0.45:
        return False
    if agent.last_seen_tick is not None and state.tick - agent.last_seen_tick <= config.ticks_for_seconds(2.5):
        return False
    if agent.last_sound_tick is not None and state.tick - agent.last_sound_tick <= config.ticks_for_seconds(2.0):
        return False
    distance_to_target = distance2(agent.position, target)
    period = config.ticks_for_seconds(3.5)
    start = config.ticks_for_seconds(0.5)
    end = config.ticks_for_seconds(1.1)
    return 520.0 <= distance_to_target <= 1600.0 and start <= state.tick % period <= end


def should_clear_before_plant(agent: AgentState, state: RoundState, config: Dust2Config) -> bool:
    if has_recent_contact(agent, state, config, seen_seconds=2.1, sound_seconds=1.4):
        return state.tick % config.ticks_for_seconds(2.0) < config.ticks_for_seconds(0.6)
    if not agent.macro_intent.startswith("slow-clear"):
        return False
    return state.tick < config.round_ticks * 0.35 and state.tick % config.ticks_for_seconds(3.0) < config.ticks_for_seconds(0.9)


def should_throw_smoke_for_intent(agent: AgentState, site_position: Vec3, tick: int, config: Dust2Config, rng: random.Random) -> bool:
    if not should_throw_smoke(agent, site_position, tick, config, rng):
        return False
    intent = agent.macro_intent
    if intent.startswith("utility-plant") or intent.startswith("fake-pressure"):
        return True
    if intent.startswith("fast-plant"):
        return rng.random() < 0.55
    if intent.startswith("slow-clear"):
        return rng.random() < 0.2
    return rng.random() < 0.35


def should_throw_fire(agent: AgentState, bomb_position: Vec3, config: Dust2Config, tick: int, rng: random.Random) -> bool:
    if tick < config.ticks_for_seconds(0.4):
        return False
    distance_to_target = distance2(agent.position, bomb_position)
    if distance_to_target < config.fire_radius * 1.45:
        return False
    if distance_to_target <= 780.0:
        return True
    return distance_to_target <= 1250.0 and rng.random() < 0.06


def choose_hold_area(dust2: Dust2Map, path_cache: PathCache, current_area: str, site_area: str, rng: random.Random) -> str:
    neighbors = [area_id for area_id in dust2.graph.get(site_area, ()) if area_id in dust2.areas]
    if not neighbors:
        return current_area
    return rng.choice(neighbors)


def choose_postplant_hold_area(
    dust2: Dust2Map,
    path_cache: PathCache,
    agent: AgentState,
    enemy: AgentState,
    state: RoundState,
    site: BombSite,
    config: Dust2Config,
    visibility: Visibility,
    style: str = "wide",
) -> str:
    bomb_position = state.bomb.position or site.position
    site_area = site_representative_area_id(dust2, site)
    bomb_area = nearest_area_id(dust2, bomb_position)
    candidates = nearby_area_ids(dust2, (site_area, bomb_area, agent.area_id), depth=3)
    if agent.target_area_id:
        candidates.add(agent.target_area_id)
    candidates = {area_id for area_id in candidates if area_id in dust2.areas}
    if not candidates:
        return agent.area_id

    ct_route: tuple[str, ...] = ()
    if enemy.is_alive:
        ct_route = path_cache.path(enemy.area_id, bomb_area)
    ct_route_set = set(ct_route)
    ct_route_neighborhood = set(ct_route_set)
    for route_area in ct_route:
        ct_route_neighborhood.update(area_id for area_id in dust2.graph.get(route_area, ()) if area_id in dust2.areas)
    watch_candidates = site_watch_candidate_area_ids(dust2, site_area)

    ideal_distance = 620.0 if style == "close" else 980.0
    tick_bucket = state.tick // max(1, config.ticks_for_seconds(3.0))
    cheap_scored: list[tuple[float, str]] = []
    for area_id in candidates:
        area = dust2.areas[area_id]
        path = path_cache.path(agent.area_id, area_id)
        if area_id != agent.area_id and not path:
            continue
        route_cost = path_distance(dust2, path) if path else 0.0
        bomb_distance = distance2(area.centroid, bomb_position)
        if bomb_distance < 230.0:
            range_penalty = 900.0 + (230.0 - bomb_distance) * 2.0
        elif bomb_distance > 1700.0:
            range_penalty = 500.0 + (bomb_distance - 1700.0) * 0.5
        else:
            range_penalty = abs(bomb_distance - ideal_distance) * 0.22
        direct_route_penalty = 450.0 if area_id in ct_route_set else 0.0
        route_neighbor_penalty = 180.0 if area_id in ct_route_neighborhood else 0.0
        current_bonus = -40.0 if area_id == agent.area_id else 0.0
        score = route_cost * 0.55 + range_penalty + direct_route_penalty + route_neighbor_penalty + current_bonus
        cheap_scored.append((score, area_id))
    if not cheap_scored:
        return agent.area_id
    cheap_scored.sort(key=lambda row: (row[0], row[1]))
    scored: list[tuple[float, str]] = []
    for cheap_score, area_id in cheap_scored[: min(12, len(cheap_scored))]:
        area = dust2.areas[area_id]
        watches_bomb = can_watch_bomb_from_position(area.centroid, bomb_position, config, visibility, state.utilities)
        visible_watch_count = len(visible_watch_targets_from_position(area.centroid, watch_candidates, dust2, config, visibility, state.utilities))
        watch_score = -850.0 if watches_bomb else 420.0
        if visible_watch_count:
            watch_score -= min(visible_watch_count, 3) * 260.0
        else:
            watch_score += 520.0
        if watches_bomb and visible_watch_count:
            watch_score -= 220.0
        if not watches_bomb and not visible_watch_count:
            watch_score += 900.0
        if state.bomb.defuse_progress_ticks > 0 and not watches_bomb:
            watch_score += 620.0
        scored.append((cheap_score + watch_score, area_id))
    scored.sort(key=lambda row: (row[0], row[1]))
    viable = scored[: min(4, len(scored))]
    return viable[tick_bucket % len(viable)][1]


def nearby_area_ids(dust2: Dust2Map, starts: tuple[str, ...], depth: int) -> set[str]:
    seen = {area_id for area_id in starts if area_id in dust2.areas}
    frontier = set(seen)
    for _ in range(max(0, depth)):
        next_frontier: set[str] = set()
        for area_id in frontier:
            next_frontier.update(next_id for next_id in dust2.graph.get(area_id, ()) if next_id in dust2.areas and next_id not in seen)
        seen.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break
    return seen


def can_watch_bomb_from_position(
    position: Vec3,
    bomb_position: Vec3,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
) -> bool:
    start = eye_position(position, config.eye_height)
    targets = (
        default_aim_point(bomb_position, config),
        Vec3(bomb_position.x, bomb_position.y, bomb_position.z + config.eye_height * 0.82),
        Vec3(bomb_position.x, bomb_position.y, bomb_position.z + config.eye_height * 0.45),
    )
    for target in targets:
        if any(u.kind == "smoke" and segment_intersects_circle(start, target, u.position, u.radius) for u in utilities):
            continue
        if visibility.visible(start, target):
            return True
    return False


def choose_postplant_watch_target(
    dust2: Dust2Map,
    path_cache: PathCache,
    agent: AgentState,
    state: RoundState,
    site: BombSite,
    config: Dust2Config,
    visibility: Visibility,
) -> Vec3:
    contact_position = recent_contact_position(agent, state, config)
    if contact_position is not None:
        contact_area = nearest_area_id(dust2, contact_position)
        return choose_clear_angle_target(dust2, path_cache, agent, state, contact_area, contact_position, config)
    site_area = site_representative_area_id(dust2, site)
    candidates = site_watch_candidate_area_ids(dust2, site_area)
    candidates.discard(agent.area_id)
    visible_targets = visible_watch_targets_from_position(agent.position, candidates, dust2, config, visibility, state.utilities)
    if visible_targets:
        scored: list[tuple[float, str, Vec3]] = []
        for area_id, target in visible_targets:
            area = dust2.areas[area_id]
            path = path_cache.path(agent.area_id, area_id)
            path_cost = path_distance(dust2, path) if path else distance2(agent.position, area.centroid)
            site_distance = distance2(site.position, area.centroid)
            scored.append((path_cost + site_distance * 0.25, area_id, target))
        scored.sort(key=lambda row: (row[0], row[1]))
        index = (state.tick // config.ticks_for_seconds(1.5)) % min(len(scored), 4)
        return scored[index][2]
    bomb_position = state.bomb.position or site.position
    if can_watch_bomb_from_position(agent.position, bomb_position, config, visibility, state.utilities):
        return default_aim_point(bomb_position, config)
    return choose_site_watch_target(dust2, path_cache, agent, state, site, config)


def choose_t_bombsite(dust2: Dust2Map, path_cache: PathCache, t_area: str, rng: random.Random) -> str:
    scores: list[tuple[float, str]] = []
    for site_id, site in dust2.bomb_sites.items():
        target_area = site_representative_area_id(dust2, site)
        path = path_cache.path(t_area, target_area)
        path_cost = path_distance(dust2, path)
        scores.append((path_cost + rng.uniform(-120.0, 120.0), site_id))
    scores.sort(key=lambda item: item[0])
    return scores[0][1]


def shortest_path(dust2: Dust2Map, config: Dust2Config, start: str, goal: str) -> tuple[str, ...]:
    if start == goal:
        return (start,)
    queue: list[tuple[float, str]] = [(0.0, start)]
    costs: dict[str, float] = {start: 0.0}
    parents: dict[str, str | None] = {start: None}
    while queue:
        cost, area_id = heapq.heappop(queue)
        if area_id == goal:
            break
        if cost > costs.get(area_id, float("inf")):
            continue
        area = dust2.areas.get(area_id)
        if area is None:
            continue
        for next_id in dust2.graph.get(area_id, ()):
            next_area = dust2.areas.get(next_id)
            if next_area is None:
                continue
            transition = classify_transition(area, next_area, config)
            if transition == "blocked":
                continue
            penalty = 1.35 if transition == "jump" else 1.0
            next_cost = cost + distance3(area.centroid, next_area.centroid) * penalty
            if next_cost < costs.get(next_id, float("inf")):
                costs[next_id] = next_cost
                parents[next_id] = area_id
                heapq.heappush(queue, (next_cost, next_id))
    if goal not in parents:
        return ()
    path = [goal]
    node = goal
    while parents[node] is not None:
        node = parents[node]  # type: ignore[assignment]
        path.append(node)
    path.reverse()
    return tuple(path)


def path_distance(dust2: Dust2Map, path: tuple[str, ...]) -> float:
    if not path:
        return float("inf")
    total = 0.0
    for index in range(1, len(path)):
        total += distance3(dust2.areas[path[index - 1]].centroid, dust2.areas[path[index]].centroid)
    return total


def classify_transition(a: NavArea, b: NavArea, config: Dust2Config) -> str:
    dz = b.centroid.z - a.centroid.z
    flat = distance2(a.centroid, b.centroid)
    if dz > config.max_jump_up or dz < -config.max_drop:
        return "blocked"
    if dz > config.max_step_up:
        return "jump" if flat <= config.max_jump_gap else "blocked"
    return "walk"


def nearest_area_id(dust2: Dust2Map, position: Vec3) -> str:
    return min(dust2.areas.values(), key=lambda area: distance3(area.centroid, position)).area_id


def coarse_sound_region(dust2: Dust2Map, source_area_id: str, source_position: Vec3, config: Dust2Config) -> tuple[Vec3, tuple[str, ...]]:
    nearby = sorted(
        dust2.areas.values(),
        key=lambda area: (distance2(area.centroid, source_position), area.area_id),
    )
    chosen: list[NavArea] = [area for area in nearby if distance2(area.centroid, source_position) <= config.sound_region_radius]
    if len(chosen) < config.sound_region_min_areas:
        chosen = nearby[: config.sound_region_min_areas]
    elif len(chosen) > config.sound_region_min_areas * 3:
        chosen = chosen[: config.sound_region_min_areas * 3]
    if source_area_id in dust2.areas and source_area_id not in {area.area_id for area in chosen}:
        chosen.append(dust2.areas[source_area_id])
    total = sum(max(area.size, 1.0) for area in chosen)
    centroid = Vec3(
        sum(area.centroid.x * max(area.size, 1.0) for area in chosen) / total,
        sum(area.centroid.y * max(area.size, 1.0) for area in chosen) / total,
        sum(area.centroid.z * max(area.size, 1.0) for area in chosen) / total,
    )
    return centroid, tuple(area.area_id for area in chosen)


def site_representative_area_id(dust2: Dust2Map, site: BombSite) -> str:
    return min(site.area_ids, key=lambda area_id: distance3(dust2.areas[area_id].centroid, site.position))


def is_on_bomb_site(dust2: Dust2Map, site: BombSite, agent: AgentState) -> bool:
    return agent.area_id in site.area_ids


def weighted_area_choice(areas: list[NavArea], rng: random.Random) -> NavArea:
    total = sum(max(area.size, 1.0) for area in areas)
    pick = rng.random() * total
    running = 0.0
    for area in areas:
        running += max(area.size, 1.0)
        if running >= pick:
            return area
    return areas[-1]


def map_payload(dust2: Dust2Map) -> dict[str, Any]:
    image_data_url = None
    if RADAR_PATH.exists():
        encoded = base64.b64encode(RADAR_PATH.read_bytes()).decode("ascii")
        image_data_url = f"data:image/png;base64,{encoded}"
    return {
        "name": dust2.map_name,
        "metadata": dust2.metadata,
        "imageDataUrl": image_data_url,
        "areas": [
            {
                "id": area.area_id,
                "centroid": vec_payload(area.centroid),
                "pixelCentroid": area.pixel_centroid,
                "polygon": area.polygon,
                "size": area.size,
                "connections": list(area.connections),
            }
            for area in dust2.areas.values()
        ],
        "bombSites": {
            site_id: {
                "label": site.label,
                "position": vec_payload(site.position),
                "radius": site.radius,
                "areaIds": list(site.area_ids),
                "bbox": site.bbox,
                "source": site.source,
            }
            for site_id, site in dust2.bomb_sites.items()
        },
    }


def knowledge_payload() -> dict[str, Any]:
    return {
        "schemaVersion": "dust2-behavior-knowledge-0.1",
        "principle": "Normative entries are legality and realism filters only; they are not treated as unique correct tactics.",
        "observedKnowledge": {
            "source": "observed_demo",
            "status": "empty",
            "items": [],
            "notes": "Reserved for demo-mined route, aim, pause, plant, and retake distributions.",
        },
        "normativeConstraints": [
            {
                "id": "legal_nav_positions_only",
                "source": "normative_seed",
                "confidence": 0.95,
                "purpose": "legality_filter",
                "description": "Agents must start and move on legal Dust2 nav areas.",
            },
            {
                "id": "no_draw_bomb_rules",
                "source": "normative_seed",
                "confidence": 0.9,
                "purpose": "game_rule_filter",
                "description": "Bomb scenarios end with a T or CT winner through plant, defuse, timeout, or elimination rules.",
            },
            {
                "id": "aim_must_reference_plausible_target",
                "source": "normative_seed",
                "confidence": 0.65,
                "purpose": "realism_filter",
                "description": "Aim quality accepts enemy, last seen, sound/contact, path, site, bomb, or retake references; it does not prescribe a single correct angle.",
            },
            {
                "id": "movement_physics_bounds",
                "source": "normative_seed",
                "confidence": 0.75,
                "purpose": "realism_filter",
                "description": "Run, walk, jump-up, step-up, and drop limits bound movement without choosing tactical style.",
            },
        ],
    }


def frame_payload(
    state: RoundState,
    events: list[dict[str, Any]],
    tick_metric: dict[str, Any],
    config: Dust2Config | None = None,
    visibility: Visibility | None = None,
) -> dict[str, Any]:
    resolved_config = config or Dust2Config()
    return {
        "tick": state.tick,
        "seconds": state.tick * resolved_config.tick_seconds,
        "state": {
            "agents": {side: agent_payload(agent, resolved_config, visibility, state.utilities) for side, agent in state.agents.items()},
            "bomb": bomb_payload(state.bomb),
            "utilities": [utility_payload(utility) for utility in state.utilities],
            "terminal": asdict(state.terminal) if state.terminal else None,
            "deathTick": state.death_tick,
        },
        "events": events,
        "metrics": tick_metric,
    }


def config_payload(config: Dust2Config) -> dict[str, Any]:
    payload = asdict(config)
    payload.update({
        "roundTicks": config.round_ticks,
        "bombTimerTicks": config.bomb_timer_ticks,
        "plantTicks": config.plant_ticks,
        "defuseTicks": config.defuse_ticks,
        "deathGraceTicks": config.death_grace_ticks,
        "runSpeedPerTick": config.run_speed_per_tick,
        "walkSpeedPerTick": config.walk_speed_per_tick,
        "maxVelocityDeltaPerTick": config.max_velocity_delta_per_tick,
        "stationaryCommitSpeedPerTick": config.stationary_commit_speed_per_tick,
        "soundSampleIntervalTicks": config.sound_sample_interval_ticks,
    })
    return payload


def agent_payload(
    agent: AgentState,
    config: Dust2Config | None = None,
    visibility: Visibility | None = None,
    utilities: tuple[UtilityCloud, ...] = (),
) -> dict[str, Any]:
    payload = {
        "side": agent.side,
        "areaId": agent.area_id,
        "position": vec_payload(agent.position),
        "velocity": vec_payload(agent.velocity),
        "aimDeg": agent.aim_deg,
        "aim_deg": agent.aim_deg,
        "aimPitchDeg": agent.aim_pitch_deg,
        "aim_pitch_deg": agent.aim_pitch_deg,
        "aimTurnDeltaDeg": round(agent.aim_turn_delta_deg, 4),
        "aimPitchTurnDeltaDeg": round(agent.aim_pitch_turn_delta_deg, 4),
        "hp": round(agent.hp, 4),
        "isAlive": agent.is_alive,
        "is_alive": agent.is_alive,
        "ammo": agent.ammo,
        "fireCooldownTicks": agent.fire_cooldown_ticks,
        "reloadCooldownTicks": agent.reload_cooldown_ticks,
        "action": agent.action_label,
        "aimContext": agent.aim_context,
        "macroIntent": agent.macro_intent,
        "jumpTicks": agent.jump_ticks,
        "siteRotateCount": agent.site_rotate_count,
    }
    if config is not None and visibility is not None:
        endpoint, blocked = aim_ray_endpoint(agent, config, visibility, utilities)
        payload["aimRayEnd"] = vec_payload(endpoint)
        payload["aimRayBlocked"] = blocked
    return payload


def bomb_payload(bomb: BombState) -> dict[str, Any]:
    return {
        "siteId": bomb.site_id,
        "planted": bomb.planted,
        "defused": bomb.defused,
        "position": vec_payload(bomb.position) if bomb.position else None,
        "plantedAtTick": bomb.planted_at_tick,
        "plantProgressTicks": bomb.plant_progress_ticks,
        "defuseProgressTicks": bomb.defuse_progress_ticks,
    }


def utility_payload(utility: UtilityCloud) -> dict[str, Any]:
    return {
        "id": utility.utility_id,
        "kind": utility.kind,
        "position": vec_payload(utility.position),
        "radius": utility.radius,
        "startTick": utility.start_tick,
        "endTick": utility.end_tick,
        "owner": utility.owner,
    }


def vec_payload(v: Vec3 | None) -> dict[str, float] | None:
    if v is None:
        return None
    return {"x": v.x, "y": v.y, "z": v.z}


def eye_position(position: Vec3, eye_height: float) -> Vec3:
    return Vec3(position.x, position.y, position.z + eye_height)


def target_head_point(position: Vec3, config: Dust2Config) -> Vec3:
    return Vec3(position.x, position.y, position.z + config.eye_height * 0.95)


def default_aim_point(position: Vec3, config: Dust2Config) -> Vec3:
    return Vec3(position.x, position.y, position.z + config.eye_height * 0.66)


def combat_aim_point(agent: AgentState, config: Dust2Config) -> Vec3:
    return target_head_point(agent.position, config)


def target_body_segment(position: Vec3, config: Dust2Config) -> tuple[Vec3, Vec3]:
    bottom = Vec3(position.x, position.y, position.z + config.eye_height * 0.22)
    top = Vec3(position.x, position.y, position.z + config.eye_height * 0.72)
    return top, bottom


def add(a: Vec3, b: Vec3) -> Vec3:
    return Vec3(a.x + b.x, a.y + b.y, a.z + b.z)


def subtract(a: Vec3, b: Vec3) -> Vec3:
    return Vec3(a.x - b.x, a.y - b.y, a.z - b.z)


def distance2(a: Vec3, b: Vec3) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def distance3(a: Vec3, b: Vec3) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def vector_length(v: Vec3) -> float:
    return math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)


def scaled_vector(v: Vec3, scale: float) -> Vec3:
    return Vec3(v.x * scale, v.y * scale, v.z * scale)


def limit_velocity_change(current: Vec3, desired: Vec3, config: Dust2Config) -> Vec3:
    delta = subtract(desired, current)
    delta_length = vector_length(delta)
    max_delta = config.max_velocity_delta_per_tick
    if delta_length <= max_delta or delta_length <= 1e-9:
        return desired
    return add(current, scaled_vector(delta, max_delta / delta_length))


def limit_horizontal_speed(velocity: Vec3, max_speed: float) -> Vec3:
    horizontal_speed = math.hypot(velocity.x, velocity.y)
    if horizontal_speed <= max_speed or horizontal_speed <= 1e-9:
        return velocity
    scale = max_speed / horizontal_speed
    return Vec3(velocity.x * scale, velocity.y * scale, velocity.z)


def angle_to(origin: Vec3, target: Vec3) -> float:
    return normalize_deg(math.degrees(math.atan2(target.y - origin.y, target.x - origin.x)))


def pitch_to(origin: Vec3, target: Vec3) -> float:
    flat = max(math.hypot(target.x - origin.x, target.y - origin.y), 1e-6)
    return math.degrees(math.atan2(target.z - origin.z, flat))


def aim_direction(yaw_deg: float, pitch_deg: float) -> Vec3:
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    cp = math.cos(pitch)
    return Vec3(math.cos(yaw) * cp, math.sin(yaw) * cp, math.sin(pitch))


def view_angle_error_deg(agent: AgentState, origin: Vec3, target: Vec3) -> float:
    desired_yaw = angle_to(origin, target)
    desired_pitch = pitch_to(origin, target)
    return math.hypot(shortest_angle_delta(agent.aim_deg, desired_yaw), desired_pitch - agent.aim_pitch_deg)


def line_of_fire_clear(origin: Vec3, target: Vec3, visibility: Visibility, utilities: tuple[UtilityCloud, ...]) -> bool:
    if any(u.kind == "smoke" and segment_intersects_circle(origin, target, u.position, u.radius) for u in utilities):
        return False
    return visibility.visible(origin, target)


def aim_ray_endpoint(
    agent: AgentState,
    config: Dust2Config,
    visibility: Visibility,
    utilities: tuple[UtilityCloud, ...],
) -> tuple[Vec3, bool]:
    origin = eye_position(agent.position, config.eye_height)
    direction = aim_direction(agent.aim_deg, agent.aim_pitch_deg)
    max_distance = min(config.vision_range, 3400.0)
    step = 64.0
    last_visible = origin
    last_distance = 0.0
    distance = step
    while distance <= max_distance:
        point = Vec3(origin.x + direction.x * distance, origin.y + direction.y * distance, origin.z + direction.z * distance)
        if point.z < -256.0 or point.z > 512.0:
            return last_visible, True
        if line_of_fire_clear(origin, point, visibility, utilities):
            last_visible = point
            last_distance = distance
            distance += step
            continue
        low = last_distance
        high = distance
        for _ in range(7):
            mid = (low + high) / 2.0
            probe = Vec3(origin.x + direction.x * mid, origin.y + direction.y * mid, origin.z + direction.z * mid)
            if line_of_fire_clear(origin, probe, visibility, utilities):
                low = mid
                last_visible = probe
            else:
                high = mid
        return last_visible, True
    return last_visible, False


def closest_distance_ray_point(origin: Vec3, direction: Vec3, point: Vec3) -> float:
    to_point = subtract(point, origin)
    t = max(0.0, dot3(to_point, direction))
    closest = Vec3(origin.x + direction.x * t, origin.y + direction.y * t, origin.z + direction.z * t)
    return distance3(closest, point)


def closest_distance_ray_segment_sampled(origin: Vec3, direction: Vec3, a: Vec3, b: Vec3, *, samples: int) -> float:
    best = float("inf")
    count = max(2, samples)
    for i in range(count):
        ratio = i / (count - 1)
        point = Vec3(a.x + (b.x - a.x) * ratio, a.y + (b.y - a.y) * ratio, a.z + (b.z - a.z) * ratio)
        best = min(best, closest_distance_ray_point(origin, direction, point))
    return best


def dot3(a: Vec3, b: Vec3) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def normalize_deg(deg: float) -> float:
    return deg % 360.0


def shortest_angle_delta(from_deg: float, to_deg: float) -> float:
    delta = normalize_deg(to_deg - from_deg)
    return delta - 360.0 if delta > 180.0 else delta


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def segment_intersects_circle(a: Vec3, b: Vec3, center: Vec3, radius: float) -> bool:
    ax, ay = a.x, a.y
    bx, by = b.x, b.y
    dx = bx - ax
    dy = by - ay
    denom = dx * dx + dy * dy
    if denom <= 1e-9:
        return distance2(a, center) <= radius
    t = clamp(((center.x - ax) * dx + (center.y - ay) * dy) / denom, 0.0, 1.0)
    closest = Vec3(ax + dx * t, ay + dy * t, 0.0)
    return distance2(closest, center) <= radius


if __name__ == "__main__":
    main()
