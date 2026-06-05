#!/usr/bin/env python3
"""Static nav-area visibility cache for CS2 map-control analysis.

The cache answers a static question: if a player is standing on a nav area,
which other nav areas are geometrically visible with no smoke, flash, or FOV
limits applied. Runtime analysis can then layer dynamic constraints on top.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
AWPY_HOME = REPO_ROOT / ".awpy-home"
STATIC_CACHE_DIR = REPO_ROOT / ".map-control-cache" / "static-info"
SCHEMA_VERSION = "map-static-info-cache-0.1"
SUPPORTED_MAPS = {
    "de_ancient",
    "de_dust2",
    "de_inferno",
    "de_mirage",
    "de_nuke",
    "de_overpass",
}

_WORKER_AREAS: list[dict[str, Any]] = []
_WORKER_AREA_BY_ID: dict[str, dict[str, Any]] = {}
_WORKER_CHECKER: Any | None = None
_WORKER_MAX_RANGE = 3200.0
_WORKER_EYE_HEIGHT = 64.0
_WORKER_TARGET_HEIGHT = 64.0


class StaticCacheError(RuntimeError):
    """Raised when a static cache cannot answer a query."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_awpy_resources(*, require_tris: bool = False) -> None:
    missing = []
    for folder in ["maps", "navs"]:
        if not (AWPY_HOME / ".awpy" / folder).exists():
            missing.append(folder)
    if require_tris and not (AWPY_HOME / ".awpy" / "tris").exists():
        missing.append("tris")
    if missing:
        joined = ", ".join(missing)
        raise StaticCacheError(
            f"Missing Awpy resources: {joined}. Run `HOME=\"$PWD/.awpy-home\" .venv/bin/awpy get <maps|navs|tris>`."
        )


def default_cache_path(map_name: str, output_dir: Path = STATIC_CACHE_DIR) -> Path:
    return output_dir / f"{map_name}.json"


def load_map_metadata(map_name: str) -> dict[str, Any]:
    map_data_path = AWPY_HOME / ".awpy" / "maps" / "map-data.json"
    data = json.loads(map_data_path.read_text(encoding="utf8"))
    metadata = data.get(map_name)
    if not metadata:
        raise StaticCacheError(f"Missing map metadata for {map_name}")
    return metadata


def load_nav_areas(map_name: str) -> list[dict[str, Any]]:
    if map_name not in SUPPORTED_MAPS:
        supported = ", ".join(sorted(SUPPORTED_MAPS))
        raise StaticCacheError(f"Unsupported map {map_name!r}. Supported maps from local dataset: {supported}.")

    nav_path = AWPY_HOME / ".awpy" / "navs" / f"{map_name}.json"
    if not nav_path.exists():
        raise StaticCacheError(f"Missing nav file for {map_name}: {nav_path}")

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
        areas.append(
            {
                "id": str(area_id),
                "label": f"Nav {area_id}",
                "centroid": centroid,
                "pixelCentroid": {"x": pixel_centroid[0], "y": pixel_centroid[1]},
                "polygon": [{"x": point[0], "y": point[1]} for point in polygon],
                "corners": corners,
                "bbox": bbox_of(corners),
                "size": polygon_area(corners),
                "connections": [str(x) for x in area.get("connections", [])],
            }
        )

    return sorted(areas, key=lambda row: int(row["id"]))


def load_visibility_checker(map_name: str) -> Any:
    os.environ.setdefault("HOME", str(AWPY_HOME))
    from awpy.visibility import VisibilityChecker  # noqa: PLC0415

    tri_path = AWPY_HOME / ".awpy" / "tris" / f"{map_name}.tri"
    if not tri_path.exists():
        raise StaticCacheError(f"Missing visibility tri file for {map_name}: {tri_path}")
    return VisibilityChecker(path=tri_path)


def empty_cache(
    map_name: str,
    *,
    max_range: float,
    eye_height: float,
    target_height: float,
    areas: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    loaded_areas = areas if areas is not None else load_nav_areas(map_name)
    cache = {
        "schemaVersion": SCHEMA_VERSION,
        "mapName": map_name,
        "generatedAt": now_iso(),
        "updatedAt": now_iso(),
        "complete": False,
        "config": {
            "originUnit": "awpy-nav-area-centroid",
            "targetUnit": "awpy-nav-area-centroid",
            "staticLos": "awpy.VisibilityChecker",
            "fovDeg": None,
            "eyeHeight": eye_height,
            "targetHeight": target_height,
            "maxRange": max_range,
        },
        "map": {
            "metadata": load_map_metadata(map_name),
            "imageUrl": f"/api/map-image/{map_name}",
            "areas": loaded_areas,
        },
        "visibility": {},
        "stats": {},
    }
    refresh_cache_stats(cache)
    return cache


def load_cache(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf8"))


def write_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cache["updatedAt"] = now_iso()
    refresh_cache_stats(cache)
    with tempfile.NamedTemporaryFile("w", encoding="utf8", dir=path.parent, delete=False) as fh:
        tmp_path = Path(fh.name)
        json.dump(cache, fh, separators=(",", ":"))
        fh.write("\n")
    tmp_path.replace(path)


def load_compatible_cache(
    map_name: str,
    *,
    cache_dir: Path = STATIC_CACHE_DIR,
    max_range: float,
    eye_height: float,
    target_height: float,
) -> dict[str, Any] | None:
    path = default_cache_path(map_name, cache_dir)
    if not path.exists():
        return None
    cache = load_cache(path)
    if is_cache_compatible(cache, max_range=max_range, eye_height=eye_height, target_height=target_height):
        return cache
    return None


def is_cache_compatible(
    cache: dict[str, Any],
    *,
    max_range: float,
    eye_height: float,
    target_height: float,
) -> bool:
    config = cache.get("config", {})
    return (
        cache.get("schemaVersion") == SCHEMA_VERSION
        and float(config.get("maxRange", 0)) >= max_range
        and math.isclose(float(config.get("eyeHeight", -1)), eye_height)
        and math.isclose(float(config.get("targetHeight", -1)), target_height)
    )


def refresh_cache_stats(cache: dict[str, Any]) -> None:
    areas = cache.get("map", {}).get("areas", [])
    area_by_id = {area["id"]: area for area in areas}
    visibility = cache.get("visibility", {})
    visible_pair_count = sum(len(ids) for ids in visibility.values())
    visible_area_size = 0.0
    for ids in visibility.values():
        visible_area_size += sum(float(area_by_id[area_id]["size"]) for area_id in ids if area_id in area_by_id)
    computed_origin_count = len(visibility)
    area_count = len(areas)
    cache["complete"] = computed_origin_count == area_count and area_count > 0
    cache["stats"] = {
        "areaCount": area_count,
        "computedOriginCount": computed_origin_count,
        "missingOriginCount": max(0, area_count - computed_origin_count),
        "visiblePairCount": visible_pair_count,
        "avgVisibleAreas": visible_pair_count / computed_origin_count if computed_origin_count else 0,
        "avgVisibleAreaSize": visible_area_size / computed_origin_count if computed_origin_count else 0,
    }


def generate_map_cache(
    map_name: str,
    *,
    output_dir: Path = STATIC_CACHE_DIR,
    max_range: float = 3200.0,
    eye_height: float = 64.0,
    target_height: float = 64.0,
    force: bool = False,
    area_limit: int | None = None,
    origin_ids: list[str] | None = None,
    jobs: int = 1,
    checkpoint_interval: int = 25,
) -> dict[str, Any]:
    ensure_awpy_resources(require_tris=True)
    areas = load_nav_areas(map_name)
    path = default_cache_path(map_name, output_dir)

    if path.exists() and not force:
        cache = load_cache(path)
        if not is_cache_compatible(cache, max_range=max_range, eye_height=eye_height, target_height=target_height):
            raise StaticCacheError(f"Existing cache is incompatible with requested config. Use --force: {path}")
        cache.setdefault("visibility", {})
    else:
        cache = empty_cache(
            map_name,
            max_range=max_range,
            eye_height=eye_height,
            target_height=target_height,
            areas=areas,
        )

    wanted = [str(area_id) for area_id in origin_ids] if origin_ids else [area["id"] for area in areas]
    pending = [area_id for area_id in wanted if area_id not in cache["visibility"]]
    if area_limit is not None:
        pending = pending[:area_limit]
    if not pending:
        write_cache(path, cache)
        return cache

    if jobs <= 1:
        checker = load_visibility_checker(map_name)
        area_by_id = {area["id"]: area for area in areas}
        for index, origin_id in enumerate(pending, start=1):
            cache["visibility"][origin_id] = compute_area_visibility(
                area_by_id[origin_id],
                areas,
                checker,
                max_range=max_range,
                eye_height=eye_height,
                target_height=target_height,
            )
            if checkpoint_interval > 0 and index % checkpoint_interval == 0:
                write_cache(path, cache)
                print_progress(map_name, cache, path)
    else:
        with ProcessPoolExecutor(
            max_workers=jobs,
            initializer=_init_visibility_worker,
            initargs=(map_name, max_range, eye_height, target_height),
        ) as pool:
            futures = {pool.submit(_worker_compute_visibility, origin_id): origin_id for origin_id in pending}
            for index, future in enumerate(as_completed(futures), start=1):
                origin_id, visible_ids = future.result()
                cache["visibility"][origin_id] = visible_ids
                if checkpoint_interval > 0 and index % checkpoint_interval == 0:
                    write_cache(path, cache)
                    print_progress(map_name, cache, path)

    write_cache(path, cache)
    return cache


def print_progress(map_name: str, cache: dict[str, Any], path: Path) -> None:
    stats = cache.get("stats", {})
    print(
        f"{map_name}: {stats.get('computedOriginCount', 0)}/{stats.get('areaCount', 0)} origins cached -> {path}",
        flush=True,
    )


def query_map_info(
    map_name: str,
    position: dict[str, float],
    *,
    cache_dir: Path = STATIC_CACHE_DIR,
    max_range: float = 3200.0,
    eye_height: float = 64.0,
    target_height: float = 64.0,
    compute_missing: bool = False,
    include_areas: bool = True,
) -> dict[str, Any]:
    ensure_awpy_resources(require_tris=compute_missing)
    areas = load_nav_areas(map_name)
    area_by_id = {area["id"]: area for area in areas}
    match = find_nav_area_for_position(areas, position)
    origin_area = match["area"]
    cache_path = default_cache_path(map_name, cache_dir)

    if cache_path.exists():
        cache = load_cache(cache_path)
        if not is_cache_compatible(cache, max_range=max_range, eye_height=eye_height, target_height=target_height):
            raise StaticCacheError(f"Static cache exists but is incompatible with this query: {cache_path}")
    elif compute_missing:
        cache = empty_cache(
            map_name,
            max_range=max_range,
            eye_height=eye_height,
            target_height=target_height,
            areas=areas,
        )
    else:
        raise StaticCacheError(f"Missing static cache for {map_name}: {cache_path}")

    visible_ids = cache["visibility"].get(origin_area["id"])
    computed_now = False
    if visible_ids is None and compute_missing:
        checker = load_visibility_checker(map_name)
        visible_ids = compute_area_visibility(
            origin_area,
            areas,
            checker,
            max_range=max_range,
            eye_height=eye_height,
            target_height=target_height,
        )
        cache["visibility"][origin_area["id"]] = visible_ids
        write_cache(cache_path, cache)
        computed_now = True
    elif visible_ids is None:
        raise StaticCacheError(f"Origin area {origin_area['id']} is not cached yet for {map_name}.")

    visible_area_size = sum(float(area_by_id[area_id]["size"]) for area_id in visible_ids if area_id in area_by_id)
    result = {
        "schemaVersion": "map-static-info-query-0.1",
        "mapName": map_name,
        "query": position,
        "cachePath": str(cache_path.relative_to(REPO_ROOT)),
        "cacheComplete": bool(cache.get("complete")),
        "computedNow": computed_now,
        "match": {
            "type": match["type"],
            "distance": match["distance"],
            "originArea": public_area(origin_area),
        },
        "visibleAreaIds": visible_ids,
        "visibleAreaCount": len(visible_ids),
        "visibleAreaSize": visible_area_size,
        "stats": cache.get("stats", {}),
    }
    if include_areas:
        result["visibleAreas"] = [public_area(area_by_id[area_id]) for area_id in visible_ids if area_id in area_by_id]
    return result


def summarize_cache(
    map_name: str,
    *,
    cache_dir: Path = STATIC_CACHE_DIR,
    max_range: float = 3200.0,
    eye_height: float = 64.0,
    target_height: float = 64.0,
) -> dict[str, Any]:
    ensure_awpy_resources(require_tris=False)
    areas = load_nav_areas(map_name)
    path = default_cache_path(map_name, cache_dir)
    if not path.exists():
        return {
            "mapName": map_name,
            "cachePath": str(path.relative_to(REPO_ROOT)),
            "exists": False,
            "complete": False,
            "stats": {"areaCount": len(areas), "computedOriginCount": 0, "missingOriginCount": len(areas)},
        }
    cache = load_cache(path)
    compatible = is_cache_compatible(cache, max_range=max_range, eye_height=eye_height, target_height=target_height)
    refresh_cache_stats(cache)
    return {
        "mapName": map_name,
        "cachePath": str(path.relative_to(REPO_ROOT)),
        "exists": True,
        "compatible": compatible,
        "complete": bool(cache.get("complete")),
        "config": cache.get("config", {}),
        "stats": cache.get("stats", {}),
    }


def compute_area_visibility(
    origin_area: dict[str, Any],
    areas: list[dict[str, Any]],
    checker: Any,
    *,
    max_range: float,
    eye_height: float,
    target_height: float,
) -> list[str]:
    origin = raised_point(origin_area["centroid"], eye_height)
    visible: list[str] = []
    for target_area in areas:
        target = raised_point(target_area["centroid"], target_height)
        if distance(origin, target) > max_range:
            continue
        if target_area["id"] == origin_area["id"] or checker.is_visible(
            (origin["x"], origin["y"], origin["z"]),
            (target["x"], target["y"], target["z"]),
        ):
            visible.append(target_area["id"])
    return sorted(visible, key=int)


def cached_visible_ids_for_origin(cache: dict[str, Any] | None, origin_area_id: str) -> set[str] | None:
    if not cache:
        return None
    ids = cache.get("visibility", {}).get(origin_area_id)
    return set(ids) if ids is not None else None


def find_nav_area_for_position(areas: list[dict[str, Any]], position: dict[str, float]) -> dict[str, Any]:
    containing = [area for area in areas if point_in_area_xy(area, position["x"], position["y"])]
    candidates = containing if containing else areas

    has_z = "z" in position and position["z"] is not None

    def score(area: dict[str, Any]) -> float:
        centroid = area["centroid"]
        xy = math.hypot(position["x"] - centroid["x"], position["y"] - centroid["y"])
        if has_z:
            return math.sqrt(xy * xy + (position["z"] - centroid["z"]) ** 2)
        return xy

    best = min(candidates, key=score)
    return {
        "type": "containing-area" if containing else "nearest-area",
        "area": best,
        "distance": score(best),
    }


def point_in_area_xy(area: dict[str, Any], x: float, y: float) -> bool:
    bbox = area.get("bbox") or bbox_of(area["corners"])
    if x < bbox["minX"] or x > bbox["maxX"] or y < bbox["minY"] or y > bbox["maxY"]:
        return False

    corners = area["corners"]
    inside = False
    j = len(corners) - 1
    for i, current in enumerate(corners):
        previous = corners[j]
        if (current["y"] > y) != (previous["y"] > y):
            x_intersect = (previous["x"] - current["x"]) * (y - current["y"]) / (previous["y"] - current["y"]) + current[
                "x"
            ]
            if x < x_intersect:
                inside = not inside
        j = i
    return inside


def public_area(area: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": area["id"],
        "label": area["label"],
        "centroid": area["centroid"],
        "pixelCentroid": area["pixelCentroid"],
        "polygon": area["polygon"],
        "size": area["size"],
        "connections": area["connections"],
    }


def _init_visibility_worker(map_name: str, max_range: float, eye_height: float, target_height: float) -> None:
    global _WORKER_AREAS, _WORKER_AREA_BY_ID, _WORKER_CHECKER, _WORKER_MAX_RANGE, _WORKER_EYE_HEIGHT
    global _WORKER_TARGET_HEIGHT

    ensure_awpy_resources(require_tris=True)
    _WORKER_AREAS = load_nav_areas(map_name)
    _WORKER_AREA_BY_ID = {area["id"]: area for area in _WORKER_AREAS}
    _WORKER_CHECKER = load_visibility_checker(map_name)
    _WORKER_MAX_RANGE = max_range
    _WORKER_EYE_HEIGHT = eye_height
    _WORKER_TARGET_HEIGHT = target_height


def _worker_compute_visibility(origin_id: str) -> tuple[str, list[str]]:
    if _WORKER_CHECKER is None:
        raise StaticCacheError("Visibility worker was not initialized.")
    visible_ids = compute_area_visibility(
        _WORKER_AREA_BY_ID[origin_id],
        _WORKER_AREAS,
        _WORKER_CHECKER,
        max_range=_WORKER_MAX_RANGE,
        eye_height=_WORKER_EYE_HEIGHT,
        target_height=_WORKER_TARGET_HEIGHT,
    )
    return origin_id, visible_ids


def raised_point(point: dict[str, float], height: float) -> dict[str, float]:
    return {"x": point["x"], "y": point["y"], "z": point["z"] + height}


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


def bbox_of(corners: list[dict[str, float]]) -> dict[str, float]:
    return {
        "minX": min(c["x"] for c in corners),
        "maxX": max(c["x"] for c in corners),
        "minY": min(c["y"] for c in corners),
        "maxY": max(c["y"] for c in corners),
        "minZ": min(c["z"] for c in corners),
        "maxZ": max(c["z"] for c in corners),
    }


def polygon_area(corners: list[dict[str, float]]) -> float:
    area = 0.0
    for i, current in enumerate(corners):
        nxt = corners[(i + 1) % len(corners)]
        area += current["x"] * nxt["y"] - current["y"] * nxt["x"]
    return abs(area) / 2
