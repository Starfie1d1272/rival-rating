#!/usr/bin/env node

import { readFileSync, writeFileSync } from "node:fs";
import { basename } from "node:path";

const args = process.argv.slice(2);
const [inputPath, outputPath] = args;

if (!inputPath || !outputPath) {
  console.error(
    "Usage: node scripts/analysis-to-account-fixture.mjs <analysis.json> <fixture.json> [--id=...] [--match-url=...] [--demo-file=...] [--tier=...]",
  );
  process.exit(1);
}

const flags = Object.fromEntries(
  args
    .slice(2)
    .filter((arg) => arg.startsWith("--") && arg.includes("="))
    .map((arg) => {
      const idx = arg.indexOf("=");
      return [arg.slice(2, idx), arg.slice(idx + 1)];
    }),
);

const analysis = JSON.parse(readFileSync(inputPath, "utf8"));
const players = normalizePlayers(asArray(analysis.players));
const kills = asArray(analysis.kills).sort((a, b) => number(a.tick) - number(b.tick));
const rounds = asArray(analysis.rounds);
const damages = asArray(analysis.damages);
const bombEvents = asArray(analysis.bomb);
const tickRate = number(analysis.match?.tick_rate) || 128;
const tradeWindowTicks = tickRate * 5;
const roundByNum = new Map(rounds.map((round) => [String(round.round_num), round]));

const openingBySteamId = new Map();
const multiKillsBySteamId = new Map();
const headshotsBySteamId = new Map();
const wallbangsBySteamId = new Map();
const tradedDeathsBySteamId = new Map();
const tradeKillsBySteamId = new Map();
const plantsBySteamId = new Map();
const defusesBySteamId = new Map();
const plantsConvertedBySteamId = new Map();
const utilityDamageBySteamId = new Map();

for (const roundKills of groupBy(kills, (kill) => String(kill.round_num)).values()) {
  roundKills.sort((a, b) => number(a.tick) - number(b.tick));
  const first = roundKills[0];
  if (first) {
    add(openingBySteamId, steamId(first.attacker_steamid), "kills", 1);
    add(openingBySteamId, steamId(first.victim_steamid), "deaths", 1);
  }

  const perAttacker = groupBy(roundKills, (kill) => steamId(kill.attacker_steamid));
  for (const [id, attackerKills] of perAttacker) {
    const count = attackerKills.length;
    if (count >= 2) {
      const bucket = count >= 5 ? "five" : count === 4 ? "four" : count === 3 ? "three" : "two";
      add(multiKillsBySteamId, id, bucket, 1);
    }
  }

  for (const death of roundKills) {
    const victimSide = death.victim_side;
    const victimId = steamId(death.victim_steamid);
    const killerId = steamId(death.attacker_steamid);
    const trade = roundKills.find((candidate) => {
      if (number(candidate.tick) <= number(death.tick)) return false;
      if (number(candidate.tick) - number(death.tick) > tradeWindowTicks) return false;
      return candidate.attacker_side === victimSide && steamId(candidate.victim_steamid) === killerId;
    });
    if (trade) {
      increment(tradedDeathsBySteamId, victimId, 1);
      increment(tradeKillsBySteamId, steamId(trade.attacker_steamid), 1);
    }
  }
}

for (const kill of kills) {
  const id = steamId(kill.attacker_steamid);
  if (kill.headshot) increment(headshotsBySteamId, id, 1);
  if (number(kill.penetrated) > 0) increment(wallbangsBySteamId, id, 1);
}

for (const bomb of bombEvents) {
  const id = steamId(bomb.steamid ?? bomb.user_steamid);
  const status = String(bomb.status ?? bomb.event ?? bomb.type ?? "");
  if (!id) continue;
  if (status === "planted" || status === "bomb_planted") {
    increment(plantsBySteamId, id, 1);
    const round = roundByNum.get(String(bomb.round_num));
    if (round?.winner === "t") increment(plantsConvertedBySteamId, id, 1);
  }
  if (status === "defused" || status === "bomb_defused") {
    increment(defusesBySteamId, id, 1);
  }
}

for (const damage of damages) {
  const id = steamId(damage.attacker_steamid);
  if (!id || !isUtilityWeapon(damage.weapon)) continue;
  increment(utilityDamageBySteamId, id, number(damage.dmg_health ?? damage.damage_health ?? damage.dmg));
}

const signals = players.map((player) => {
  const id = steamId(player.steamid);
  const roundsPlayed = number(player.n_rounds) || number(analysis.match?.rounds_played) || rounds.length;
  const deaths = number(player.deaths);
  const opening = openingBySteamId.get(id) ?? {};
  const multiKills = {
    two: number(multiKillsBySteamId.get(id)?.two),
    three: number(multiKillsBySteamId.get(id)?.three),
    four: number(multiKillsBySteamId.get(id)?.four),
    five: number(multiKillsBySteamId.get(id)?.five),
  };
  const tradedDeaths = number(tradedDeathsBySteamId.get(id));

  return {
    steamId64: id,
    rounds: roundsPlayed,
    sourceVersion: "analysis-to-account-fixture/0.1",
    combat: {
      kills: number(player.kills),
      deaths,
      assists: number(player.assists),
      effectiveDamage: number(player.dmg) || number(player.adr) * roundsPlayed,
      openingKills: number(opening.kills),
      openingDeaths: number(opening.deaths),
      multiKills,
      headshotKills: number(player.headshots) || number(headshotsBySteamId.get(id)),
      wallbangKills: number(wallbangsBySteamId.get(id)),
      killsByBuyDelta: null,
      killsByManState: null,
    },
    trade: {
      tradeKills: number(tradeKillsBySteamId.get(id)),
      tradedDeaths,
      deaths,
      tradedOpeningDeaths: null,
    },
    clutch: {
      vsOne: { count: 0, won: 0 },
      vsTwo: { count: 0, won: 0 },
      vsThree: { count: 0, won: 0 },
      vsFour: { count: 0, won: 0 },
      vsFive: { count: 0, won: 0 },
    },
    objective: {
      plants: number(plantsBySteamId.get(id)),
      defuses: number(defusesBySteamId.get(id)),
      plantsConverted: number(plantsConvertedBySteamId.get(id)),
    },
    utility: {
      flashAssists: 0,
      enemyFlashDurationSeconds: 0,
      teamFlashDurationSeconds: null,
      utilityDamage: number(utilityDamageBySteamId.get(id)),
    },
  };
});

const fixture = {
  id: flags.id ?? analysis.map_id ?? analysis.match_id ?? basename(inputPath, ".json"),
  source: {
    matchUrl: flags["match-url"] ?? analysis.meta?.match_url ?? analysis.match_url,
    demoFile: flags["demo-file"] ?? analysis.file_name ?? basename(inputPath),
    tier: flags.tier,
    parsedAt: new Date().toISOString(),
  },
  signals,
};

writeFileSync(outputPath, `${JSON.stringify(fixture, null, 2)}\n`);

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function normalizePlayers(rows) {
  const grouped = groupBy(rows, (player) => steamId(player.steamid));
  const players = [];

  for (const [id, group] of grouped) {
    if (!id) continue;
    const allSide = group.find((player) => player.side === "all");
    if (allSide) {
      players.push(allSide);
      continue;
    }

    players.push({
      name: group.find((player) => player.name)?.name,
      steamid: id,
      side: "all",
      n_rounds: sum(group, "n_rounds"),
      kills: sum(group, "kills"),
      headshots: sum(group, "headshots"),
      deaths: sum(group, "deaths"),
      assists: sum(group, "assists"),
      dmg: sum(group, "dmg"),
      adr: sum(group, "n_rounds") > 0 ? sum(group, "dmg") / sum(group, "n_rounds") : 0,
      kast_rounds: sum(group, "kast_rounds"),
    });
  }

  return players;
}

function number(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function steamId(value) {
  return value === null || value === undefined ? "" : String(value);
}

function increment(map, key, amount) {
  map.set(key, number(map.get(key)) + amount);
}

function add(map, key, prop, amount) {
  const value = map.get(key) ?? {};
  value[prop] = number(value[prop]) + amount;
  map.set(key, value);
}

function sum(rows, prop) {
  return rows.reduce((total, row) => total + number(row[prop]), 0);
}

function isUtilityWeapon(weapon) {
  return ["hegrenade", "inferno", "incgrenade", "molotov"].includes(String(weapon));
}

function groupBy(values, getKey) {
  const groups = new Map();
  for (const value of values) {
    const key = getKey(value);
    const group = groups.get(key);
    if (group) group.push(value);
    else groups.set(key, [value]);
  }
  return groups;
}
