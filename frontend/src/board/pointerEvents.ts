/**
 * Pure normalization from web Pointer Event semantics to the shared stroke machine.
 *
 * The DOM wiring lives in the `.web` board layer; everything here takes plain descriptors
 * so the rules are unit-testable without a browser:
 * - only a primary-button (or direct touch/pen contact) press starts a stroke;
 * - hover (no buttons) and secondary buttons never draw;
 * - a second simultaneous pointer cannot splice points into the active stroke;
 * - pointercancel / lostpointercapture / window blur cancel without committing.
 */

import type { LogicalPoint } from './geometry';
import type { StrokeMachine } from './stroke';

export type PointerDescriptor = {
  pointerId: number;
  /** 'mouse' | 'touch' | 'pen' (anything else is treated like pen contact). */
  pointerType: string;
  /** DOM button field on the event: 0 = primary, 1 = middle, 2 = secondary. */
  button: number;
  /** Bitmask of currently pressed buttons; 0 during hover. */
  buttons: number;
  /** false for secondary simultaneous touches (e.g. a palm contact). */
  isPrimary: boolean;
  x: number;
  y: number;
};

export type PointerHandling = 'began' | 'ended' | 'cancelled' | 'moved' | 'ignored';

function pointerKey(pointerId: number): string {
  return `p${pointerId}`;
}

export function handlePointerDown(
  machine: StrokeMachine,
  event: PointerDescriptor,
): PointerHandling {
  // Secondary buttons (right/middle click, pen barrel) never start a stroke.
  if (event.button !== 0) {
    return 'ignored';
  }
  // A non-primary contact is a second finger/palm while one stroke is active, or a stray
  // simultaneous touch; the one-active-pointer rule keeps it out of the stroke.
  if (event.isPrimary === false) {
    return 'ignored';
  }
  return machine.begin(pointerKey(event.pointerId), { x: event.x, y: event.y })
    ? 'began'
    : 'ignored';
}

export function handlePointerMove(
  machine: StrokeMachine,
  event: PointerDescriptor,
): PointerHandling {
  // Hover moves (no active stroke owned by this pointer) do nothing by construction.
  machine.move(pointerKey(event.pointerId), { x: event.x, y: event.y });
  return machine.activePointerId() === pointerKey(event.pointerId) ? 'moved' : 'ignored';
}

export function handlePointerUp(
  machine: StrokeMachine,
  event: PointerDescriptor,
  point?: LogicalPoint | null,
): PointerHandling {
  if (machine.activePointerId() !== pointerKey(event.pointerId)) {
    return 'ignored';
  }
  machine.end(pointerKey(event.pointerId), point);
  return 'ended';
}

export function handlePointerCancel(
  machine: StrokeMachine,
  event: PointerDescriptor,
): PointerHandling {
  if (machine.activePointerId() !== pointerKey(event.pointerId)) {
    return 'ignored';
  }
  machine.cancel();
  return 'cancelled';
}

/** Lost capture, window blur and app backgrounding all discard the active stroke. */
export function handleInterruption(machine: StrokeMachine): PointerHandling {
  if (!machine.isActive()) {
    return 'ignored';
  }
  machine.cancel();
  return 'cancelled';
}
