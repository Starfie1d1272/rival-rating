#!/usr/bin/env python3
"""Parse a CS2 .dem with Awpy and emit the compact analysis sidecar.

Install parser dependencies outside this package first:

    python3 -m pip install awpy

The JSON output is intentionally shaped for scripts/analysis-to-account-fixture.mjs.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("demo", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tickrate", type=int, default=128)
    parser.add_argument("--match-url")
    parser.add_argument("--demo-id")
    parser.add_argument("--event")
    parser.add_argument("--tier")
    args = parser.parse_args()

    try:
        from awpy import Demo
    except ImportError as exc:
        raise SystemExit("Missing dependency: install Awpy with `python3 -m pip install awpy`.") from exc

    demo = Demo(args.demo, tickrate=args.tickrate, verbose=True)
    demo.parse()

    rounds = frame_to_rows(getattr(demo, "rounds", None))
    kills = frame_to_rows(safe_get(demo, "kills"))
    damages = frame_to_rows(safe_get(demo, "damages"))
    bomb = frame_to_rows(safe_get(demo, "bomb"))
    player_round_totals = frame_to_rows(safe_get(demo, "player_round_totals"))

    players = build_players(player_round_totals, kills, damages)
    header = to_jsonable(safe_get(demo, "header"))

    analysis = {
        "header": header if isinstance(header, dict) else {},
        "match": {
            "map_name": value_from(header, "map_name"),
            "tick_rate": args.tickrate,
            "rounds_played": len({row.get("round_num") for row in rounds if row.get("round_num") is not None}),
        },
        "players": players,
        "rounds": rounds,
        "kills": kills,
        "damages": damages,
        "bomb": bomb,
        "meta": {
            "demo_id": args.demo_id,
            "demo_url": f"https://www.hltv.org/download/demo/{args.demo_id}" if args.demo_id else None,
            "match_url": args.match_url,
            "event": args.event,
            "tier": args.tier,
            "demo_file": str(args.demo),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(to_jsonable(analysis), indent=2) + "\n", encoding="utf8")


def safe_get(obj: Any, attr: str) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return None


def frame_to_rows(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dicts"):
        return [to_jsonable(row) for row in frame.to_dicts()]
    return []


def build_players(
    player_round_totals: list[dict[str, Any]],
    kills: list[dict[str, Any]],
    damages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    names: dict[str, str] = {}
    rounds_by_id: dict[str, int] = {}
    kills_by_id: defaultdict[str, int] = defaultdict(int)
    headshots_by_id: defaultdict[str, int] = defaultdict(int)
    deaths_by_id: defaultdict[str, int] = defaultdict(int)
    assists_by_id: defaultdict[str, int] = defaultdict(int)
    damage_by_id: defaultdict[str, float] = defaultdict(float)

    for row in player_round_totals:
      sid = steamid(row.get("steamid"))
      if not sid:
          continue
      names.setdefault(sid, str(row.get("name") or sid))
      if row.get("side") == "all":
          rounds_by_id[sid] = int(number(row.get("n_rounds")))

    for row in kills:
        attacker = steamid(row.get("attacker_steamid"))
        victim = steamid(row.get("victim_steamid"))
        assister = steamid(row.get("assister_steamid"))
        if attacker:
            kills_by_id[attacker] += 1
            names.setdefault(attacker, str(row.get("attacker_name") or attacker))
            if row.get("headshot"):
                headshots_by_id[attacker] += 1
        if victim:
            deaths_by_id[victim] += 1
            names.setdefault(victim, str(row.get("victim_name") or victim))
        if assister:
            assists_by_id[assister] += 1
            names.setdefault(assister, str(row.get("assister_name") or assister))

    for row in damages:
        attacker = steamid(row.get("attacker_steamid"))
        if not attacker:
            continue
        names.setdefault(attacker, str(row.get("attacker_name") or attacker))
        damage_by_id[attacker] += number(row.get("dmg_health", row.get("damage_health", row.get("dmg", 0))))

    ids = sorted(set(names) | set(rounds_by_id) | set(kills_by_id) | set(deaths_by_id) | set(damage_by_id))
    players = []
    for sid in ids:
        rounds = rounds_by_id.get(sid, 0)
        damage = damage_by_id.get(sid, 0)
        players.append(
            {
                "name": names.get(sid, sid),
                "steamid": sid,
                "side": "all",
                "n_rounds": rounds,
                "kills": kills_by_id[sid],
                "headshots": headshots_by_id[sid],
                "deaths": deaths_by_id[sid],
                "assists": assists_by_id[sid],
                "adr": damage / rounds if rounds > 0 else 0,
                "dmg": damage,
            }
        )
    return players


def steamid(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def number(value: Any) -> float:
    return value if isinstance(value, (int, float)) else 0


def value_from(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else None


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "item"):
        return to_jsonable(value.item())
    if isinstance(value, Path):
        return str(value)
    return value


if __name__ == "__main__":
    main()
