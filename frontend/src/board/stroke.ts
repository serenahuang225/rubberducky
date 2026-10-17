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
};

export class StrokeMachine {
  private active: ActiveStroke | null = null;

  constructor(private readonly callbacks: StrokeCallbacks) {}

  /** Start a stroke. Returns false when another pointer already owns one (no splicing). */
  begin(pointerId: string, point: LogicalPoint): boolean {
    if (this.active !== null || !isFinitePoint(point)) {
      return false;
    }
    this.active = { pointerId, points: [point] };
    this.callbacks.onPreview(this.active.points);
    return true;
  }

  /** Extend the active stroke. Unknown pointers and non-finite points are ignored. */
  move(pointerId: string, point: LogicalPoint): void {
    if (this.active === null || this.active.pointerId !== pointerId || !isFinitePoint(point)) {
      return;
    }
    // Past the server limit the stroke keeps its first MAX_PATH_POINTS points.
    if (this.active.points.length >= MAX_PATH_POINTS) {
      return;
    }
    this.active.points.push(point);
    this.callbacks.onPreview(this.active.points);
  }

  /** Finish the active stroke. A stroke with no moves commits as a dot. */
  end(pointerId: string): void {
    if (this.active === null || this.active.pointerId !== pointerId) {
      return;
    }
    const finished = this.active;
    this.active = null;
    this.callbacks.onCommit(finished.points);
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
