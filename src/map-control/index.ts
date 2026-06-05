export { computeMapControl, teams } from "./compute.js";
export { detectControlLossEvents } from "./events.js";
export type { ControlLossOptions } from "./events.js";
export {
  DEFAULT_MAP_CONTROL_CONFIG,
  canPlayerSeeSample,
  distance,
  eyePosition,
  isWithinHorizontalFov,
  isWithinVerticalFov,
  resolveMapControlConfig,
  segmentIntersectsSmoke,
} from "./geometry.js";
export type {
  ActiveSmoke,
  MapControlConfig,
  MapControlFrame,
  MapControlInput,
  MapControlSamplePoint,
  MapControlTeam,
  MapControlTick,
  MapControlTimeline,
  MapControlZone,
  OverlayState,
  PlayerSampleVisibility,
  PlayerVisionState,
  StaticLineOfSight,
  StaticLineOfSightQuery,
  TeamControlRecord,
  TeamZoneControl,
  Vec3,
  VisibleSample,
  ZoneControlFrame,
  ZoneControlLossEvent,
  ZoneControlState,
} from "./types.js";
export { MAP_CONTROL_TEAMS } from "./types.js";
