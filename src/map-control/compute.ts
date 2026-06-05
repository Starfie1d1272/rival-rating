import { canPlayerSeeSample, resolveMapControlConfig } from "./geometry.js";
import { MAP_CONTROL_TEAMS } from "./types.js";
import type {
  MapControlConfig,
  MapControlFrame,
  MapControlInput,
  MapControlSamplePoint,
  MapControlTeam,
  MapControlTimeline,
  MapControlTick,
  MapControlZone,
  OverlayState,
  TeamControlRecord,
  TeamZoneControl,
  VisibleSample,
  ZoneControlFrame,
  ZoneControlState,
} from "./types.js";

export function computeMapControl(input: MapControlInput): MapControlTimeline {
  const config = resolveMapControlConfig(input.config);
  return {
    mapName: input.mapName,
    config,
    frames: input.ticks.map((tick) => computeFrame(input.zones, tick, config)),
  };
}

function computeFrame(
  zones: readonly MapControlZone[],
  tick: MapControlTick,
  config: MapControlConfig,
): MapControlFrame {
  return {
    tick: tick.tick,
    seconds: tick.seconds,
    zones: zones.map((zone) => computeZoneFrame(zone, tick, config)),
  };
}

function computeZoneFrame(
  zone: MapControlZone,
  tick: MapControlTick,
  config: MapControlConfig,
): ZoneControlFrame {
  const teams: TeamControlRecord<TeamZoneControl> = {
    T: computeTeamZoneControl("T", zone, tick, config),
    CT: computeTeamZoneControl("CT", zone, tick, config),
  };

  return {
    zoneId: zone.id,
    label: zone.label,
    tags: zone.tags ?? [],
    teams,
    overlayState: overlayState(teams),
  };
}

function computeTeamZoneControl(
  team: MapControlTeam,
  zone: MapControlZone,
  tick: MapControlTick,
  config: MapControlConfig,
): TeamZoneControl {
  const totalWeight = zone.samples.reduce((sum, sample) => sum + sampleWeight(sample), 0);
  const visibleSamples = zone.samples.flatMap((sample) => {
    const viewers = tick.players
      .filter((player) => player.team === team)
      .filter((player) => canPlayerSeeSample(player, sample, tick, config).visible)
      .map((player) => player.steamId64);

    if (viewers.length === 0) return [];

    return [{
      sampleId: sample.id,
      position: sample.position,
      weight: sampleWeight(sample),
      viewers,
    }];
  });

  const visibleWeight = visibleSamples.reduce((sum, sample) => sum + sample.weight, 0);
  const coverage = totalWeight > 0 ? visibleWeight / totalWeight : 0;

  return {
    team,
    zoneId: zone.id,
    visibleWeight,
    totalWeight,
    coverage,
    state: zoneControlState(coverage, config),
    visibleSamples,
  };
}

function zoneControlState(coverage: number, config: MapControlConfig): ZoneControlState {
  if (coverage >= config.controlledCoverageThreshold) return "controlled";
  if (coverage >= config.partialCoverageThreshold) return "partial";
  return "none";
}

function overlayState(teams: TeamControlRecord<TeamZoneControl>): OverlayState {
  const tHasControl = teams.T.state !== "none";
  const ctHasControl = teams.CT.state !== "none";
  if (tHasControl && ctHasControl) return "contested";
  if (tHasControl) return "T-controlled";
  if (ctHasControl) return "CT-controlled";
  return "vacuum";
}

function sampleWeight(sample: MapControlSamplePoint): number {
  return sample.weight ?? 1;
}

export function emptyTeamControlRecord(zoneId: string): TeamControlRecord<TeamZoneControl> {
  return {
    T: emptyTeamZoneControl("T", zoneId),
    CT: emptyTeamZoneControl("CT", zoneId),
  };
}

function emptyTeamZoneControl(team: MapControlTeam, zoneId: string): TeamZoneControl {
  return {
    team,
    zoneId,
    visibleWeight: 0,
    totalWeight: 0,
    coverage: 0,
    state: "none",
    visibleSamples: [],
  };
}

export function teams(): readonly MapControlTeam[] {
  return MAP_CONTROL_TEAMS;
}
