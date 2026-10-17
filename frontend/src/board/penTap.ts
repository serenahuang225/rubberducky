/**
 * A pen tap is a touch that barely moves. Two of those, close together and close in
 * time, undo the last mark instead of leaving two dots.
 */

import type { LogicalPoint } from './geometry';

/** How far a touch may wander, in logical units, and still count as a tap. */
export const PEN_TAP_RADIUS = 36;
/** Second tap must arrive within this many milliseconds. */
export const DOUBLE_TAP_MS = 320;
/** Second tap must land within this many logical units of the first. */
export const DOUBLE_TAP_SEPARATION = 80;

export function isPenTap(points: readonly LogicalPoint[]): boolean {
  if (points.length === 0) {
    return false;
  }
  const origin = points[0];
  for (const point of points) {
    if (Math.hypot(point.x - origin.x, point.y - origin.y) > PEN_TAP_RADIUS) {
      return false;
    }
  }
  return true;
}

export type PenTapDecision =
  | { action: 'commit' }
  | { action: 'hold' }
  | { action: 'undo' }
  | { action: 'commit-held'; held: readonly LogicalPoint[] }
  | { action: 'commit-then-hold'; held: readonly LogicalPoint[] };

function copyPoints(points: readonly LogicalPoint[]): LogicalPoint[] {
  return points.map((point) => ({ x: point.x, y: point.y }));
}

function near(a: LogicalPoint, b: LogicalPoint): boolean {
  return Math.hypot(a.x - b.x, a.y - b.y) <= DOUBLE_TAP_SEPARATION;
}

/** Remembers one tap long enough to see whether a second tap follows it. */
export class PenTapSwitch {
  private pending: { points: LogicalPoint[]; at: number } | null = null;

  note(points: readonly LogicalPoint[], now: number): PenTapDecision {
    if (!isPenTap(points)) {
      const held = this.pending;
      this.pending = null;
      return held === null ? { action: 'commit' } : { action: 'commit-held', held: held.points };
    }
    const held = this.pending;
    if (held !== null && now - held.at <= DOUBLE_TAP_MS && near(held.points[0], points[0])) {
      this.pending = null;
      return { action: 'undo' };
    }
    this.pending = { points: copyPoints(points), at: now };
    return held === null
      ? { action: 'hold' }
      : { action: 'commit-then-hold', held: held.points };
  }

  /** The tap still waiting, if the double-tap window has closed. */
  take(): readonly LogicalPoint[] | null {
    const held = this.pending;
    this.pending = null;
    return held?.points ?? null;
  }
}
