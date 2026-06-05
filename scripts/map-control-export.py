#!/usr/bin/env python3
"""Export a CS2 demo into a nav-area map-control timeline for the web demo.

This is a prototype bridge around Awpy. It intentionally stays independent from
RR/PRISM: it parses positions, active smokes, and nav areas, then emits a
visualization JSON payload.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from map_control_static_cache import (
    cached_visible_ids_for_origin,
    find_nav_area_for_position,
    load_compatible_cache,
    load_nav_areas as load_static_nav_areas,
    raised_point,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
AWPY_HOME = REPO_ROOT / ".awpy-home"
SUPPORTED_MAPS = {
    "de_ancient",
    "de_dust2",
    "de_inferno",
    "de_mirage",
    "de_nuke",
    "de_overpass",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("demo", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sample-seconds", type=float, default=2.0)
    parser.add_argument("--max-frames", type=int, default=900)
    parser.add_argument("--fov-deg", type=float, default=95.0)
    parser.add_argument("--vertical-fov-deg", type=float, default=75.0)
    parser.add_argument("--vision-range", type=float, default=3200.0)
    parser.add_argument("--smoke-radius", type=float, default=144.0)
    parser.add_argument("--eye-height", type=float, default=64.0)
    parser.add_argument("--residual-seconds", type=float, default=3.0)
    parser.add_argument("--no-static-los", action="store_true")
    args = parser.parse_args()

    payload = export_demo(
        args.demo,
        sample_seconds=args.sample_seconds,
        max_frames=args.max_frames,
        fov_deg=args.fov_deg,
        vertical_fov_deg=args.vertical_fov_deg,
        vision_range=args.vision_range,
        smoke_radius=args.smoke_radius,
        eye_height=args.eye_height,
        residual_seconds=args.residual_seconds,
        static_los=not args.no_static_los,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf8")


def export_demo(
    demo_path: Path,
    *,
    sample_seconds: float,
    max_frames: int,
    fov_deg: float,
    vertical_fov_deg: float,
    vision_range: float,
    smoke_radius: float,
    eye_height: float,
    residual_seconds: float,
    static_los: bool,
) -> dict[str, Any]:
    os.environ.setdefault("HOME", str(AWPY_HOME))

    from awpy import Demo  # noqa: PLC0415

    ensure_awpy_resources()

    demo = Demo(demo_path, verbose=False)
    map_name = demo.header.get("map_name")
    if map_name not in SUPPORTED_MAPS:
        supported = ", ".join(sorted(SUPPORTED_MAPS))
        raise SystemExit(f"Unsupported map {map_name!r}. Supported maps from local dataset: {supported}.")

    demo.parse(player_props=["yaw", "pitch", "flash_duration", "is_alive"])

    tickrate = int(demo.tickrate)
    sample_stride_ticks = max(1, int(sample_seconds * tickrate))
    ticks_by_frame = sampled_ticks(demo.ticks, sample_stride_ticks, max_frames)
    nav_areas = load_static_nav_areas(map_name)
    static_info_cache = (
        load_compatible_cache(
            map_name,
            max_range=vision_range,
            eye_height=eye_height,
            target_height=eye_height,
        )
        if static_los
        else None
    )
    visibility_checker = load_visibility_checker(map_name) if static_los else None
    smokes_by_tick = active_smokes_by_sample(demo.smokes, ticks_by_frame, smoke_radius)
    residual_ticks = max(0, int(residual_seconds * tickrate))
    last_seen_by_team: dict[str, dict[str, int]] = {"T": {}, "CT": {}}

    frames = []
    for tick in ticks_by_frame:
        frame_rows = demo.ticks.filter(demo.ticks["tick"] == tick).to_dicts()
        players = [player_from_row(row, eye_height) for row in frame_rows]
        smokes = smokes_by_tick.get(tick, [])
        frame = compute_frame(
            tick=tick,
            tickrate=tickrate,
            players=players,
            nav_areas=nav_areas,
            smokes=smokes,
            fov_deg=fov_deg,
            vertical_fov_deg=vertical_fov_deg,
            vision_range=vision_range,
            eye_height=eye_height,
            residual_ticks=residual_ticks,
            last_seen_by_team=last_seen_by_team,
            visibility_checker=visibility_checker,
            static_info_cache=static_info_cache,
        )
        frames.append(frame)

    rounds = frame_to_rows(demo.rounds)
    players = players_from_ticks(demo.ticks)

    return {
        "schemaVersion": "map-control-web-0.2",
        "demo": {
            "fileName": demo_path.name,
            "mapName": map_name,
            "tickrate": tickrate,
            "sampleSeconds": sample_seconds,
            "frameCount": len(frames),
            "supportedMaps": sorted(SUPPORTED_MAPS),
            "config": {
                "fovDeg": fov_deg,
                "verticalFovDeg": vertical_fov_deg,
                "visionRange": vision_range,
                "smokeRadius": smoke_radius,
                "eyeHeight": eye_height,
                "targetHeight": eye_height,
                "residualSeconds": residual_seconds,
                "staticLos": static_los,
                "staticLosCache": static_cache_summary(static_info_cache),
            },
        },
        "map": {
            "name": map_name,
            "metadata": load_map_metadata(map_name),
            "imageUrl": f"/api/map-image/{map_name}",
            "areas": nav_areas,
        },
        "players": players,
        "rounds": rounds,
        "frames": frames,
        "events": detect_loss_events(frames, nav_areas),
    }


def ensure_awpy_resources() -> None:
    missing = []
    for folder in ["maps", "navs", "tris"]:
        if not (AWPY_HOME / ".awpy" / folder).exists():
            missing.append(folder)
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(
            f"Missing Awpy resources: {joined}. Run `HOME=\"$PWD/.awpy-home\" .venv/bin/awpy get <maps|navs|tris>`."
        )


def load_map_metadata(map_name: str) -> dict[str, Any]:
    map_data_path = AWPY_HOME / ".awpy" / "maps" / "map-data.json"
    data = json.loads(map_data_path.read_text(encoding="utf8"))
    metadata = data.get(map_name)
    if not metadata:
        raise SystemExit(f"Missing map metadata for {map_name}")
    return metadata


def load_nav_areas(map_name: str) -> list[dict[str, Any]]:
    nav_path = AWPY_HOME / ".awpy" / "navs" / f"{map_name}.json"
    nav = json.loads(nav_path.read_text(encoding="utf8"))
    metadata = load_map_metadata(map_name)

    areas: list[dict[str, Any]] = []
    for area_id, area in nav["areas"].items():
        corners = area["corners"]
        if len(corners) < 3:
            continue
        centroid = centroid_of(corners)
        polygon = [game_to_pixel(metadata, corner["x"], corner["y"]) for corner in corners]
        pixel_centroid = game_to_pixel(metadata, centroid["x"], centroid["y"])
        size = polygon_area(corners)
        areas.append(
            {
                "id": str(area_id),
                "label": f"Nav {area_id}",
                "centroid": centroid,
                "pixelCentroid": {"x": pixel_centroid[0], "y": pixel_centroid[1]},
                "polygon": [{"x": point[0], "y": point[1]} for point in polygon],
                "size": size,
                "connections": [str(x) for x in area.get("connections", [])],
            }
        )

    return areas


def load_visibility_checker(map_name: str) -> Any:
    from awpy.visibility import VisibilityChecker  # noqa: PLC0415

    tri_path = AWPY_HOME / ".awpy" / "tris" / f"{map_name}.tri"
    if not tri_path.exists():
        raise SystemExit(f"Missing visibility tri file for {map_name}: {tri_path}")
    return VisibilityChecker(path=tri_path)


def sampled_ticks(ticks_df: Any, sample_stride_ticks: int, max_frames: int) -> list[int]:
    unique_ticks = ticks_df.select("tick").unique().sort("tick")["tick"].to_list()
    if not unique_ticks:
        return []
    selected = [int(unique_ticks[0])]
    last = int(unique_ticks[0])
    for value in unique_ticks[1:]:
        tick = int(value)
        if tick - last >= sample_stride_ticks:
            selected.append(tick)
            last = tick
        if len(selected) >= max_frames:
            break
    return selected


def active_smokes_by_sample(smokes_df: Any, ticks: list[int], smoke_radius: float) -> dict[int, list[dict[str, Any]]]:
    rows = frame_to_rows(smokes_df)
    out: dict[int, list[dict[str, Any]]] = {}
    for tick in ticks:
        active = []
        for row in rows:
            if int(row["start_tick"]) <= tick <= int(row["end_tick"]):
                active.append(
                    {
                        "id": str(row.get("entity_id", "")),
                        "position": vec(row),
                        "radius": smoke_radius,
                    }
                )
        out[tick] = active
    return out


def compute_frame(
    *,
    tick: int,
    tickrate: int,
    players: list[dict[str, Any]],
    nav_areas: list[dict[str, Any]],
    smokes: list[dict[str, Any]],
    fov_deg: float,
    vertical_fov_deg: float,
    vision_range: float,
    eye_height: float,
    residual_ticks: int,
    last_seen_by_team: dict[str, dict[str, int]],
    visibility_checker: Any | None,
    static_info_cache: dict[str, Any] | None,
) -> dict[str, Any]:
    team_visible: dict[str, set[str]] = {"T": set(), "CT": set()}

    annotate_player_origin_areas(players, nav_areas)

    for area in nav_areas:
        for player in players:
            team = player["team"]
            if can_see(
                player,
                area,
                smokes,
                fov_deg,
                vertical_fov_deg,
                vision_range,
                eye_height,
                visibility_checker,
                static_info_cache,
            ):
                area_id = area["id"]
                team_visible[team].add(area_id)

    t_visible = team_visible["T"]
    ct_visible = team_visible["CT"]
    contested = sorted(t_visible & ct_visible, key=int)
    t_only = sorted(t_visible - ct_visible, key=int)
    ct_only = sorted(ct_visible - t_visible, key=int)

    round_num = None
    if players:
        round_num = players[0].get("roundNum")

    residual = update_residual_control(
        tick=tick,
        tickrate=tickrate,
        direct_visible=team_visible,
        residual_ticks=residual_ticks,
        last_seen_by_team=last_seen_by_team,
    )
    residual_ids = {entry["id"] for team in ["T", "CT"] for entry in residual[team]}

    return {
        "tick": tick,
        "seconds": tick / tickrate,
        "roundNum": round_num,
        "players": players,
        "smokes": smokes,
        "control": {
            "T": t_only,
            "CT": ct_only,
            "contested": contested,
            "vacuumCount": max(0, len(nav_areas) - len(t_visible | ct_visible)),
            "infoVacuumCount": max(0, len(nav_areas) - len(t_visible | ct_visible | residual_ids)),
        },
        "residual": residual,
    }


def update_residual_control(
    *,
    tick: int,
    tickrate: int,
    direct_visible: dict[str, set[str]],
    residual_ticks: int,
    last_seen_by_team: dict[str, dict[str, int]],
) -> dict[str, list[dict[str, Any]]]:
    for team in ["T", "CT"]:
        for area_id in direct_visible[team]:
            last_seen_by_team[team][area_id] = tick

    residual: dict[str, list[dict[str, Any]]] = {"T": [], "CT": []}
    if residual_ticks <= 0:
        return {"T": [], "CT": [], "contested": []}

    for team in ["T", "CT"]:
        expired = []
        direct = direct_visible[team]
        for area_id, last_tick in last_seen_by_team[team].items():
            if area_id in direct:
                continue
            age_ticks = tick - last_tick
            if age_ticks > residual_ticks:
                expired.append(area_id)
                continue
            confidence = max(0.0, min(1.0, 1.0 - age_ticks / residual_ticks))
            if confidence > 0:
                residual[team].append(
                    {
                        "id": area_id,
                        "confidence": round(confidence, 3),
                        "ageSeconds": round(age_ticks / tickrate, 2),
                    }
                )
        for area_id in expired:
            del last_seen_by_team[team][area_id]
        residual[team].sort(key=lambda entry: int(entry["id"]))

    t_residual = {entry["id"]: entry for entry in residual["T"]}
    ct_residual = {entry["id"]: entry for entry in residual["CT"]}
    contested = []
    for area_id in sorted(set(t_residual) & set(ct_residual), key=int):
        contested.append(
            {
                "id": area_id,
                "confidence": round(min(t_residual[area_id]["confidence"], ct_residual[area_id]["confidence"]), 3),
                "ageSeconds": round(max(t_residual[area_id]["ageSeconds"], ct_residual[area_id]["ageSeconds"]), 2),
            }
        )
    residual["contested"] = contested
    return residual


def can_see(
    player: dict[str, Any],
    target_area: dict[str, Any],
    smokes: list[dict[str, Any]],
    fov_deg: float,
    vertical_fov_deg: float,
    vision_range: float,
    eye_height: float,
    visibility_checker: Any | None,
    static_info_cache: dict[str, Any] | None,
) -> bool:
    if not player["isAlive"] or player.get("flashDuration", 0) > 0.2:
        return False
    target = raised_point(target_area["centroid"], eye_height)
    eye = {
        "x": player["position"]["x"],
        "y": player["position"]["y"],
        "z": player["position"]["z"] + eye_height,
    }
    if distance(eye, target) > vision_range:
        return False
    if not within_fov(eye, target, player["yawDeg"], fov_deg):
        return False
    if vertical_fov_deg > 0 and not within_vertical_fov(eye, target, player["pitchDeg"], vertical_fov_deg):
        return False
    if static_info_cache is not None:
        origin_area_id = player.get("originAreaId")
        use_cache = origin_area_id and not is_height_sensitive_view(player)
        cached_ids = cached_visible_ids_for_origin(static_info_cache, str(origin_area_id)) if use_cache else None
        if cached_ids is not None:
            if target_area["id"] not in cached_ids:
                return False
        elif visibility_checker is not None and not visibility_checker.is_visible(
            (eye["x"], eye["y"], eye["z"]),
            (target["x"], target["y"], target["z"]),
        ):
            return False
        elif visibility_checker is None:
            return False
    elif visibility_checker is not None and not visibility_checker.is_visible(
        (eye["x"], eye["y"], eye["z"]),
        (target["x"], target["y"], target["z"]),
    ):
        return False
    return not any(segment_intersects_sphere(eye, target, smoke["position"], smoke["radius"]) for smoke in smokes)


def annotate_player_origin_areas(players: list[dict[str, Any]], nav_areas: list[dict[str, Any]]) -> None:
    for player in players:
        if not player["isAlive"]:
            continue
        match = find_nav_area_for_position(nav_areas, player["position"])
        origin_area = match["area"]
        origin_z = float(origin_area["centroid"]["z"])
        player["originAreaId"] = origin_area["id"]
        player["originAreaMatch"] = {"type": match["type"], "distance": match["distance"]}
        player["heightDeltaFromNav"] = round(player["position"]["z"] - origin_z, 2)


def is_height_sensitive_view(player: dict[str, Any]) -> bool:
    return abs(float(player.get("heightDeltaFromNav") or 0)) >= 18.0


def static_cache_summary(cache: dict[str, Any] | None) -> dict[str, Any]:
    if cache is None:
        return {"used": False}
    stats = cache.get("stats", {})
    return {
        "used": True,
        "complete": bool(cache.get("complete")),
        "computedOriginCount": stats.get("computedOriginCount", 0),
        "missingOriginCount": stats.get("missingOriginCount", 0),
    }


def player_from_row(row: dict[str, Any], eye_height: float) -> dict[str, Any]:
    side = str(row.get("side", "")).lower()
    team = "T" if side == "t" else "CT"
    pos = vec(row)
    return {
        "steamId64": str(row.get("steamid")),
        "name": str(row.get("name")),
        "team": team,
        "side": side,
        "isAlive": bool(row.get("is_alive")),
        "position": pos,
        "eyePosition": {"x": pos["x"], "y": pos["y"], "z": pos["z"] + eye_height},
        "yawDeg": float(row.get("yaw") or 0),
        "pitchDeg": float(row.get("pitch") or 0),
        "viewPitchDeg": -float(row.get("pitch") or 0),
        "flashDuration": float(row.get("flash_duration") or 0),
        "place": str(row.get("place") or ""),
        "roundNum": int(row["round_num"]) if row.get("round_num") is not None else None,
    }


def players_from_ticks(ticks_df: Any) -> list[dict[str, Any]]:
    rows = ticks_df.select(["steamid", "name", "side"]).unique().to_dicts()
    return sorted(
        [
            {
                "steamId64": str(row.get("steamid")),
                "name": str(row.get("name")),
                "side": str(row.get("side")),
                "team": "T" if str(row.get("side")).lower() == "t" else "CT",
            }
            for row in rows
        ],
        key=lambda row: (row["team"], row["name"]),
    )


def detect_loss_events(frames: list[dict[str, Any]], nav_areas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    area_labels = {area["id"]: area["label"] for area in nav_areas}
    events = []
    for previous, current in zip(frames, frames[1:]):
        for team in ["T", "CT"]:
            before = set(previous["control"][team])
            after = set(current["control"][team]) | set(current["control"]["contested"])
            lost = sorted(before - after, key=int)
            for area_id in lost[:50]:
                events.append(
                    {
                        "team": team,
                        "areaId": area_id,
                        "label": area_labels.get(area_id, f"Nav {area_id}"),
                        "fromTick": previous["tick"],
                        "toTick": current["tick"],
                        "fromSeconds": previous["seconds"],
                        "toSeconds": current["seconds"],
                    }
                )
    return events


def within_fov(origin: dict[str, float], target: dict[str, float], yaw_deg: float, fov_deg: float) -> bool:
    dx = target["x"] - origin["x"]
    dy = target["y"] - origin["y"]
    if dx == 0 and dy == 0:
        return True
    target_yaw = math.degrees(math.atan2(dy, dx))
    return abs(shortest_angle(yaw_deg, target_yaw)) <= fov_deg / 2


def within_vertical_fov(
    origin: dict[str, float],
    target: dict[str, float],
    pitch_deg: float,
    vertical_fov_deg: float,
) -> bool:
    dx = target["x"] - origin["x"]
    dy = target["y"] - origin["y"]
    dz = target["z"] - origin["z"]
    horizontal_distance = math.hypot(dx, dy)
    if horizontal_distance == 0 and dz == 0:
        return True
    target_pitch = math.degrees(math.atan2(dz, horizontal_distance))
    # CS pitch is positive when looking down. Convert to a positive-up convention.
    view_pitch = -pitch_deg
    return abs(shortest_angle(view_pitch, target_pitch)) <= vertical_fov_deg / 2


def segment_intersects_sphere(
    start: dict[str, float],
    end: dict[str, float],
    center: dict[str, float],
    radius: float,
) -> bool:
    sx, sy, sz = start["x"], start["y"], start["z"]
    ex, ey, ez = end["x"], end["y"], end["z"]
    cx, cy, cz = center["x"], center["y"], center["z"]
    vx, vy, vz = ex - sx, ey - sy, ez - sz
    wx, wy, wz = cx - sx, cy - sy, cz - sz
    length_squared = vx * vx + vy * vy + vz * vz
    if length_squared == 0:
        return distance(start, center) <= radius
    t = max(0.0, min(1.0, (wx * vx + wy * vy + wz * vz) / length_squared))
    closest = {"x": sx + t * vx, "y": sy + t * vy, "z": sz + t * vz}
    return distance(closest, center) <= radius


def shortest_angle(a: float, b: float) -> float:
    delta = (b - a) % 360
    if delta > 180:
        delta -= 360
    return delta


def distance(a: dict[str, float], b: dict[str, float]) -> float:
    return math.sqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a["z"] - b["z"]) ** 2)


def game_to_pixel(metadata: dict[str, Any], x: float, y: float) -> tuple[float, float]:
    return ((x - metadata["pos_x"]) / metadata["scale"], (metadata["pos_y"] - y) / metadata["scale"])


def centroid_of(corners: list[dict[str, float]]) -> dict[str, float]:
    return {
        "x": sum(c["x"] for c in corners) / len(corners),
        "y": sum(c["y"] for c in corners) / len(corners),
        "z": sum(c["z"] for c in corners) / len(corners),
    }


def polygon_area(corners: list[dict[str, float]]) -> float:
    area = 0.0
    for i, current in enumerate(corners):
        nxt = corners[(i + 1) % len(corners)]
        area += current["x"] * nxt["y"] - current["y"] * nxt["x"]
    return abs(area) / 2


def vec(row: dict[str, Any]) -> dict[str, float]:
    return {
        "x": float(row.get("X") or 0),
        "y": float(row.get("Y") or 0),
        "z": float(row.get("Z") or 0),
    }


def frame_to_rows(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dicts"):
        return [jsonable(row) for row in frame.to_dicts()]
    return []


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if hasattr(value, "item"):
        return jsonable(value.item())
    return value


if __name__ == "__main__":
    main()
