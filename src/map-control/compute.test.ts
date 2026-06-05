import { describe, expect, it } from "vitest";
import {
  canPlayerSeeSample,
  computeMapControl,
  detectControlLossEvents,
  type MapControlFrame,
  type MapControlInput,
  type MapControlZone,
  type PlayerVisionState,
  type ZoneControlFrame,
} from "./index.js";

const midZone: MapControlZone = {
  id: "mirage_mid",
  label: "Mirage Mid",
  tags: ["mirage", "mid"],
  samples: [
    { id: "top_mid", position: { x: 1000, y: 0, z: 0 } },
    { id: "window_line", position: { x: 1000, y: 100, z: 0 } },
  ],
};

const behindZone: MapControlZone = {
  id: "ct_spawn",
  label: "CT Spawn",
  samples: [{ id: "ct_spawn_1", position: { x: -1000, y: 0, z: 0 } }],
};

const ctViewer: PlayerVisionState = {
  steamId64: "ct-anchor",
  team: "CT",
  isAlive: true,
  position: { x: 0, y: 0, z: 0 },
  yawDeg: 0,
};

const tViewer: PlayerVisionState = {
  steamId64: "t-entry",
  team: "T",
  isAlive: true,
  position: { x: 2000, y: 0, z: 0 },
  yawDeg: 180,
};

describe("computeMapControl", () => {
  it("marks a zone safe-controlled when a teammate directly sees its samples", () => {
    const timeline = computeMapControl({
      mapName: "de_mirage",
      zones: [midZone, behindZone],
      ticks: [{ tick: 100, seconds: 1, players: [ctViewer] }],
    });

    const frame = requireFrame(timeline.frames[0]);
    const mid = requireZone(frame.zones[0]);
    const behind = requireZone(frame.zones[1]);

    expect(mid.teams.CT.state).toBe("controlled");
    expect(mid.teams.CT.coverage).toBe(1);
    expect(mid.overlayState).toBe("CT-controlled");
    expect(mid.teams.CT.visibleSamples[0]?.viewers).toEqual(["ct-anchor"]);

    expect(behind.teams.CT.state).toBe("none");
    expect(behind.overlayState).toBe("vacuum");
  });

  it("emits contested overlay when both teams can see the same zone", () => {
    const timeline = computeMapControl({
      mapName: "de_mirage",
      zones: [midZone],
      ticks: [{ tick: 100, seconds: 1, players: [ctViewer, tViewer] }],
    });

    const frame = requireFrame(timeline.frames[0]);
    const mid = requireZone(frame.zones[0]);

    expect(mid.teams.CT.state).toBe("controlled");
    expect(mid.teams.T.state).toBe("controlled");
    expect(mid.overlayState).toBe("contested");
  });

  it("blocks direct vision through active smokes", () => {
    const timeline = computeMapControl({
      mapName: "de_mirage",
      zones: [midZone],
      ticks: [{
        tick: 100,
        seconds: 1,
        players: [ctViewer],
        smokes: [{ id: "window_smoke", position: { x: 500, y: 0, z: 32 }, radius: 180 }],
      }],
    });

    const frame = requireFrame(timeline.frames[0]);
    const mid = requireZone(frame.zones[0]);

    expect(mid.teams.CT.state).toBe("none");
    expect(mid.teams.CT.coverage).toBe(0);
  });

  it("respects static LOS adapters supplied by analysis code", () => {
    const input: MapControlInput = {
      mapName: "de_mirage",
      zones: [midZone],
      ticks: [{ tick: 100, seconds: 1, players: [ctViewer] }],
      config: {
        staticLineOfSight: ({ sample }) => sample.id !== "window_line",
      },
    };

    const timeline = computeMapControl(input);
    const frame = requireFrame(timeline.frames[0]);
    const mid = requireZone(frame.zones[0]);

    expect(mid.teams.CT.coverage).toBe(0.5);
    expect(mid.teams.CT.state).toBe("partial");
    expect(mid.teams.CT.visibleSamples.map((sample) => sample.sampleId)).toEqual(["top_mid"]);
  });
});

describe("canPlayerSeeSample", () => {
  it("ignores blinded players", () => {
    const sample = midZone.samples[0];
    if (!sample) throw new Error("missing sample");

    const visibility = canPlayerSeeSample(
      { ...ctViewer, isBlinded: true },
      sample,
      { tick: 100, seconds: 1, players: [ctViewer] },
      {
        controlledCoverageThreshold: 0.6,
        partialCoverageThreshold: 0.001,
        defaultEyeHeight: 64,
        defaultHorizontalFovDeg: 90,
        defaultVisionRange: Infinity,
        defaultSmokeRadius: 144,
        smokeBlocksVision: true,
      },
    );

    expect(visibility).toEqual({ visible: false, reason: "blinded" });
  });
});

describe("detectControlLossEvents", () => {
  it("marks controlled-to-none transitions for timeline annotation", () => {
    const timeline = computeMapControl({
      mapName: "de_mirage",
      zones: [midZone],
      ticks: [
        { tick: 100, seconds: 1, players: [ctViewer] },
        { tick: 200, seconds: 2, players: [{ ...ctViewer, yawDeg: 180 }] },
      ],
    });

    const events = detectControlLossEvents(timeline);

    expect(events).toEqual([{
      team: "CT",
      zoneId: "mirage_mid",
      label: "Mirage Mid",
      fromTick: 100,
      toTick: 200,
      fromSeconds: 1,
      toSeconds: 2,
      previousCoverage: 1,
      coverage: 0,
    }]);
  });
});

function requireFrame(frame: MapControlFrame | undefined): MapControlFrame {
  if (!frame) throw new Error("missing frame");
  return frame;
}

function requireZone(zone: ZoneControlFrame | undefined): ZoneControlFrame {
  if (!zone) throw new Error("missing zone");
  return zone;
}
