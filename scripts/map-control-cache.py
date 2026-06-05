#!/usr/bin/env python3
"""CLI for building and querying CS2 static map-information caches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from map_control_static_cache import (
    STATIC_CACHE_DIR,
    SUPPORTED_MAPS,
    StaticCacheError,
    generate_map_cache,
    query_map_info,
    summarize_cache,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Generate or resume one map cache.")
    add_shared_cache_args(generate)
    generate.add_argument("map_name", choices=sorted(SUPPORTED_MAPS))
    generate.add_argument("--force", action="store_true", help="Overwrite an incompatible or existing cache.")
    generate.add_argument("--area-limit", type=int, default=None, help="Compute only the first N missing origin areas.")
    generate.add_argument(
        "--origin-id",
        action="append",
        default=None,
        help="Compute only this origin nav area. Can be passed more than once.",
    )
    generate.add_argument("--jobs", type=int, default=1, help="Parallel worker count. Each worker loads the map tri file.")
    generate.add_argument("--checkpoint-interval", type=int, default=25)

    generate_all = subparsers.add_parser("generate-all", help="Generate or resume caches for all supported maps.")
    add_shared_cache_args(generate_all)
    generate_all.add_argument("--force", action="store_true")
    generate_all.add_argument("--area-limit", type=int, default=None)
    generate_all.add_argument("--jobs", type=int, default=1)
    generate_all.add_argument("--checkpoint-interval", type=int, default=25)

    query = subparsers.add_parser("query", help="Return static map information for a game-space coordinate.")
    add_shared_cache_args(query)
    query.add_argument("map_name", choices=sorted(SUPPORTED_MAPS))
    query.add_argument("--x", type=float, required=True)
    query.add_argument("--y", type=float, required=True)
    query.add_argument("--z", type=float, default=None)
    query.add_argument("--compute-missing", action="store_true", help="Compute and save the origin row if missing.")
    query.add_argument("--ids-only", action="store_true", help="Omit full visible area metadata.")

    summary = subparsers.add_parser("summary", help="Show static cache status for a map.")
    add_shared_cache_args(summary)
    summary.add_argument("map_name", choices=sorted(SUPPORTED_MAPS))

    args = parser.parse_args()
    try:
        payload = dispatch(args)
    except StaticCacheError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def add_shared_cache_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", type=Path, default=STATIC_CACHE_DIR)
    parser.add_argument("--max-range", type=float, default=3200.0)
    parser.add_argument("--eye-height", type=float, default=64.0)
    parser.add_argument("--target-height", type=float, default=64.0)


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "generate":
        cache = generate_map_cache(
            args.map_name,
            output_dir=args.output_dir,
            max_range=args.max_range,
            eye_height=args.eye_height,
            target_height=args.target_height,
            force=args.force,
            area_limit=args.area_limit,
            origin_ids=args.origin_id,
            jobs=args.jobs,
            checkpoint_interval=args.checkpoint_interval,
        )
        return summarize_cache(
            args.map_name,
            cache_dir=args.output_dir,
            max_range=args.max_range,
            eye_height=args.eye_height,
            target_height=args.target_height,
        ) | {"generatedAt": cache.get("generatedAt"), "updatedAt": cache.get("updatedAt")}

    if args.command == "generate-all":
        results = []
        for map_name in sorted(SUPPORTED_MAPS):
            cache = generate_map_cache(
                map_name,
                output_dir=args.output_dir,
                max_range=args.max_range,
                eye_height=args.eye_height,
                target_height=args.target_height,
                force=args.force,
                area_limit=args.area_limit,
                jobs=args.jobs,
                checkpoint_interval=args.checkpoint_interval,
            )
            results.append(
                summarize_cache(
                    map_name,
                    cache_dir=args.output_dir,
                    max_range=args.max_range,
                    eye_height=args.eye_height,
                    target_height=args.target_height,
                )
                | {"generatedAt": cache.get("generatedAt"), "updatedAt": cache.get("updatedAt")}
            )
        return {"maps": results}

    if args.command == "query":
        position = {"x": args.x, "y": args.y}
        if args.z is not None:
            position["z"] = args.z
        return query_map_info(
            args.map_name,
            position,
            cache_dir=args.output_dir,
            max_range=args.max_range,
            eye_height=args.eye_height,
            target_height=args.target_height,
            compute_missing=args.compute_missing,
            include_areas=not args.ids_only,
        )

    if args.command == "summary":
        return summarize_cache(
            args.map_name,
            cache_dir=args.output_dir,
            max_range=args.max_range,
            eye_height=args.eye_height,
            target_height=args.target_height,
        )

    raise StaticCacheError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
