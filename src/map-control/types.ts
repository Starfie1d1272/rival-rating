/**
 * Map control MVP contract.
 *
 * This module is intentionally independent from RR / PRISM. It describes
 * what a team can currently see on the map and emits timeline data that a
 * viewer can render as a control overlay.
 */

export const MAP_CONTROL_TEAMS = ["T", "CT"] as const;
export type MapControlTeam = (typeof MAP_CONTROL_TEAMS)[number];

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface MapControlSamplePoint {
  id: string;
  /** World-space sample position. Use nav-area centroids or hand-authored zone samples. */
  position: Vec3;
  /** Optional importance within the zone. Defaults to 1. */
  weight?: number;
  label?: string;
}

export interface MapControlZone {
  id: string;
  label: string;
  /** Human callout / structural tags for UI filtering, e.g. ["mid", "connector"]. */
  tags?: readonly string[];
  /** Samples that approximate this zone's navigable/control surface. */
  samples: readonly MapControlSamplePoint[];
}

export interface PlayerVisionState {
  steamId64: string;
  team: MapControlTeam;
  isAlive: boolean;
  position: Vec3;
  /**
   * Yaw in degrees. Convention for this library: 0 faces +X, 90 faces +Y.
   * Adapters should convert engine yaw into this convention before calling.
   */
  yawDeg: number;
  /** Optional pitch in degrees. Positive means looking up in this library's convention. */
  pitchDeg?: number;
  /** Defaults to config.defaultEyeHeight. */
  eyeHeight?: number;
  /** Defaults to config.defaultHorizontalFovDeg. */
  horizontalFovDeg?: number;
  /** If omitted, vertical FOV is not gated. */
  verticalFovDeg?: number;
  /** Defaults to config.defaultVisionRange. */
  visionRange?: number;
  /** Blinded players contribute no safe vision in the MVP. */
  isBlinded?: boolean;
}

export interface ActiveSmoke {
  id: string;
  position: Vec3;
  /** Defaults to config.defaultSmokeRadius. */
  radius?: number;
}

export interface MapControlTick {
  tick: number;
  seconds: number;
  players: readonly PlayerVisionState[];
  smokes?: readonly ActiveSmoke[];
}

export interface StaticLineOfSightQuery {
  viewer: PlayerVisionState;
  sample: MapControlSamplePoint;
  tick: MapControlTick;
  eyePosition: Vec3;
}

export type StaticLineOfSight = (query: StaticLineOfSightQuery) => boolean;

export interface MapControlConfig {
  /** Minimum coverage for a zone to be treated as controlled by the team. */
  controlledCoverageThreshold: number;
  /** Minimum non-zero coverage for partial control. */
  partialCoverageThreshold: number;
  defaultEyeHeight: number;
  defaultHorizontalFovDeg: number;
  /** Optional hard range for vision checks. Use Infinity to disable. */
  defaultVisionRange: number;
  defaultSmokeRadius: number;
  /** When true, active smokes block line segments between eye and sample point. */
  smokeBlocksVision: boolean;
  /**
   * Static map LOS check supplied by an adapter around awpy / nav geometry.
   * If omitted, static geometry is assumed clear and only FOV/range/smoke apply.
   */
  staticLineOfSight?: StaticLineOfSight;
}

export interface MapControlInput {
  mapName: string;
  zones: readonly MapControlZone[];
  ticks: readonly MapControlTick[];
  config?: Partial<MapControlConfig>;
}

export type ZoneControlState = "none" | "partial" | "controlled";

export interface VisibleSample {
  sampleId: string;
  position: Vec3;
  weight: number;
  viewers: readonly string[];
}

export interface TeamZoneControl {
  team: MapControlTeam;
  zoneId: string;
  visibleWeight: number;
  totalWeight: number;
  coverage: number;
  state: ZoneControlState;
  visibleSamples: readonly VisibleSample[];
}

export interface TeamControlRecord<T> {
  T: T;
  CT: T;
}

export type OverlayState =
  | "T-controlled"
  | "CT-controlled"
  | "contested"
  | "vacuum";

export interface ZoneControlFrame {
  zoneId: string;
  label: string;
  tags: readonly string[];
  teams: TeamControlRecord<TeamZoneControl>;
  overlayState: OverlayState;
}

export interface MapControlFrame {
  tick: number;
  seconds: number;
  zones: readonly ZoneControlFrame[];
}

export interface MapControlTimeline {
  mapName: string;
  config: MapControlConfig;
  frames: readonly MapControlFrame[];
}

export interface PlayerSampleVisibility {
  visible: boolean;
  reason:
    | "visible"
    | "dead"
    | "blinded"
    | "range"
    | "horizontal-fov"
    | "vertical-fov"
    | "static-los"
    | "smoke";
}

export interface ZoneControlLossEvent {
  team: MapControlTeam;
  zoneId: string;
  label: string;
  fromTick: number;
  toTick: number;
  fromSeconds: number;
  toSeconds: number;
  previousCoverage: number;
  coverage: number;
}
