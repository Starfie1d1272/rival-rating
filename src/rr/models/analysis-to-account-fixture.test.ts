import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const scriptPath = fileURLToPath(
  new URL("../../../scripts/analysis-to-account-fixture.mjs", import.meta.url),
);

describe("analysis-to-account-fixture script", () => {
  it("maps analysis sidecar players and kill events into AccountSignalsV2", () => {
    const dir = mkdtempSync(join(tmpdir(), "rr-fixture-"));
    const input = join(dir, "demo.analysis.json");
    const output = join(dir, "fixture.json");

    writeFileSync(
      input,
      JSON.stringify({
        match: { tick_rate: 128, rounds_played: 1 },
        rounds: [{ round_num: 1 }],
        players: [
          { name: "A", steamid: "1", side: "ct", n_rounds: 1, kills: 1, headshots: 1, deaths: 1, assists: 0, adr: 100, dmg: 100 },
          { name: "B", steamid: "2", side: "t", n_rounds: 1, kills: 0, headshots: 0, deaths: 1, assists: 0, adr: 0, dmg: 0 },
          { name: "C", steamid: "3", side: "t", n_rounds: 1, kills: 1, headshots: 0, deaths: 0, assists: 0, adr: 50, dmg: 50 },
          { name: "C", steamid: "3", side: "ct", n_rounds: 2, kills: 2, headshots: 1, deaths: 1, assists: 1, adr: 25, dmg: 50 },
        ],
        kills: [
          { tick: 1000, round_num: 1, attacker_steamid: "1", attacker_side: "ct", victim_steamid: "2", victim_side: "t", headshot: true, penetrated: 0 },
          { tick: 1100, round_num: 1, attacker_steamid: "3", attacker_side: "t", victim_steamid: "1", victim_side: "ct", headshot: false, penetrated: 0 },
        ],
        bomb: [
          { tick: 900, round_num: 1, status: "planted", steamid: "3" },
          { tick: 1200, round_num: 1, status: "defused", steamid: "1" },
        ],
        damages: [
          { tick: 800, round_num: 1, attacker_steamid: "3", weapon: "hegrenade", dmg_health: 42 },
          { tick: 850, round_num: 1, attacker_steamid: "3", weapon: "ak47", dmg_health: 20 },
        ],
      }),
    );

    execFileSync("node", [scriptPath, input, output, "--id=sample", "--tier=elite"]);
    const fixture = JSON.parse(readFileSync(output, "utf8"));
    const bySteamId = new Map<string, any>(
      fixture.signals.map((signal: { steamId64: string }) => [signal.steamId64, signal]),
    );

    expect(fixture.id).toBe("sample");
    expect(fixture.source.tier).toBe("elite");
    expect(fixture.signals).toHaveLength(3);
    expect(bySteamId.get("1").combat.openingKills).toBe(1);
    expect(bySteamId.get("2").combat.openingDeaths).toBe(1);
    expect(bySteamId.get("1").combat.headshotKills).toBe(1);
    expect(bySteamId.get("3").rounds).toBe(3);
    expect(bySteamId.get("3").combat.kills).toBe(3);
    expect(bySteamId.get("2").trade.tradedDeaths).toBe(1);
    expect(bySteamId.get("3").trade.tradeKills).toBe(1);
    expect(bySteamId.get("3").objective.plants).toBe(1);
    expect(bySteamId.get("1").objective.defuses).toBe(1);
    expect(bySteamId.get("3").utility.utilityDamage).toBe(42);
  });
});
