/**
 * SVG path helpers, bounds and stroke hit-testing for the shared renderer.
 *
 * All geometry here is in logical board units. Paths are built from validated point lists
 * only; no SVG/XML/HTML strings ever enter the renderer from outside.
 */

import { PEN_WIDTH, type LogicalPoint } from './geometry';

export type Bounds = { minX: number; minY: number; maxX: number; maxY: number };

function fmt(point: LogicalPoint): string {
  return `${round(point.x)} ${round(point.y)}`;
}

/**
 * Smooth SVG path for two or more points; null for a dot (rendered as a circle).
 *
 * Two points stay a straight segment. Longer strokes use quadratic segments through
 * the midpoints, with each sample as the control, so corners round off while the
 * ink still passes along the samples the server stored.
 */
export function pointsToPathData(points: readonly LogicalPoint[]): string | null {
  if (points.length < 2) {
    return null;
  }
  if (points.length === 2) {
    return `M ${fmt(points[0])} L ${fmt(points[1])}`;
  }
  const parts = [`M ${fmt(points[0])}`];
  for (let index = 1; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const midX = (current.x + next.x) / 2;
    const midY = (current.y + next.y) / 2;
    parts.push(`Q ${fmt(current)} ${round(midX)} ${round(midY)}`);
  }
  parts.push(`L ${fmt(points[points.length - 1])}`);
  return parts.join(' ');
}

/** A dot (single-point stroke) renders as a small filled disc of pen width. */
export const DOT_RADIUS = PEN_WIDTH * 1.6;

export function pointsBounds(points: readonly LogicalPoint[]): Bounds | null {
  if (points.length === 0) {
    return null;
  }
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const point of points) {
    minX = Math.min(minX, point.x);
    minY = Math.min(minY, point.y);
    maxX = Math.max(maxX, point.x);
    maxY = Math.max(maxY, point.y);
  }
  return { minX, minY, maxX, maxY };
}

export function unionBounds(a: Bounds | null, b: Bounds | null): Bounds | null {
  if (a === null) return b;
  if (b === null) return a;
  return {
    minX: Math.min(a.minX, b.minX),
    minY: Math.min(a.minY, b.minY),
    maxX: Math.max(a.maxX, b.maxX),
    maxY: Math.max(a.maxY, b.maxY),
  };
}

function distanceToSegment(point: LogicalPoint, a: LogicalPoint, b: LogicalPoint): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) {
    return Math.hypot(point.x - a.x, point.y - a.y);
  }
  const t = Math.max(
    0,
    Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSquared),
  );
  return Math.hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy));
}

/** Shortest distance from a point to a polyline (a single point is a dot). */
export function distanceToStroke(point: LogicalPoint, stroke: readonly LogicalPoint[]): number {
  if (stroke.length === 0) {
    return Infinity;
  }
  if (stroke.length === 1) {
    return Math.hypot(point.x - stroke[0].x, point.y - stroke[0].y);
  }
  let best = Infinity;
  for (let index = 0; index < stroke.length - 1; index += 1) {
    best = Math.min(best, distanceToSegment(point, stroke[index], stroke[index + 1]));
  }
  return best;
}

/** Comfortable erase tap tolerance in logical units (roughly a fingertip at fit scale). */
export const ERASE_TOLERANCE = 28;

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
