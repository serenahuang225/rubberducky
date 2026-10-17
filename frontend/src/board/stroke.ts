/**
 * The shared stroke state machine.
 *
 * Both input adapters (web Pointer Events, native touch) normalize their raw events into
 * begin/move/end/cancel calls here, so the core rules live in exactly one place: one
 * active pointer owns a stroke, a single touch is a dot, non-finite points never enter a
 * stroke, and cancellation (pointer cancel, lost capture, backgrounding, layout change)
 * discards the in-progress stroke without committing anything or connecting lines.
 */

import { isFinitePoint, MAX_PATH_POINTS, type LogicalPoint } from './geometry';

/**
 * Movement, in logical units, required before another sample is kept.
 * Smaller jitter never becomes a corner; the latest point is still remembered
 * so the stroke finishes where the finger or pencil lifted.
 */
export const MIN_SAMPLE_DISTANCE = 3.5;

export type StrokeCallbacks = {
  /** In-progress points changed (also fired once on begin). */
  onPreview: (points: readonly LogicalPoint[]) => void;
  /** A finished stroke, including a single-point dot. */
  onCommit: (points: readonly LogicalPoint[]) => void;
  /** The in-progress stroke was discarded. */
  onCancel: () => void;
};

type ActiveStroke = {
  pointerId: string;
  points: LogicalPoint[];
  /** Latest sample that was too close to store, so the lift still lands on it. */
  tail: LogicalPoint | null;
};

function farEnough(from: LogicalPoint, to: LogicalPoint): boolean {
  return Math.hypot(to.x - from.x, to.y - from.y) >= MIN_SAMPLE_DISTANCE;
}

export class StrokeMachine {
  private active: ActiveStroke | null = null;

  constructor(private readonly callbacks: StrokeCallbacks) {}

  /** Start a stroke. Returns false when another pointer already owns one (no splicing). */
  begin(pointerId: string, point: LogicalPoint): boolean {
    if (this.active !== null || !isFinitePoint(point)) {
      return false;
    }
    this.active = { pointerId, points: [point], tail: null };
    this.callbacks.onPreview(this.active.points);
    return true;
  }

  /** Extend the active stroke. Unknown pointers and non-finite points are ignored. */
  move(pointerId: string, point: LogicalPoint): void {
    if (this.active === null || this.active.pointerId !== pointerId || !isFinitePoint(point)) {
      return;
    }
    this.note(point);
  }

  /** Keep a sample, or remember it as the tail when it is only jitter. */
  private note(point: LogicalPoint): void {
    const active = this.active;
    if (active === null || active.points.length >= MAX_PATH_POINTS) {
      return;
    }
    const last = active.points[active.points.length - 1];
    if (farEnough(last, point)) {
      active.points.push(point);
      active.tail = null;
      this.callbacks.onPreview(active.points);
      return;
    }
    active.tail = point;
    this.callbacks.onPreview([...active.points, point]);
  }

  /**
   * Finish the active stroke. A stroke with no moves commits as a dot.
   * `point` is the lift location when the input layer has one.
   */
  end(pointerId: string, point?: LogicalPoint | null): void {
    if (this.active === null || this.active.pointerId !== pointerId) {
      return;
    }
    if (point != null && isFinitePoint(point)) {
      this.note(point);
    }
    const tail = this.active.tail;
    if (tail !== null && this.active.points.length < MAX_PATH_POINTS) {
      const last = this.active.points[this.active.points.length - 1];
      if (Math.hypot(tail.x - last.x, tail.y - last.y) >= 0.5) {
        this.active.points.push(tail);
      }
    }
    const finished = this.active.points;
    this.active = null;
    this.callbacks.onCommit(finished);
  }

  /** Discard the active stroke, if any. Safe to call when idle. */
  cancel(): void {
    if (this.active === null) {
      return;
    }
    this.active = null;
    this.callbacks.onCancel();
  }

  isActive(): boolean {
    return this.active !== null;
  }

  activePointerId(): string | null {
    return this.active?.pointerId ?? null;
  }
}
