/**
 * Web board input layer: real Pointer Events on the board element only.
 *
 * This is the only DOM-touching part of the board. It captures the pointer on the board
 * (so a stroke continues cleanly to its end), sets `touch-action: none` on the board
 * alone (page scrolling outside the board keeps working), and cancels on pointercancel,
 * lost capture, window blur and tab backgrounding. All decisions go through the shared
 * pure normalizers in `board/pointerEvents`.
 */

import React, { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import { View, type ViewStyle } from 'react-native';

import type { LogicalPoint } from '../board/geometry';
import { toLogical } from '../board/geometry';
import {
  handleInterruption,
  handlePointerCancel,
  handlePointerDown,
  handlePointerMove,
  handlePointerUp,
} from '../board/pointerEvents';
import { StrokeMachine } from '../board/stroke';

import type { BoardInputHandle, BoardInputLayerProps } from './BoardInputLayer';

export type { BoardInputHandle, BoardInputLayerProps };

export const BoardInputLayer = forwardRef<BoardInputHandle, BoardInputLayerProps>(
  function BoardInputLayer(props, ref) {
    const propsRef = useRef(props);
    propsRef.current = props;
    const hostRef = useRef<View | null>(null);

    const machine = useMemo(
      () =>
        new StrokeMachine({
          onPreview: (points) => propsRef.current.onPreview(points),
          onCommit: (points) => propsRef.current.onStroke(points),
          onCancel: () => propsRef.current.onStrokeCancel(),
        }),
      [],
    );

    useImperativeHandle(
      ref,
      () => ({
        cancelActiveStroke: () => handleInterruption(machine),
        strokeInProgress: () => machine.isActive(),
      }),
      [machine],
    );

    useEffect(() => {
      const node = hostRef.current as unknown as HTMLElement | null;
      if (node === null || typeof node.addEventListener !== 'function') {
        return;
      }
      // Board-only scroll suppression and no text selection while drawing.
      node.style.touchAction = 'none';
      node.style.userSelect = 'none';
      (node.style as CSSStyleDeclaration & { webkitUserSelect?: string }).webkitUserSelect =
        'none';

      // Board-local pixels; the rect is read per event so the board can sit anywhere.
      const localPoint = (event: PointerEvent): { x: number; y: number } => {
        const rect = node.getBoundingClientRect();
        return { x: event.clientX - rect.left, y: event.clientY - rect.top };
      };
      const descriptor = (event: PointerEvent) => {
        const point = localPoint(event);
        return {
          pointerId: event.pointerId,
          pointerType: event.pointerType,
          button: event.button,
          buttons: event.buttons,
          isPrimary: event.isPrimary,
          x: point.x,
          y: point.y,
        };
      };
      const logical = (event: PointerEvent): LogicalPoint | null => {
        const point = localPoint(event);
        return toLogical(propsRef.current.getTransform(), point.x, point.y);
      };

      const onPointerDown = (event: PointerEvent) => {
        const current = propsRef.current;
        if (current.disabled) {
          return;
        }
        if (current.mode === 'erase') {
          if (event.button === 0 && event.isPrimary) {
            const point = logical(event);
            if (point !== null) {
              current.onTap(point);
            }
          }
          return;
        }
        const point = logical(event);
        if (point === null) {
          return;
        }
        const result = handlePointerDown(machine, { ...descriptor(event), x: point.x, y: point.y });
        if (result === 'began') {
          // Keep the stroke's events flowing to the board even off its edge.
          try {
            node.setPointerCapture(event.pointerId);
          } catch {
            // A detached or synthetic pointer cannot be captured; the stroke still works.
          }
          event.preventDefault();
        }
      };
      const onPointerMove = (event: PointerEvent) => {
        if (propsRef.current.disabled) {
          return;
        }
        if (propsRef.current.mode === 'erase') {
          return;
        }
        const point = logical(event);
        if (point !== null) {
          handlePointerMove(machine, { ...descriptor(event), x: point.x, y: point.y });
        }
      };
      const onPointerUp = (event: PointerEvent) => {
        if (propsRef.current.mode === 'erase') {
          return;
        }
        handlePointerUp(machine, descriptor(event));
      };
      const onPointerCancel = (event: PointerEvent) => {
        handlePointerCancel(machine, descriptor(event));
      };
      const onLostCapture = (event: PointerEvent) => {
        handlePointerCancel(machine, descriptor(event));
      };
      const onInterrupt = () => {
        handleInterruption(machine);
      };
      const onVisibility = () => {
        if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
          handleInterruption(machine);
        }
      };
      const onContextMenu = (event: MouseEvent) => {
        // A right-click on the board is never a drawing gesture or a menu.
        event.preventDefault();
      };

      node.addEventListener('pointerdown', onPointerDown);
      node.addEventListener('pointermove', onPointerMove);
      node.addEventListener('pointerup', onPointerUp);
      node.addEventListener('pointercancel', onPointerCancel);
      node.addEventListener('lostpointercapture', onLostCapture);
      node.addEventListener('contextmenu', onContextMenu);
      if (typeof window !== 'undefined') {
        window.addEventListener('blur', onInterrupt);
      }
      if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', onVisibility);
      }
      return () => {
        node.removeEventListener('pointerdown', onPointerDown);
        node.removeEventListener('pointermove', onPointerMove);
        node.removeEventListener('pointerup', onPointerUp);
        node.removeEventListener('pointercancel', onPointerCancel);
        node.removeEventListener('lostpointercapture', onLostCapture);
        node.removeEventListener('contextmenu', onContextMenu);
        if (typeof window !== 'undefined') {
          window.removeEventListener('blur', onInterrupt);
        }
        if (typeof document !== 'undefined') {
          document.removeEventListener('visibilitychange', onVisibility);
        }
        handleInterruption(machine);
      };
    }, [machine]);

    return (
      <View ref={hostRef} style={props.style as ViewStyle} collapsable={false}>
        {props.children}
      </View>
    );
  },
);
