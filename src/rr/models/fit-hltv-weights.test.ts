import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const scriptPath = fileURLToPath(
  new URL("../../../scripts/fit-hltv-weights.mjs", import.meta.url),
);

describe("fit-hltv-weights script", () => {
  it("fits labeled player-map rows and emits metrics plus candidate weights", () => {
    const dir = mkdtempSync(join(tmpdir(), "rr-hltv-fit-"));
    const fixturesDir = join(dir, "fixtures");
    const labelsDir = join(dir, "labels");
    const out = join(dir, "weights.json");
    const metricsPath = join(dir, "metrics.json");
    mkdirSync(fixturesDir);
    mkdirSync(labelsDir);

    writeFileSync(
      join(fixturesDir, "sample.json"),
      JSON.stringify({
        id: "sample",
        source: { tier: "test" },
        signals: [
          signal("1", 20, 28, 10, 2100),
          signal("2", 20, 20, 16, 1600),
          signal("3", 20, 12, 22, 1100),
        ],
      }),
    );
    writeFileSync(
      join(labelsDir, "sample.json"),
      JSON.stringify({
        version: "hltv-labels-v1",
        fixtureId: "sample",
        ratingVersion: "test",
        labels: [
          { steamId64: "1", hltvRating: 1.4 },
          { steamId64: "2", hltvRating: 1.0 },
          { steamId64: "3", hltvRating: 0.7 },
        ],
      }),
    );

    execFileSync("node", [
      scriptPath,
      `--fixtures=${fixturesDir}`,
      `--labels=${labelsDir}`,
      `--out=${out}`,
      `--metrics=${metricsPath}`,
      "--lambda=0.1",
    ]);

    const weights = JSON.parse(readFileSync(out, "utf8"));
    const metrics = JSON.parse(readFileSync(metricsPath, "utf8"));

    expect(weights.version).toBe("rr-hltv-fit-v1-0.1");
    expect(weights.fit.rows).toBe(3);
    expect(Number.isFinite(weights.combat.killWeight)).toBe(true);
    expect(metrics.rows).toHaveLength(3);
    expect(metrics.metrics.mae).toBeLessThan(0.2);
  });
});

function signal(steamId64: string, rounds: number, kills: number, deaths: number, damage: number) {
  return {
    steamId64,
    rounds,
    combat: {
      kills,
      deaths,
      assists: 0,
      effectiveDamage: damage,
      openingKills: Math.max(0, kills - 18),
      openingDeaths: Math.max(0, deaths - 18),
      multiKills: { two: 0, three: 0, four: 0, five: 0 },
      headshotKills: 0,
      wallbangKills: 0,
      killsByBuyDelta: null,
      killsByManState: null,
    },
    trade: {
      tradeKills: 0,
      tradedDeaths: 0,
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
      plants: 0,
      defuses: 0,
      plantsConverted: 0,
    },
    utility: {
      flashAssists: 0,
      enemyFlashDurationSeconds: 0,
      teamFlashDurationSeconds: 0,
      utilityDamage: 0,
    },
  };
}
