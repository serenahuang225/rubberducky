/**
 * The shared whiteboard canvas: one component for native and web.
 *
 * It fits the fixed logical board (1600 x 1200) uniformly into whatever space it is
 * given, renders durable scene objects and the live stroke with react-native-svg, wires
 * the platform input layer, and cancels any in-progress stroke when the layout changes
 * so a resize can never join points across two different transforms. Authorship is
 * exposed to assistive technology through text labels, never through color alone.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { StyleSheet, Text, View, type LayoutChangeEvent } from 'react-native';
import Svg, { G } from 'react-native-svg';

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
import { payloadPoints, type SceneObjectRecord } from '../board/sceneTypes';

import { BoardInputLayer, type BoardInputHandle, type BoardInputMode } from './BoardInputLayer';
import {
  describeObject,
  LiveStroke,
  orderedObjects,
  PendingStrokeView,
  SceneObjectView,
} from './SceneObjectView';

export type PendingStroke = {
  id: string;
  points: readonly LogicalPoint[];
};

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
  theme: BoardTheme;
  mode: BoardInputMode;
  /** Commit a finished student stroke (logical points; a single point is a dot). */
  onStroke: (points: readonly LogicalPoint[]) => void;
  /** Erase mode: the learner tapped near one of their own marks. */
  onEraseAt: (objectId: string) => void;
  /** Frozen while a save is in flight so the board cannot go stale underneath. */
  inputDisabled?: boolean;
  testID?: string;
};

export const EARLIER_WORK_OPACITY = 0.4;

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
  theme,
  mode,
  onStroke,
  onEraseAt,
  inputDisabled = false,
  testID,
}: WhiteboardCanvasProps) {
  const [transform, setTransform] = useState<ViewTransform>(() => computeFitTransform(1, 1));
  // Input is ignored until the first real layout measurement: the placeholder 1x1 fit
  // would squash any point into a board corner, so a stroke drawn that early would be
  // garbage. Better to ignore input for a frame than to commit a degenerate mark.
  const [measured, setMeasured] = useState(false);
  const [livePoints, setLivePoints] = useState<readonly LogicalPoint[]>([]);
  const inputRef = useRef<BoardInputHandle>(null);
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

  const handleStroke = useCallback(
    (points: readonly LogicalPoint[]) => {
      setLivePoints([]);
      onStroke(points);
    },
    [onStroke],
  );

  const handleCancel = useCallback(() => {
    setLivePoints([]);
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
      style={[styles.frame, { backgroundColor: theme.board, borderColor: theme.boardEdge }]}
      onLayout={onLayout}
      accessibilityLabel={summary}
      accessibilityRole="image"
    >
      <BoardInputLayer
        ref={inputRef}
        mode={mode}
        disabled={inputDisabled || !measured}
        getTransform={getTransform}
        onPreview={setLivePoints}
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
          {ordered.map((object) => (
            <G
              key={object.id}
              opacity={earlier.has(object.id) ? EARLIER_WORK_OPACITY : 1}
            >
              <SceneObjectView object={object} theme={theme} resolveTarget={resolveTarget} />
            </G>
          ))}
          {/* Queued-but-unsaved strokes stay visible, faded, never mistaken for saved. */}
          {pendingStrokes.map((stroke) => (
            <PendingStrokeView key={stroke.id} points={stroke.points} theme={theme} />
          ))}
          <LiveStroke points={livePoints} theme={theme} />
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

const styles = StyleSheet.create({
  frame: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 12,
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
