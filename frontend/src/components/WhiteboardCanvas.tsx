/**
 * The shared whiteboard canvas: one component for native and web.
 *
 * It fits the fixed logical board (1600 x 1200) uniformly into whatever space it is
 * given, renders durable scene objects and the live stroke with react-native-svg, wires
 * the platform input layer, and cancels any in-progress stroke when the layout changes
 * so a resize can never join points across two different transforms. Authorship is
 * exposed to assistive technology through text labels, never through color alone.
 */

import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { StyleSheet, Text, View, type LayoutChangeEvent } from 'react-native';
import Svg, { G, Path, Rect } from 'react-native-svg';

import {
  BOARD_HEIGHT,
  BOARD_WIDTH,
  computeFitTransform,
  transformChanged,
  type LogicalPoint,
  type ViewTransform,
} from '../board/geometry';
import type { BoardTheme } from '../board/palette';
import { distanceToStroke, ERASE_TOLERANCE } from '../board/pathData';
import { DOUBLE_TAP_MS, PenTapSwitch } from '../board/penTap';
import { payloadPoints, type SceneObjectRecord } from '../board/sceneTypes';

import { BoardInputLayer, type BoardInputHandle, type BoardInputMode } from './BoardInputLayer';
import {
  describeObject,
  LiveStroke,
  orderedObjects,
  PendingStrokeView,
  SceneObjectView,
  wordTotal,
} from './SceneObjectView';

export type PendingStroke = {
  id: string;
  points: readonly LogicalPoint[];
};

type LiveInkHandle = {
  setPoints: (points: readonly LogicalPoint[]) => void;
};

/** Owns the in-progress stroke so each sample does not redraw the saved scene. */
const LiveInk = forwardRef<LiveInkHandle, { theme: BoardTheme }>(function LiveInk({ theme }, ref) {
  const [points, setPoints] = useState<readonly LogicalPoint[]>([]);
  useImperativeHandle(ref, () => ({ setPoints }), []);
  return <LiveStroke points={points} theme={theme} />;
});

export type WhiteboardCanvasProps = {
  objects: readonly SceneObjectRecord[];
  /**
   * The current problem's statement object. On a later problem, the learner's ink written
   * before it is shown softened (never removed or altered) so the current equation and its
   * tutor marks stay legible; it remains on the board, erasable and in history.
   */
  currentStatementId?: string | null;
  /** Finished strokes held in the durable outbox, painted faded and honestly labeled. */
  pendingStrokes?: readonly PendingStroke[];
  /** Strokes drawn and still being saved, painted as solid ink so the pen does not flicker. */
  settlingStrokes?: readonly PendingStroke[];
  theme: BoardTheme;
  mode: BoardInputMode;
  /** Commit a finished student stroke (logical points; a single point is a dot). */
  onInkActivity?: () => void;
  onStroke: (points: readonly LogicalPoint[]) => void;
  /** Erase mode: the learner tapped near one of their own marks. */
  onEraseAt: (objectId: string) => void;
  /** Two quick taps in draw mode: undo the last mark, and do not ink the taps. */
  onDoubleTap?: () => void;
  /** Frozen while a save is in flight so the board cannot go stale underneath. */
  inputDisabled?: boolean;
  /**
   * Fade tutor marks that arrive after the board is already showing. Student ink is never
   * delayed. The first scene paints at full opacity.
   */
  animateTutorMarks?: boolean;
  testID?: string;
};

export const EARLIER_WORK_OPACITY = 0.4;

// Logical coordinates keep the grid aligned with ink when the board resizes.
const GRID_SPACING = 40;
const GRID_PATH = [
  ...Array.from({ length: BOARD_WIDTH / GRID_SPACING + 1 }, (_, i) =>
    `M ${i * GRID_SPACING} 0 V ${BOARD_HEIGHT}`),
  ...Array.from({ length: BOARD_HEIGHT / GRID_SPACING + 1 }, (_, i) =>
    `M 0 ${i * GRID_SPACING} H ${BOARD_WIDTH}`),
].join(' ');


/** Ids of the learner's marks written before the current (second or later) problem. */
export function earlierWorkIds(
  objects: readonly SceneObjectRecord[],
  currentStatementId: string | null,
): ReadonlySet<string> {
  const statement =
    currentStatementId === null ? undefined : objects.find((o) => o.id === currentStatementId);
  const problemNumber = statement?.payload.problem_number;
  if (statement === undefined || typeof problemNumber !== 'number' || problemNumber < 2) {
    return new Set();
  }
  const posedAt = Date.parse(statement.created_at ?? '');
  if (Number.isNaN(posedAt)) {
    return new Set();
  }
  return new Set(
    objects
      .filter((o) => o.author_role === 'student' && Date.parse(o.created_at ?? '') < posedAt)
      .map((o) => o.id),
  );
}

export function WhiteboardCanvas({
  objects,
  currentStatementId = null,
  pendingStrokes = [],
  settlingStrokes = [],
  theme,
  mode,
  onStroke,
  onInkActivity,
  onEraseAt,
  onDoubleTap,
  inputDisabled = false,
  animateTutorMarks = false,
  testID,
}: WhiteboardCanvasProps) {
  const [transform, setTransform] = useState<ViewTransform>(() => computeFitTransform(1, 1));
  // Input is ignored until the first real layout measurement: the placeholder 1x1 fit
  // would squash any point into a board corner, so a stroke drawn that early would be
  // garbage. Better to ignore input for a frame than to commit a degenerate mark.
  const [measured, setMeasured] = useState(false);
  const inputRef = useRef<BoardInputHandle>(null);
  const liveRef = useRef<LiveInkHandle>(null);
  const objectsRef = useRef(objects);
  useEffect(() => {
    objectsRef.current = objects;
  }, [objects]);

  const getTransform = useCallback(() => transform, [transform]);

  // A resize mid-stroke freezes (cancels) the stroke instead of mixing transforms.
  const onLayout = useCallback(
    (event: LayoutChangeEvent) => {
      const { width, height } = event.nativeEvent.layout;
      const next = computeFitTransform(width, height);
      if (width > 1 && height > 1) {
        setMeasured(true);
      }
      setTransform((previous) => {
        if (transformChanged(previous, next)) {
          inputRef.current?.cancelActiveStroke();
          return next;
        }
        return previous;
      });
    },
    [],
  );

  const handlePreview = useCallback((points: readonly LogicalPoint[]) => {
    liveRef.current?.setPoints(points);
    onInkActivity?.();
  }, [onInkActivity]);

  const onStrokeRef = useRef(onStroke);
  const onDoubleTapRef = useRef(onDoubleTap);
  useEffect(() => {
    onStrokeRef.current = onStroke;
    onDoubleTapRef.current = onDoubleTap;
  });
  const tapGate = useRef(new PenTapSwitch());
  const tapTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTapTimer = useCallback(() => {
    if (tapTimer.current !== null) {
      clearTimeout(tapTimer.current);
      tapTimer.current = null;
    }
  }, []);

  const flushHeldTap = useCallback(() => {
    const held = tapGate.current.take();
    if (held !== null) {
      onStrokeRef.current(held);
    }
  }, []);

  const armTapTimer = useCallback(() => {
    clearTapTimer();
    tapTimer.current = setTimeout(() => {
      tapTimer.current = null;
      flushHeldTap();
    }, DOUBLE_TAP_MS);
  }, [clearTapTimer, flushHeldTap]);

  useEffect(() => {
    const gate = tapGate.current;
    return () => {
      if (tapTimer.current !== null) {
        clearTimeout(tapTimer.current);
      }
      const held = gate.take();
      if (held !== null) {
        onStrokeRef.current(held);
      }
    };
  }, []);

  useEffect(() => {
    if (mode === 'draw') {
      return;
    }
    clearTapTimer();
    flushHeldTap();
  }, [clearTapTimer, flushHeldTap, mode]);

  const handleStroke = useCallback(
    (points: readonly LogicalPoint[]) => {
      liveRef.current?.setPoints([]);
      if (mode !== 'draw' || onDoubleTapRef.current === undefined) {
        clearTapTimer();
        flushHeldTap();
        onStrokeRef.current(points);
        return;
      }
      const decision = tapGate.current.note(points, Date.now());
      if (decision.action === 'commit') {
        clearTapTimer();
        onStrokeRef.current(points);
        return;
      }
      if (decision.action === 'commit-held') {
        clearTapTimer();
        onStrokeRef.current(decision.held);
        onStrokeRef.current(points);
        return;
      }
      if (decision.action === 'undo') {
        clearTapTimer();
        onDoubleTapRef.current?.();
        return;
      }
      if (decision.action === 'commit-then-hold') {
        onStrokeRef.current(decision.held);
      }
      armTapTimer();
    },
    [armTapTimer, clearTapTimer, flushHeldTap, mode],
  );

  const handleCancel = useCallback(() => {
    liveRef.current?.setPoints([]);
  }, []);

  const handleTap = useCallback(
    (point: LogicalPoint) => {
      // Erase mode: pick the nearest own mark within a comfortable tolerance.
      let bestId: string | null = null;
      let bestDistance = ERASE_TOLERANCE;
      for (const object of objectsRef.current) {
        if (object.author_role !== 'student' || object.kind !== 'path') {
          continue;
        }
        const distance = distanceToStroke(point, payloadPoints(object.payload));
        if (distance <= bestDistance) {
          bestDistance = distance;
          bestId = object.id;
        }
      }
      if (bestId !== null) {
        onEraseAt(bestId);
      }
    },
    [onEraseAt],
  );

  // Ids present on the first paint stay immediate. Later tutor marks fade in; student ink does not.
  const [initialIds] = useState(
    () => new Set(objects.map((object) => object.id)),
  );
  // Newly arrived tutor notes reveal one word at a time. Notes already on the board do not.
  const [revealedWords, setRevealedWords] = useState<Record<string, number>>({});
  useEffect(() => {
    if (!animateTutorMarks) return;
    const pending = objects.filter(
      (object) =>
        object.semantic_role === 'teaching_note' &&
        object.author_role === 'tutor' &&
        !initialIds.has(object.id) &&
        typeof object.payload.text === 'string',
    );
    if (pending.length === 0) return;
    const timer = setInterval(() => {
      setRevealedWords((current) => {
        let changed = false;
        const next = { ...current };
        for (const object of pending) {
          const text = object.payload.text;
          if (typeof text !== 'string') continue;
          const total = wordTotal(text);
          const shown = next[object.id] ?? 0;
          if (shown < total) {
            next[object.id] = shown + 1;
            changed = true;
          }
        }
        return changed ? next : current;
      });
    }, WORD_MS);
    return () => clearInterval(timer);
  }, [animateTutorMarks, initialIds, objects]);
  const ordered = useMemo(() => orderedObjects(objects), [objects]);
  const earlier = useMemo(
    () => earlierWorkIds(objects, currentStatementId),
    [objects, currentStatementId],
  );
  const byId = useMemo(() => {
    const map = new Map<string, SceneObjectRecord>();
    for (const object of objects) {
      map.set(object.id, object);
    }
    return map;
  }, [objects]);
  const resolveTarget = useCallback(
    (objectId: string) => byId.get(objectId) ?? null,
    [byId],
  );

  const studentCount = objects.filter((o) => o.author_role === 'student').length;
  const tutorCount = objects.length - studentCount;
  const summary =
    objects.length === 0
      ? 'Whiteboard, empty'
      : `Whiteboard: ${studentCount} of your marks, ${tutorCount} tutor marks`;

  return (
    <View
      testID={testID}
      style={[styles.frame, { backgroundColor: theme.board }]}
      onLayout={onLayout}
      accessibilityLabel={summary}
      accessibilityRole="image"
    >
      <BoardInputLayer
        ref={inputRef}
        mode={mode}
        disabled={inputDisabled || !measured}
        getTransform={getTransform}
        onPreview={handlePreview}
        onStroke={handleStroke}
        onStrokeCancel={handleCancel}
        onTap={handleTap}
        style={styles.inputLayer}
      >
        <Svg
          width={transform.viewWidth}
          height={transform.viewHeight}
          viewBox={`${-transform.offsetX / transform.scale} ${-transform.offsetY / transform.scale} ${transform.viewWidth / transform.scale} ${transform.viewHeight / transform.scale}`}
        >
          <Rect
            x={0}
            y={0}
            width={BOARD_WIDTH}
            height={BOARD_HEIGHT}
            fill={theme.board}
            stroke={theme.board}
            strokeWidth={1 / transform.scale}
          />
          <Path
            d={GRID_PATH}
            fill="none"
            stroke={theme.studentInk}
            strokeOpacity={theme.name === 'paper' ? 0.12 : 0.16}
            strokeWidth={0.75 / transform.scale}
            pointerEvents="none"
          />
          {ordered.map((object) => {
            const arriving =
              animateTutorMarks &&
              object.author_role === 'tutor' &&
              !initialIds.has(object.id);
            const streaming = arriving && object.semantic_role === 'teaching_note';
            const view = (
              <SceneObjectView
                object={object}
                theme={theme}
                resolveTarget={resolveTarget}
                visibleWords={streaming ? (revealedWords[object.id] ?? 0) : undefined}
              />
            );
            return (
              <G
                key={object.id}
                opacity={earlier.has(object.id) ? EARLIER_WORK_OPACITY : 1}
              >
                {arriving && !streaming ? <ArrivingInk>{view}</ArrivingInk> : view}
              </G>
            );
          })}
          {/* Queued-but-unsaved strokes stay visible, faded, never mistaken for saved. */}
          {pendingStrokes.map((stroke) => (
            <PendingStrokeView key={stroke.id} points={stroke.points} theme={theme} />
          ))}
          {settlingStrokes.map((stroke) => (
            <LiveStroke key={stroke.id} points={stroke.points} theme={theme} />
          ))}
          <LiveInk ref={liveRef} theme={theme} />
        </Svg>
      </BoardInputLayer>
      {/* Color-independent board contents for screen readers. */}
      <View
        testID={testID ? `${testID}-contents` : undefined}
        accessibilityLabel="Board contents"
        style={styles.visuallyHidden}
        pointerEvents="none"
      >
        {objects.map((object) => (
          <Text key={object.id}>{describeObject(object)}</Text>
        ))}
        {pendingStrokes.map((stroke) => (
          <Text key={stroke.id}>
            {stroke.points.length <= 1 ? 'Your dot' : 'Your pen stroke'} (not saved yet)
          </Text>
        ))}
        {objects.length === 0 && pendingStrokes.length === 0 ? (
          <Text>The board is empty.</Text>
        ) : null}
      </View>
    </View>
  );
}

const ARRIVE_MS = 180;
const WORD_MS = 90;

/** Opacity fade for a tutor mark that has just arrived. Starts at 0 on first paint. */
function ArrivingInk({ children }: { children: React.ReactNode }) {
  const [opacity, setOpacity] = useState(0);
  useEffect(() => {
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ARRIVE_MS);
      setOpacity(1 - (1 - t) ** 3);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);
  return <G opacity={opacity}>{children}</G>;
}

const styles = StyleSheet.create({
  frame: {
    flex: 1,
    minHeight: 0,
    borderRadius: 28,
    overflow: 'hidden',
  },
  inputLayer: {
    flex: 1,
  },
  // Kept in the accessibility tree but invisible and non-interactive.
  visuallyHidden: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: 1,
    height: 1,
    opacity: 0,
    overflow: 'hidden',
  },
});

export const CANVAS_BOARD_ASPECT = BOARD_WIDTH / BOARD_HEIGHT;
