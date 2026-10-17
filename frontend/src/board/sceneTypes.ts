/**
 * Client-side view of durable scene object payloads.
 *
 * The server validates every payload; these types describe what the shared SVG renderer
 * may encounter. `color_role` is the only color information in a scene object — actual
 * ink colors come from the fixed session palette, so restoration and themes can never
 * collide student and tutor ink.
 */

import type { LogicalPoint } from './geometry';

export type ColorRoleValue = 'student' | 'tutor';

export type SceneObjectRecord = {
  id: string;
  author_role: 'student' | 'tutor';
  semantic_role: string;
  kind: string;
  payload: Record<string, unknown>;
};

export function payloadPoints(payload: Record<string, unknown>): LogicalPoint[] {
  const raw = payload.points;
  if (!Array.isArray(raw)) {
    return [];
  }
  const points: LogicalPoint[] = [];
  for (const item of raw) {
    if (
      typeof item === 'object' &&
      item !== null &&
      typeof (item as LogicalPoint).x === 'number' &&
      typeof (item as LogicalPoint).y === 'number' &&
      Number.isFinite((item as LogicalPoint).x) &&
      Number.isFinite((item as LogicalPoint).y)
    ) {
      points.push({ x: (item as LogicalPoint).x, y: (item as LogicalPoint).y });
    }
  }
  return points;
}

export function payloadPoint(payload: Record<string, unknown>, key: string): LogicalPoint | null {
  const raw = payload[key];
  if (
    typeof raw === 'object' &&
    raw !== null &&
    typeof (raw as LogicalPoint).x === 'number' &&
    typeof (raw as LogicalPoint).y === 'number' &&
    Number.isFinite((raw as LogicalPoint).x) &&
    Number.isFinite((raw as LogicalPoint).y)
  ) {
    return { x: (raw as LogicalPoint).x, y: (raw as LogicalPoint).y };
  }
  return null;
}

export function payloadText(payload: Record<string, unknown>, key: string): string | null {
  const raw = payload[key];
  return typeof raw === 'string' && raw.length > 0 ? raw : null;
}

export function payloadRole(payload: Record<string, unknown>): ColorRoleValue {
  return payload.color_role === 'student' ? 'student' : 'tutor';
}

/** Kinds that paint underneath other marks (highlight washes and focus frames). */
export const UNDERLAY_KINDS = new Set(['highlight', 'focus_region']);
