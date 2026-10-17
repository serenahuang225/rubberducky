/**
 * Ties the progressive tutor-mark reveal to the workspace's real lifecycle.
 *
 * A committed turn's marks are withheld only when motion is allowed, the board is in view and
 * the server's cancellation epoch has caught up to the turn that drew them. The run is bound
 * to the session, the workspace turn generation (advanced by Stop and session changes), the
 * server epoch (advanced when pending output is withdrawn) and the current problem. Any change
 * to those, reduced motion, the board being hidden, or unmount cancels the run and shows the
 * final board; the controller's tokens reject callbacks that were already scheduled.
 */

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import type { TutorTurnResult } from "../api/contracts";
import type { MotionMode } from "../feedback/preferences";
import {
  RevealController,
  realTimers,
  type TimerApi,
} from "../board/progressiveReveal";

export type ProgressiveRevealInput = {
  sessionId: string;
  turn: TutorTurnResult | null;
  /** useWorkspace turn generation. */
  generation: number;
  /** The server's current cancellation epoch for this session; null until state is loaded. */
  epoch: number | null;
  attemptId: string | null;
  /** Ids of objects currently in the authoritative scene. */
  presentIds: ReadonlySet<string>;
  motion: MotionMode;
  /** The board is not on screen (settings or memory is open). */
  suspended: boolean;
  timers?: TimerApi;
};

const NONE: ReadonlySet<string> = new Set();

type RevealSnapshot = {
  hidden: ReadonlySet<string>;
  /** The turn whose marks have been started, or given up on; it is never replayed. */
  settledTurnId: string | null;
};

/** External store so lifecycle effects can publish reveal state without setState-in-effect. */
class RevealStore {
  private snapshot: RevealSnapshot = { hidden: NONE, settledTurnId: null };
  private readonly listeners = new Set<() => void>();

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = () => this.snapshot;

  set(patch: Partial<RevealSnapshot>) {
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((listener) => listener());
  }
}

function plannedIds(turn: TutorTurnResult | null, sessionId: string): string[] {
  if (
    turn === null ||
    turn.status !== "committed" ||
    turn.session_id !== sessionId
  )
    return [];
  return turn.drawings.map((drawing) => drawing.object_id);
}

export function useProgressiveReveal({
  sessionId,
  turn,
  generation,
  epoch,
  attemptId,
  presentIds,
  motion,
  suspended,
  timers = realTimers,
}: ProgressiveRevealInput): ReadonlySet<string> {
  const [store] = useState(() => new RevealStore());
  const [controller] = useState(
    () => new RevealController(timers, (next) => store.set({ hidden: next })),
  );
  const { hidden, settledTurnId } = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
  );
  const runScopeRef = useRef<string | null>(null);
  const seenRef = useRef<{
    turnId: string;
    generation: number;
    sessionId: string;
  } | null>(null);

  const ids = useMemo(() => plannedIds(turn, sessionId), [turn, sessionId]);
  const animating = motion === "full" && !suspended;
  const scope = [sessionId, generation, epoch, attemptId].join("|");
  const presentCount = ids.filter((id) => presentIds.has(id)).length;

  useEffect(() => {
    if (runScopeRef.current !== null && runScopeRef.current !== scope) {
      controller.cancel();
      runScopeRef.current = null;
    }
    if (!animating) {
      controller.cancel();
      runScopeRef.current = null;
    }
    if (turn === null || ids.length === 0 || turn.turn_id === settledTurnId)
      return;
    if (seenRef.current?.turnId !== turn.turn_id) {
      seenRef.current = { turnId: turn.turn_id, generation, sessionId };
    }
    const seen = seenRef.current;
    const stale =
      !animating ||
      seen.generation !== generation ||
      seen.sessionId !== sessionId ||
      (epoch !== null && epoch > turn.cancellation_epoch);
    if (stale) {
      store.set({ settledTurnId: turn.turn_id });
      return;
    }
    if (epoch === turn.cancellation_epoch && presentCount > 0) {
      runScopeRef.current = scope;
      store.set({ settledTurnId: turn.turn_id });
      controller.start(ids.filter((id) => presentIds.has(id)));
    }
  }, [
    animating,
    attemptId,
    controller,
    epoch,
    generation,
    ids,
    presentCount,
    presentIds,
    scope,
    sessionId,
    settledTurnId,
    store,
    turn,
  ]);

  useEffect(() => () => controller.cancel(), [controller]);

  const awaitingStart =
    animating &&
    turn !== null &&
    ids.length > 0 &&
    turn.turn_id !== settledTurnId;
  return useMemo(() => {
    if (!awaitingStart) return hidden;
    return new Set([...hidden, ...ids]);
  }, [awaitingStart, hidden, ids]);
}
