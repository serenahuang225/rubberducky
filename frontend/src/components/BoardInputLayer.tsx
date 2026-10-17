/**
 * Native (Expo Go iPad) board input layer.
 *
 * Uses React Native's built-in responder touch events — no DOM APIs — and normalizes
 * them through the shared touch rules: one active touch owns the stroke, extra contacts
 * (palm, second finger) are ignored, and AppState backgrounding cancels the stroke.
 * This is the app-side single-pointer rule, not a claim of OS palm rejection.
 */

import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import { AppState, View, type GestureResponderEvent, type ViewStyle } from 'react-native';

import type { LogicalPoint, ViewTransform } from '../board/geometry';
import { toLogical } from '../board/geometry';
import { StrokeMachine } from '../board/stroke';
import {
  handleTouchCancel,
  handleTouchEnd,
  handleTouchMove,
  handleTouchStart,
  type TouchSample,
} from '../board/touchEvents';

export type BoardInputMode = 'draw' | 'erase';

export type BoardInputLayerProps = {
  mode: BoardInputMode;
  /** While true (a save is in flight), all input is ignored. */
  disabled?: boolean;
  /** Current screen->logical transform; read at event time so resize never goes stale. */
  getTransform: () => ViewTransform;
  onPreview: (points: readonly LogicalPoint[]) => void;
  onStroke: (points: readonly LogicalPoint[]) => void;
  onStrokeCancel: () => void;
  /** Erase mode: a quick touch reports a tap point instead of starting a stroke. */
  onTap: (point: LogicalPoint) => void;
  style?: ViewStyle;
  children?: React.ReactNode;
};

export type BoardInputHandle = {
  /** Freeze/cancel the in-progress stroke (layout change, backgrounding, new problem). */
  cancelActiveStroke: () => void;
  strokeInProgress: () => boolean;
};

type RawTouch = { identifier?: number | string; locationX?: number; locationY?: number };

function toSamples(touches: readonly RawTouch[] | undefined): TouchSample[] {
  if (!Array.isArray(touches)) {
    return [];
  }
  const samples: TouchSample[] = [];
  for (const touch of touches) {
    const id = touch.identifier;
    const x = touch.locationX;
    const y = touch.locationY;
    if (
      (typeof id === 'number' || typeof id === 'string') &&
      typeof x === 'number' &&
      typeof y === 'number' &&
      Number.isFinite(x) &&
      Number.isFinite(y)
    ) {
      samples.push({ identifier: String(id), x, y });
    }
  }
  return samples;
}

export const BoardInputLayer = forwardRef<BoardInputHandle, BoardInputLayerProps>(
  function BoardInputLayer(props, ref) {
    const propsRef = useRef(props);
    propsRef.current = props;

    const machine = useMemo(
      () =>
        new StrokeMachine({
          onPreview: (points) => propsRef.current.onPreview(points),
          onCommit: (points) => propsRef.current.onStroke(points),
          onCancel: () => propsRef.current.onStrokeCancel(),
        }),
      [],
    );

    const cancelActiveStroke = useCallback(() => {
      handleTouchCancel(machine);
    }, [machine]);

    useImperativeHandle(
      ref,
      () => ({
        cancelActiveStroke,
        strokeInProgress: () => machine.isActive(),
      }),
      [cancelActiveStroke, machine],
    );

    // A busy/disabled transition mid-gesture cancels it (clearing the preview) so the
    // release can never commit a stroke the workspace would silently refuse.
    useEffect(() => {
      if (props.disabled) {
        handleTouchCancel(machine);
      }
    }, [props.disabled, machine]);

    // Backgrounding the app cancels any in-progress stroke so it cannot commit later.
    useEffect(() => {
      const subscription = AppState.addEventListener('change', (state) => {
        if (state !== 'active') {
          handleTouchCancel(machine);
        }
      });
      return () => subscription.remove();
    }, [machine]);

    const toLogicalPoint = useCallback(
      (x: number, y: number): LogicalPoint | null => toLogical(propsRef.current.getTransform(), x, y),
      [],
    );

    const onTouchStart = useCallback(
      (event: GestureResponderEvent) => {
        if (propsRef.current.disabled) {
          return;
        }
        if (propsRef.current.mode === 'erase') {
          const [first] = toSamples(
            (event.nativeEvent.changedTouches as RawTouch[]) ?? [],
          );
          if (first !== undefined) {
            const point = toLogicalPoint(first.x, first.y);
            if (point !== null) {
              propsRef.current.onTap(point);
            }
          }
          return;
        }
        const samples = toSamples(event.nativeEvent.changedTouches as RawTouch[]).map((t) => {
          const point = toLogicalPoint(t.x, t.y);
          return point === null ? null : { identifier: t.identifier, x: point.x, y: point.y };
        });
        handleTouchStart(machine, samples.filter((s): s is TouchSample => s !== null));
      },
      [machine, toLogicalPoint],
    );

    const onTouchMove = useCallback(
      (event: GestureResponderEvent) => {
        if (propsRef.current.disabled) {
          handleTouchCancel(machine);
          return;
        }
        const samples = toSamples(event.nativeEvent.touches as RawTouch[]).map((t) => {
          const point = toLogicalPoint(t.x, t.y);
          return point === null ? null : { identifier: t.identifier, x: point.x, y: point.y };
        });
        handleTouchMove(machine, samples.filter((s): s is TouchSample => s !== null));
      },
      [machine, toLogicalPoint],
    );

    const onTouchEnd = useCallback(
      (event: GestureResponderEvent) => {
        if (propsRef.current.disabled) {
          handleTouchCancel(machine);
          return;
        }
        const changed = toSamples(event.nativeEvent.changedTouches as RawTouch[]);
        handleTouchEnd(machine, changed);
      },
      [machine],
    );

    const onTouchCancelProp = useCallback(() => {
      handleTouchCancel(machine);
    }, [machine]);

    return (
      <View
        style={props.style}
        onStartShouldSetResponder={() => true}
        onMoveShouldSetResponder={() => true}
        onResponderTerminationRequest={() => false}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onTouchCancel={onTouchCancelProp}
      >
        {props.children}
      </View>
    );
  },
);
