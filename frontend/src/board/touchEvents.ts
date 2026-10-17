/**
 * Pure normalization from React Native touch event semantics to the shared stroke machine.
 *
 * The native board layer feeds it `touches`/`changedTouches` shaped descriptors, so the
 * one-active-pointer, dot and cancellation rules are unit-testable without a device:
 * the first touch owns the stroke, extra simultaneous touches (palm, second finger) are
 * ignored rather than spliced in, and a cancelled/terminated gesture discards the stroke.
 * This does not claim OS-level palm rejection; it is the app-side single-pointer rule.
 */

import type { StrokeMachine } from './stroke';

export type TouchSample = {
  identifier: string;
  x: number;
  y: number;
};

export type TouchHandling = 'began' | 'ended' | 'cancelled' | 'moved' | 'ignored';

export function handleTouchStart(
  machine: StrokeMachine,
  changedTouches: readonly TouchSample[],
): TouchHandling {
  const first = changedTouches[0];
  if (first === undefined) {
    return 'ignored';
  }
  return machine.begin(first.identifier, { x: first.x, y: first.y }) ? 'began' : 'ignored';
}

export function handleTouchMove(
  machine: StrokeMachine,
  activeTouches: readonly TouchSample[],
): TouchHandling {
  const owner = machine.activePointerId();
  if (owner === null) {
    return 'ignored';
  }
  const sample = activeTouches.find((touch) => touch.identifier === owner);
  if (sample === undefined) {
    return 'ignored';
  }
  machine.move(owner, { x: sample.x, y: sample.y });
  return 'moved';
}

export function handleTouchEnd(
  machine: StrokeMachine,
  changedTouches: readonly TouchSample[],
): TouchHandling {
  const owner = machine.activePointerId();
  if (owner === null) {
    return 'ignored';
  }
  if (!changedTouches.some((touch) => touch.identifier === owner)) {
    return 'ignored';
  }
  machine.end(owner);
  return 'ended';
}

export function handleTouchCancel(machine: StrokeMachine): TouchHandling {
  if (!machine.isActive()) {
    return 'ignored';
  }
  machine.cancel();
  return 'cancelled';
}
