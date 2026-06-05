import type {
  MapControlTeam,
  MapControlTimeline,
  TeamZoneControl,
  ZoneControlFrame,
  ZoneControlLossEvent,
} from "./types.js";

export interface ControlLossOptions {
  /** Defaults to "controlled": only count losses from fully controlled zones. */
  fromState?: TeamZoneControl["state"];
}

export function detectControlLossEvents(
  timeline: MapControlTimeline,
  options: ControlLossOptions = {},
): ZoneControlLossEvent[] {
  const fromState = options.fromState ?? "controlled";
  const events: ZoneControlLossEvent[] = [];

  for (let frameIndex = 1; frameIndex < timeline.frames.length; frameIndex += 1) {
    const previousFrame = timeline.frames[frameIndex - 1];
    const frame = timeline.frames[frameIndex];
    if (!previousFrame || !frame) continue;

    for (const zone of frame.zones) {
      const previousZone = findZone(previousFrame.zones, zone.zoneId);
      if (!previousZone) continue;

      pushLossIfNeeded(events, "T", previousZone, zone, previousFrame.tick, frame.tick, previousFrame.seconds, frame.seconds, fromState);
      pushLossIfNeeded(events, "CT", previousZone, zone, previousFrame.tick, frame.tick, previousFrame.seconds, frame.seconds, fromState);
    }
  }

  return events;
}

function pushLossIfNeeded(
  events: ZoneControlLossEvent[],
  team: MapControlTeam,
  previousZone: ZoneControlFrame,
  zone: ZoneControlFrame,
  fromTick: number,
  toTick: number,
  fromSeconds: number,
  toSeconds: number,
  fromState: TeamZoneControl["state"],
): void {
  const before = previousZone.teams[team];
  const after = zone.teams[team];
  if (before.state !== fromState || after.state === fromState) return;

  events.push({
    team,
    zoneId: zone.zoneId,
    label: zone.label,
    fromTick,
    toTick,
    fromSeconds,
    toSeconds,
    previousCoverage: before.coverage,
    coverage: after.coverage,
  });
}

function findZone(
  zones: readonly ZoneControlFrame[],
  zoneId: string,
): ZoneControlFrame | undefined {
  return zones.find((zone) => zone.zoneId === zoneId);
}
