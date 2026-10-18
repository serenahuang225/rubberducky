/**
 * Shared SVG renderer for durable scene objects.
 *
 * Every durable object kind the server can commit renders here for both native and web:
 * student paths and dots, tutor paths, the five shapes (circle, rectangle, line, bracket,
 * arrow), safe math text, problem statements, highlight washes and focus frames. Ink
 * colors come only from the fixed session palette keyed by the server-assigned color
 * role; the renderer never accepts a color from the payload.
 */

import React from 'react';
import { Circle, Ellipse, G, Line, Path, Rect, Text as SvgText } from 'react-native-svg';

import type { LogicalPoint } from '../board/geometry';
import { PEN_WIDTH, STUDENT_INK_WIDTH } from '../board/geometry';
import { colorForRole, type BoardTheme } from '../board/palette';
import { font } from '../theme/tokens';
import { DOT_RADIUS, pointsBounds, pointsToPathData, unionBounds, type Bounds } from '../board/pathData';
import {
  payloadPoint,
  payloadPoints,
  payloadRole,
  payloadText,
  type SceneObjectRecord,
} from '../board/sceneTypes';

const STATEMENT_FONT_SIZE = 52;
const MATH_FONT_SIZE = 44;
const TEACHING_FONT_SIZE = 28;
const TEACHING_LINE_HEIGHT = 36;
const BRACKET_TICK = 26;
const ARROW_HEAD = 22;

/** Text bounds estimate for highlight washes (the server owns the true layout). */
function textBounds(at: LogicalPoint, text: string, fontSize: number): Bounds {
  const width = Math.max(1, text.length) * fontSize * 0.56;
  return { minX: at.x - 8, minY: at.y - fontSize, maxX: at.x + width + 8, maxY: at.y + 12 };
}

function teachingLines(payload: Record<string, unknown>, text: string): string[] {
  const stored = payload.lines;
  if (Array.isArray(stored) && stored.every((line) => typeof line === 'string' && line.length > 0)) {
    return stored;
  }
  const width = 68;
  const lines: string[] = [];
  let current = '';
  for (const word of text.split(/\s+/)) {
    if (word.length === 0) continue;
    const piece = current ? `${current} ${word}` : word;
    if (piece.length > width && current) {
      lines.push(current);
      current = word;
    } else {
      current = piece;
    }
  }
  if (current) lines.push(current);
  return lines.slice(0, 22);
}

/** Approximate logical bounds of one object, used by highlight washes. */
export function objectBounds(object: SceneObjectRecord): Bounds | null {
  const { kind, payload } = object;
  if (kind === 'path' || kind === 'draw_path') {
    return pointsBounds(payloadPoints(payload));
  }
  if (kind === 'text') {
    const text = payloadText(payload, 'text');
    const x = typeof payload.x === 'number' ? payload.x : null;
    const y = typeof payload.y === 'number' ? payload.y : null;
    if (text === null || x === null || y === null) return null;
    if (object.semantic_role === 'teaching_note') {
      const lines = teachingLines(payload, text);
      return {
        minX: x,
        minY: y - TEACHING_FONT_SIZE,
        maxX: x + 68 * TEACHING_FONT_SIZE * 0.5,
        maxY: y + Math.max(0, lines.length - 1) * TEACHING_LINE_HEIGHT + 8,
      };
    }
    return textBounds({ x, y }, text, STATEMENT_FONT_SIZE);
  }
  if (kind === 'add_math') {
    const text = payloadText(payload, 'text');
    const at = payloadPoint(payload, 'at');
    if (text === null || at === null) return null;
    return textBounds(at, text, MATH_FONT_SIZE);
  }
  const start = payloadPoint(payload, 'start');
  const end = payloadPoint(payload, 'end');
  if (start !== null && end !== null) {
    return {
      minX: Math.min(start.x, end.x),
      minY: Math.min(start.y, end.y),
      maxX: Math.max(start.x, end.x),
      maxY: Math.max(start.y, end.y),
    };
  }
  return null;
}

function bracketPath(start: LogicalPoint, end: LogicalPoint): string {
  const horizontal = Math.abs(end.x - start.x) >= Math.abs(end.y - start.y);
  if (horizontal) {
    // A square under-bracket spanning start -> end, opening upward.
    const y = end.y;
    return `M ${start.x} ${y - BRACKET_TICK} L ${start.x} ${y} L ${end.x} ${y} L ${end.x} ${y - BRACKET_TICK}`;
  }
  const x = start.x;
  return `M ${x + BRACKET_TICK} ${start.y} L ${x} ${start.y} L ${x} ${end.y} L ${x + BRACKET_TICK} ${end.y}`;
}

function arrowHead(start: LogicalPoint, end: LogicalPoint): string {
  const angle = Math.atan2(end.y - start.y, end.x - start.x);
  const left = angle + Math.PI * 0.82;
  const right = angle - Math.PI * 0.82;
  const x1 = end.x + ARROW_HEAD * Math.cos(left);
  const y1 = end.y + ARROW_HEAD * Math.sin(left);
  const x2 = end.x + ARROW_HEAD * Math.cos(right);
  const y2 = end.y + ARROW_HEAD * Math.sin(right);
  return `M ${end.x} ${end.y} L ${x1} ${y1} M ${end.x} ${end.y} L ${x2} ${y2}`;
}

export type SceneObjectViewProps = {
  object: SceneObjectRecord;
  theme: BoardTheme;
  /** Resolve a highlight's target bounds; missing targets render nothing. */
  resolveTarget?: (objectId: string) => SceneObjectRecord | null;
};

export function SceneObjectView({ object, theme, resolveTarget }: SceneObjectViewProps) {
  const { kind, payload } = object;
  const assigned = colorForRole(theme, payloadRole(payload));
  // The paper writing surface is yellow, which is also the tutor ink, so tutor
  // marks use the blue ink there. The chalkboard keeps yellow tutor ink.
  const ink =
    theme.name === "paper" && assigned === theme.tutorInk ? theme.studentInk : assigned;

  if (kind === 'path' || kind === 'draw_path') {
    const points = payloadPoints(payload);
    if (points.length === 0) return null;
    const storedWidth =
      typeof payload.width === 'number' && Number.isFinite(payload.width)
        ? payload.width
        : PEN_WIDTH;
    // Student ink is drawn heavier than the stored width so a fitted board still
    // reads as a pen. The server keeps assigning the fixed width.
    const width = object.author_role === 'student' ? Math.max(storedWidth, STUDENT_INK_WIDTH) : storedWidth;
    if (points.length === 1) {
      // A dot: one tap with no drag.
      return (
        <Circle cx={points[0].x} cy={points[0].y} r={Math.max(DOT_RADIUS, width / 2)} fill={ink} />
      );
    }
    const d = pointsToPathData(points);
    if (d === null) return null;
    return (
      <Path d={d} stroke={ink} strokeWidth={width} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    );
  }

  if (kind === 'text' && object.semantic_role === 'teaching_note') {
    const text = payloadText(payload, 'text');
    const at =
      typeof payload.x === 'number' && typeof payload.y === 'number'
        ? { x: payload.x, y: payload.y }
        : null;
    if (text === null || at === null) return null;
    const lines = teachingLines(payload, text);
    return (
      <G>
        {lines.map((line, index) => (
          <SvgText
            key={`${object.id}-${index}`}
            x={at.x}
            y={at.y + index * TEACHING_LINE_HEIGHT}
            fontSize={TEACHING_FONT_SIZE}
            fill={ink}
            fontFamily={font.sans}
          >
            {line}
          </SvgText>
        ))}
      </G>
    );
  }

  if (kind === 'text' || kind === 'add_math') {
    const text = payloadText(payload, 'text');
    const at = kind === 'text'
      ? (typeof payload.x === 'number' && typeof payload.y === 'number'
          ? { x: payload.x, y: payload.y }
          : null)
      : payloadPoint(payload, 'at');
    if (text === null || at === null) return null;
    const fontSize = kind === 'text' ? STATEMENT_FONT_SIZE : MATH_FONT_SIZE;
    return (
      <SvgText x={at.x} y={at.y} fontSize={fontSize} fill={ink} fontFamily={font.sans}>
        {text}
      </SvgText>
    );
  }

  if (kind === 'highlight') {
    const targetId = payloadText(payload, 'target_object_id');
    const target = targetId !== null && resolveTarget ? resolveTarget(targetId) : null;
    const bounds = target !== null ? objectBounds(target) : null;
    if (bounds === null) return null;
    return (
      <Rect
        x={bounds.minX - 10}
        y={bounds.minY - 10}
        width={bounds.maxX - bounds.minX + 20}
        height={bounds.maxY - bounds.minY + 20}
        fill={theme.highlightFill}
      />
    );
  }

  if (kind === 'focus_region') {
    const start = payloadPoint(payload, 'start');
    const end = payloadPoint(payload, 'end');
    if (start === null || end === null) return null;
    return (
      <Rect
        x={Math.min(start.x, end.x)}
        y={Math.min(start.y, end.y)}
        width={Math.abs(end.x - start.x)}
        height={Math.abs(end.y - start.y)}
        fill="none"
        stroke={theme.focusOutline}
        strokeWidth={4}
        strokeDasharray="18 12"
      />
    );
  }

  // Shapes: circle, rectangle, line, bracket, arrow.
  const start = payloadPoint(payload, 'start');
  const end = payloadPoint(payload, 'end');
  if (start === null || end === null) return null;

  if (kind === 'circle') {
    return (
      <Ellipse
        cx={(start.x + end.x) / 2}
        cy={(start.y + end.y) / 2}
        rx={Math.abs(end.x - start.x) / 2}
        ry={Math.abs(end.y - start.y) / 2}
        stroke={ink}
        strokeWidth={PEN_WIDTH}
        fill="none"
      />
    );
  }
  if (kind === 'rectangle') {
    return (
      <Rect
        x={Math.min(start.x, end.x)}
        y={Math.min(start.y, end.y)}
        width={Math.abs(end.x - start.x)}
        height={Math.abs(end.y - start.y)}
        stroke={ink}
        strokeWidth={PEN_WIDTH}
        fill="none"
      />
    );
  }
  if (kind === 'line') {
    return <Line x1={start.x} y1={start.y} x2={end.x} y2={end.y} stroke={ink} strokeWidth={PEN_WIDTH} strokeLinecap="round" />;
  }
  if (kind === 'bracket') {
    return (
      <Path d={bracketPath(start, end)} stroke={ink} strokeWidth={PEN_WIDTH} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    );
  }
  if (kind === 'arrow') {
    return (
      <G>
        <Line x1={start.x} y1={start.y} x2={end.x} y2={end.y} stroke={ink} strokeWidth={PEN_WIDTH} strokeLinecap="round" />
        <Path d={arrowHead(start, end)} stroke={ink} strokeWidth={PEN_WIDTH} fill="none" strokeLinecap="round" />
      </G>
    );
  }
  return null;
}

/** Live in-progress student stroke (not yet committed to the scene). */
export function LiveStroke({ points, theme }: { points: readonly LogicalPoint[]; theme: BoardTheme }) {
  if (points.length === 0) return null;
  const ink = theme.studentInk;
  if (points.length === 1) {
    return <Circle cx={points[0].x} cy={points[0].y} r={STUDENT_INK_WIDTH / 2} fill={ink} />;
  }
  const d = pointsToPathData(points);
  if (d === null) return null;
  return (
    <Path
      d={d}
      stroke={ink}
      strokeWidth={STUDENT_INK_WIDTH}
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  );
}

/** A finished stroke waiting in the durable outbox: visibly unsaved (faded), never
 *  confused with committed work, and never dropped from view while unsaved. */
export function PendingStrokeView({
  points,
  theme,
}: {
  points: readonly LogicalPoint[];
  theme: BoardTheme;
}) {
  if (points.length === 0) return null;
  const ink = theme.studentInk;
  return (
    <G opacity={0.45}>
      {points.length === 1 ? (
        <Circle cx={points[0].x} cy={points[0].y} r={STUDENT_INK_WIDTH / 2} fill={ink} />
      ) : (
        <Path
          d={pointsToPathData(points) ?? ''}
          stroke={ink}
          strokeWidth={STUDENT_INK_WIDTH}
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray="14 10"
        />
      )}
    </G>
  );
}

/** Stable render order: highlight washes and focus frames paint underneath ink. */
export function orderedObjects(objects: readonly SceneObjectRecord[]): SceneObjectRecord[] {
  const underlay = objects.filter((o) => o.kind === 'highlight' || o.kind === 'focus_region');
  const overlay = objects.filter((o) => o.kind !== 'highlight' && o.kind !== 'focus_region');
  return [...underlay, ...overlay];
}

/** Human-readable, color-independent description of one object for assistive tech. */
export function describeObject(object: SceneObjectRecord): string {
  const who = object.author_role === 'student' ? 'Your' : 'Tutor';
  const text = payloadText(object.payload, 'text');
  switch (object.semantic_role) {
    case 'problem_statement':
      return `Tutor posed the problem: "${text ?? ''}"`;
    case 'grouping_mark':
      return 'Tutor grouping mark around the parentheses';
    case 'emphasis':
      return 'Tutor highlight on your work';
    case 'focus':
      return 'Tutor focus frame';
    case 'annotation':
      return text !== null ? `Tutor note: "${text}"` : 'Tutor note';
    case 'teaching_note':
      return text !== null ? `Tutor explained: "${text}"` : 'Tutor explanation';
    default:
      if (object.kind === 'path') {
        const count = payloadPoints(object.payload).length;
        return count <= 1 ? `${who} dot` : `${who} pen stroke`;
      }
      return text !== null ? `${who} mark: "${text}"` : `${who} ${object.kind} mark`;
  }
}

/** Bounds union for the whole scene, e.g. for future fit-to-content views. */
export function sceneBounds(objects: readonly SceneObjectRecord[]): Bounds | null {
  return objects.reduce<Bounds | null>(
    (acc, object) => unionBounds(acc, objectBounds(object)),
    null,
  );
}
