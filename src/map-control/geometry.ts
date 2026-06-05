import type {
  ActiveSmoke,
  MapControlConfig,
  MapControlSamplePoint,
  MapControlTick,
  PlayerSampleVisibility,
  PlayerVisionState,
  Vec3,
} from "./types.js";

export const DEFAULT_MAP_CONTROL_CONFIG: MapControlConfig = {
  controlledCoverageThreshold: 0.6,
  partialCoverageThreshold: 0.001,
  defaultEyeHeight: 64,
  defaultHorizontalFovDeg: 90,
  defaultVisionRange: Infinity,
  defaultSmokeRadius: 144,
  smokeBlocksVision: true,
};

export function resolveMapControlConfig(config?: Partial<MapControlConfig>): MapControlConfig {
  return {
    ...DEFAULT_MAP_CONTROL_CONFIG,
    ...config,
  };
}

export function eyePosition(player: PlayerVisionState, config: MapControlConfig): Vec3 {
  return {
    x: player.position.x,
    y: player.position.y,
    z: player.position.z + (player.eyeHeight ?? config.defaultEyeHeight),
  };
}

export function distance(a: Vec3, b: Vec3): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const dz = a.z - b.z;
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

export function canPlayerSeeSample(
  viewer: PlayerVisionState,
  sample: MapControlSamplePoint,
  tick: MapControlTick,
  config: MapControlConfig,
): PlayerSampleVisibility {
  if (!viewer.isAlive) return { visible: false, reason: "dead" };
  if (viewer.isBlinded) return { visible: false, reason: "blinded" };

  const eye = eyePosition(viewer, config);
  const range = viewer.visionRange ?? config.defaultVisionRange;
  const targetDistance = distance(eye, sample.position);
  if (targetDistance > range) return { visible: false, reason: "range" };

  if (!isWithinHorizontalFov(eye, sample.position, viewer.yawDeg, viewer.horizontalFovDeg ?? config.defaultHorizontalFovDeg)) {
    return { visible: false, reason: "horizontal-fov" };
  }

  if (
    viewer.pitchDeg !== undefined &&
    viewer.verticalFovDeg !== undefined &&
    !isWithinVerticalFov(eye, sample.position, viewer.pitchDeg, viewer.verticalFovDeg)
  ) {
    return { visible: false, reason: "vertical-fov" };
  }

  if (
    config.staticLineOfSight &&
    !config.staticLineOfSight({ viewer, sample, tick, eyePosition: eye })
  ) {
    return { visible: false, reason: "static-los" };
  }

  if (
    config.smokeBlocksVision &&
    (tick.smokes ?? []).some((smoke) => segmentIntersectsSmoke(eye, sample.position, smoke, config))
  ) {
    return { visible: false, reason: "smoke" };
  }

  return { visible: true, reason: "visible" };
}

export function segmentIntersectsSmoke(
  from: Vec3,
  to: Vec3,
  smoke: ActiveSmoke,
  config: MapControlConfig,
): boolean {
  const radius = smoke.radius ?? config.defaultSmokeRadius;
  return distancePointToSegment(smoke.position, from, to) <= radius;
}

export function isWithinHorizontalFov(
  origin: Vec3,
  target: Vec3,
  yawDeg: number,
  horizontalFovDeg: number,
): boolean {
  const dx = target.x - origin.x;
  const dy = target.y - origin.y;
  if (dx === 0 && dy === 0) return true;

  const targetYaw = radiansToDegrees(Math.atan2(dy, dx));
  return Math.abs(shortestAngleDeltaDeg(normalizeDeg(yawDeg), normalizeDeg(targetYaw))) <= horizontalFovDeg / 2;
}

export function isWithinVerticalFov(
  origin: Vec3,
  target: Vec3,
  pitchDeg: number,
  verticalFovDeg: number,
): boolean {
  const dx = target.x - origin.x;
  const dy = target.y - origin.y;
  const dz = target.z - origin.z;
  const horizontalDistance = Math.sqrt(dx * dx + dy * dy);
  const targetPitch = radiansToDegrees(Math.atan2(dz, horizontalDistance));
  return Math.abs(shortestAngleDeltaDeg(normalizeDeg(pitchDeg), normalizeDeg(targetPitch))) <= verticalFovDeg / 2;
}

function distancePointToSegment(point: Vec3, from: Vec3, to: Vec3): number {
  const vx = to.x - from.x;
  const vy = to.y - from.y;
  const vz = to.z - from.z;
  const wx = point.x - from.x;
  const wy = point.y - from.y;
  const wz = point.z - from.z;

  const segmentLengthSquared = vx * vx + vy * vy + vz * vz;
  if (segmentLengthSquared === 0) return distance(point, from);

  const t = clamp((wx * vx + wy * vy + wz * vz) / segmentLengthSquared, 0, 1);
  const projected = {
    x: from.x + t * vx,
    y: from.y + t * vy,
    z: from.z + t * vz,
  };
  return distance(point, projected);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function normalizeDeg(deg: number): number {
  const normalized = deg % 360;
  return normalized < 0 ? normalized + 360 : normalized;
}

function shortestAngleDeltaDeg(a: number, b: number): number {
  const delta = normalizeDeg(b - a);
  return delta > 180 ? delta - 360 : delta;
}

function radiansToDegrees(rad: number): number {
  return (rad * 180) / Math.PI;
}
