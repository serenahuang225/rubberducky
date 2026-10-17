/**
 * Workspace controller: owns the session, scene snapshot, tutor conversation state and
 * the durable save pipeline for the whiteboard screen.
 *
 * Durability contract:
 * - Every committed change is re-fetched from the server and mirrored into the durable
 *   scene cache, so reload/re-entry paints the last committed scene immediately and then
 *   replaces it with authoritative state.
 * - A finished stroke that cannot reach the server is queued in the durable outbox under
 *   its original operation id, stays visible as an honest "not saved yet" mark, and is
 *   retried with that SAME id on reconnect — the server's idempotent commit makes the
 *   retry land exactly once.
 * - If the outbox itself is unavailable (storage error), the finished stroke is held in
 *   memory for this session only: still visible as unsaved, retried with its original
 *   operation id, and described honestly as NOT kept on the device.
 * - History edits (erase/undo/redo/tutor-move undo) depend on current server state, so
 *   they are never queued: without a connection they are refused honestly instead.
 * - A server rejection surfaces the server's own message; nothing is retried blindly.
 * - Help me is one logical command with one stable idempotency key and body. An uncertain
 *   transport failure keeps that command so the next press retries it unchanged; a definite
 *   revision conflict resyncs first and never carries a stale intent onto a new problem.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { LogicalPoint } from '../board/geometry';
import { ApiClient, ApiClientError, type SceneActionRequest } from '../api/client';
import type { SceneSnapshot, SessionState, TutorTurnResult } from '../api/contracts';
import { newId } from '../api/ids';
import { commitWithResync, makeSceneSync } from '../api/sceneSync';
import {
  enqueueOperation,
  loadPendingOperations,
  removeOperation,
  type PendingSceneOperation,
} from '../storage/outbox';
import { loadCachedScene, saveCachedScene } from '../storage/sceneCache';

export type WorkspacePhase = 'loading' | 'ready' | 'failed';

/** A stroke that is drawn but not yet durably saved. */
export type PendingStrokePreview = {
  id: string;
  points: readonly LogicalPoint[];
};

export type WorkspaceController = {
  phase: WorkspacePhase;
  state: SessionState | null;
  scene: SceneSnapshot | null;
  /** Latest committed tutor utterance for the prompt bar. */
  lastUtterance: string | null;
  lastExpectedAction: string | null;
  /** The latest committed turn, for concise representation/disclosure/diagnostic context. */
  lastTurn: TutorTurnResult | null;
  /** The tutor provider's own label, e.g. the honest mock label; null until known. */
  providerLabel: string | null;
  providerIsMock: boolean;
  /** Truthful short status for the prompt bar. */
  busyLabel: string | null;
  errorMessage: string | null;
  /** Finished strokes held in the durable outbox, shown as visibly unsaved. */
  pendingStrokes: readonly PendingStrokePreview[];
  /** Number of changes not yet saved to the server. */
  pendingCount: number;
  /** Subset of pendingCount held only in memory because device storage failed. */
  memoryOnlyCount: number;
  needsCheckIn: boolean;
  retry: () => void;
  /** Retry saving queued changes now (also happens automatically after any success). */
  retryPending: () => Promise<void>;
  checkIn: (energy: 'ready' | 'a_bit_tired' | 'tired') => Promise<void>;
  submitWork: (text: string) => Promise<void>;
  /** Help me: asks /help for a hint right now, without waiting for any timer. */
  requestHelp: () => Promise<void>;
  commitStroke: (points: readonly LogicalPoint[]) => Promise<void>;
  eraseObject: (objectId: string) => Promise<void>;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
  undoTutorMove: () => Promise<void>;
};

/** True when the request never reached a decided server response (offline/down/timeout). */
function isNetworkFailure(error: unknown): boolean {
  if (error instanceof ApiClientError) {
    return false;
  }
  return error instanceof Error && (error.name === 'AbortError' || error instanceof TypeError);
}

/** One logical Help me command: the key and body stay fixed until a definite outcome. */
type PendingHelp = { key: string; expectedRevision: number; attemptId: string | null };

const HELP_UNCERTAIN_MESSAGE =
  'The tutor may not have received that. Press Help me again; it will not be counted twice.';
const HELP_STALE_MESSAGE =
  'The problem changed while that was sending, so Help me was not applied. Press Help me again if you still want a hint.';

const MEMORY_ONLY_MESSAGE =
  'Your last stroke is not saved to the tutor and could not be kept on this device. It stays on the board only in memory while this screen is open. Tap Retry now once the tutor is reachable.';

/** Durable entries plus session-memory entries, oldest first, without duplicate ids. */
function mergeQueues(
  durable: readonly PendingSceneOperation[],
  memory: readonly PendingSceneOperation[],
): PendingSceneOperation[] {
  const known = new Set(durable.map((entry) => entry.operationId));
  const merged = [...durable, ...memory.filter((entry) => !known.has(entry.operationId))];
  return merged.sort((a, b) => (a.queuedAt < b.queuedAt ? -1 : a.queuedAt > b.queuedAt ? 1 : 0));
}

function previewsFromQueue(queue: readonly PendingSceneOperation[]): PendingStrokePreview[] {
  const previews: PendingStrokePreview[] = [];
  for (const entry of queue) {
    if (entry.action.op === 'add_stroke') {
      previews.push({ id: entry.operationId, points: entry.action.points });
    }
  }
  return previews;
}

export function useWorkspace(client: ApiClient, sessionId: string): WorkspaceController {
  const [phase, setPhase] = useState<WorkspacePhase>('loading');
  const [state, setState] = useState<SessionState | null>(null);
  const [scene, setScene] = useState<SceneSnapshot | null>(null);
  const [pendingOps, setPendingOpsState] = useState<readonly PendingSceneOperation[]>([]);
  const [memoryOps, setMemoryOpsState] = useState<readonly PendingSceneOperation[]>([]);
  // Tagged with its session so a session change shows nothing from the previous one.
  const [committed, setCommitted] = useState<{ sessionId: string; turn: TutorTurnResult } | null>(
    null,
  );
  const [providerLabel, setProviderLabel] = useState<string | null>(null);
  const [providerIsMock, setProviderIsMock] = useState(false);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const busyRef = useRef(false);
  const sceneRef = useRef<SceneSnapshot | null>(null);
  const flushingRef = useRef(false);
  const pendingOpsRef = useRef<readonly PendingSceneOperation[]>([]);
  const memoryOpsRef = useRef<readonly PendingSceneOperation[]>([]);
  const epochRef = useRef(0);
  const pendingHelpRef = useRef<PendingHelp | null>(null);

  const setPendingOps = useCallback((next: readonly PendingSceneOperation[]) => {
    pendingOpsRef.current = next;
    setPendingOpsState(next);
  }, []);
  const setMemoryOps = useCallback((next: readonly PendingSceneOperation[]) => {
    memoryOpsRef.current = next;
    setMemoryOpsState(next);
  }, []);

  const sync = useMemo(() => makeSceneSync(client, sessionId), [client, sessionId]);

  useEffect(() => {
    sceneRef.current = scene;
  }, [scene]);

  // A new session invalidates the pending help command and any in-flight help response.
  useEffect(() => {
    epochRef.current += 1;
    pendingHelpRef.current = null;
    return () => {
      epochRef.current += 1;
    };
  }, [client, sessionId]);

  const refresh = useCallback(async (): Promise<SessionState> => {
    const epoch = epochRef.current;
    const [nextState, nextScene] = await Promise.all([
      client.sessionState(sessionId),
      client.sceneSnapshot(sessionId),
    ]);
    if (epoch === epochRef.current) {
      setState(nextState);
      setScene(nextScene);
      // Mirror the committed server truth; never cache optimistic local guesses.
      await saveCachedScene(nextScene).catch(() => undefined);
    }
    return nextState;
  }, [client, sessionId]);

  const guardBusy = useCallback((label: string): boolean => {
    if (busyRef.current) {
      return false;
    }
    busyRef.current = true;
    setBusyLabel(label);
    setErrorMessage(null);
    return true;
  }, []);

  const releaseBusy = useCallback((): void => {
    busyRef.current = false;
    setBusyLabel(null);
  }, []);

  /**
   * Save every queued change with its original operation id, oldest first. Stops at the
   * first network failure (the rest stay queued and visibly unsaved). Returns true when
   * the queue is empty afterwards.
   */
  const flushPending = useCallback(async (): Promise<boolean> => {
    if (flushingRef.current) {
      return false;
    }
    flushingRef.current = true;
    try {
      // An unreadable outbox must not hide ink: fall back to what this session knows.
      const durable = await loadPendingOperations(sessionId).catch(() => pendingOpsRef.current);
      const queued = mergeQueues(durable, memoryOpsRef.current);
      if (queued.length === 0) {
        setPendingOps([]);
        return true;
      }
      for (const entry of queued) {
        const currentRevision = sceneRef.current?.scene_revision ?? 0;
        try {
          // SAME operation id: a retried-but-already-saved op replays, never duplicates.
          const outcome = await commitWithResync(sync, entry.operationId, currentRevision, entry.action);
          // Publish the authoritative snapshot BEFORE the pending preview goes away, so the
          // accepted stroke moves from preview to scene object without a gap.
          sceneRef.current = outcome.scene;
          setScene(outcome.scene);
          await saveCachedScene(outcome.scene).catch(() => undefined);
        } catch (error) {
          if (isNetworkFailure(error)) {
            return false;
          }
          // A real rejection (conflict/validation) cannot be repaired by retrying; drop
          // it from the queue so one bad entry cannot block the rest forever, and say so.
          setErrorMessage(
            'One unsaved change could not be accepted and was set aside. The rest of your work is unaffected.',
          );
        }
        setMemoryOps(memoryOpsRef.current.filter((op) => op.operationId !== entry.operationId));
        // Drop the preview locally first; a failed durable removal only leaves an
        // idempotent replay for the next flush.
        setPendingOps(pendingOpsRef.current.filter((op) => op.operationId !== entry.operationId));
        await removeOperation(sessionId, entry.operationId).catch(() => undefined);
      }
      return true;
    } finally {
      flushingRef.current = false;
    }
  }, [sessionId, setMemoryOps, setPendingOps, sync]);

  const retryPending = useCallback(async () => {
    if (!guardBusy('Saving…')) {
      return;
    }
    try {
      const drained = await flushPending();
      if (drained) {
        await refresh();
      }
    } catch {
      // The queue is still honest; the notice stays until the next successful save.
    } finally {
      releaseBusy();
    }
  }, [flushPending, guardBusy, refresh, releaseBusy]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      setPhase('loading');
      setErrorMessage(null);
      // Paint the last committed scene from the durable cache while the server answers.
      const [cached, queued] = await Promise.all([
        loadCachedScene(sessionId).catch(() => null),
        loadPendingOperations(sessionId).catch(() => []),
      ]);
      if (!active) return;
      if (cached !== null) {
        setScene(cached);
      }
      setPendingOps(queued);
      try {
        await refresh();
        if (active) {
          setPhase('ready');
        }
        // The provider's own identity label (e.g. the honest mock label) rides along so
        // the workspace can show it from the start, before any turn has run.
        await client
          .modelReadiness()
          .then((readiness) => {
            if (active) {
              setProviderLabel(readiness.label);
              setProviderIsMock(readiness.is_mock);
            }
          })
          .catch(() => undefined);
        // Reconnected (or never disconnected): finish anything the outbox still holds.
        const drained = await flushPending();
        if (active && drained) {
          await refresh().catch(() => undefined);
        }
      } catch (error) {
        if (active) {
          setPhase('failed');
          setErrorMessage(
            error instanceof Error ? error.message : 'The workspace could not load.',
          );
        }
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [refresh, attempt, sessionId, flushPending, client, setPendingOps]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  /** Shows a turn's provider and, when committed, its tutor words and teaching context. */
  const applyTurnResult = useCallback(
    (result: TutorTurnResult) => {
    setProviderLabel(result.provider.label);
    setProviderIsMock(result.provider.is_mock);
    if (result.status === 'committed') {
      setCommitted({ sessionId, turn: result });
    } else if (result.status === 'rejected') {
      setErrorMessage('The tutor could not use that turn; your work is unchanged.');
    } else {
      setErrorMessage('The tutor turn did not complete; your work is unchanged.');
    }
    },
    [sessionId],
  );

  const runTurn = useCallback(
    async (label: string, action: () => Promise<TutorTurnResult>) => {
      if (!guardBusy(label)) return;
      try {
        const result = await action();
        applyTurnResult(result);
        await refresh();
        await flushPending();
      } catch (error) {
        if (error instanceof ApiClientError && error.code === 'revision_conflict') {
          try {
            const result = await action();
            applyTurnResult(result);
            await refresh();
          } catch (second) {
            setErrorMessage(
              second instanceof Error ? second.message : 'The tutor turn failed to send.',
            );
            await refresh().catch(() => undefined);
          }
        } else if (isNetworkFailure(error)) {
          setErrorMessage(
            memoryOpsRef.current.length > 0
              ? 'The tutor is not reachable right now. Some of your board work is held only in memory, not on this device.'
              : 'The tutor is not reachable right now. Your board work is kept on this device.',
          );
        } else {
          setErrorMessage(
            error instanceof Error ? error.message : 'The tutor turn failed to send.',
          );
          await refresh().catch(() => undefined);
        }
      } finally {
        releaseBusy();
      }
    },
    [applyTurnResult, flushPending, guardBusy, refresh, releaseBusy],
  );

  const checkIn = useCallback(
    async (energy: 'ready' | 'a_bit_tired' | 'tired') => {
      const current = state;
      if (current === null) return;
      await runTurn('Starting…', () =>
        client.checkIn(sessionId, newId(), current.session.revision, energy),
      );
    },
    [client, runTurn, sessionId, state],
  );

  const submitWork = useCallback(
    async (text: string) => {
      const current = state;
      if (current === null) return;
      const trimmed = text.trim();
      if (trimmed.length === 0) return;
      await runTurn('Thinking…', () =>
        client.submitWork(sessionId, newId(), current.session.revision, trimmed, 'typed'),
      );
    },
    [client, runTurn, sessionId, state],
  );

  const requestHelp = useCallback(async () => {
    const current = state;
    if (current === null || current.current_problem === null) return;
    if (!guardBusy('Thinking…')) return;
    const epoch = epochRef.current;
    const attemptId = current.current_problem.attempt_id;
    let command = pendingHelpRef.current;
    if (command === null || command.attemptId !== attemptId) {
      command = { key: newId(), expectedRevision: current.session.revision, attemptId };
      pendingHelpRef.current = command;
    }
    try {
      let result: TutorTurnResult;
      try {
        result = await client.requestHelp(sessionId, command.key, command.expectedRevision, 'hint');
      } catch (error) {
        if (!(error instanceof ApiClientError && error.code === 'revision_conflict')) {
          throw error;
        }
        // A definite conflict applied nothing. Resync, and only re-ask for the problem the
        // learner was actually looking at; a new problem never inherits the old intent.
        pendingHelpRef.current = null;
        const fresh = await refresh();
        if (epoch !== epochRef.current) return;
        if ((fresh.current_problem?.attempt_id ?? null) !== attemptId) {
          setErrorMessage(HELP_STALE_MESSAGE);
          return;
        }
        command = { key: newId(), expectedRevision: fresh.session.revision, attemptId };
        pendingHelpRef.current = command;
        result = await client.requestHelp(sessionId, command.key, command.expectedRevision, 'hint');
      }
      if (epoch !== epochRef.current) return;
      if (result.status !== 'pending') {
        pendingHelpRef.current = null;
      }
      applyTurnResult(result);
      await refresh();
      await flushPending();
    } catch (error) {
      if (epoch !== epochRef.current) return;
      if (isNetworkFailure(error)) {
        // Keep the command: the next press retries the same key and body, never a duplicate.
        setErrorMessage(
          memoryOpsRef.current.length > 0
            ? `${HELP_UNCERTAIN_MESSAGE} Some of your board work is held only in memory, not on this device.`
            : HELP_UNCERTAIN_MESSAGE,
        );
      } else {
        pendingHelpRef.current = null;
        setErrorMessage(error instanceof Error ? error.message : 'Help me could not be sent.');
        await refresh().catch(() => undefined);
      }
    } finally {
      releaseBusy();
    }
  }, [applyTurnResult, client, flushPending, guardBusy, refresh, releaseBusy, sessionId, state]);

  const commitSceneAction = useCallback(
    async (action: SceneActionRequest, label: string) => {
      const current = sceneRef.current;
      if (current === null || !guardBusy(label)) return;
      const operationId = newId();
      try {
        const outcome = await commitWithResync(sync, operationId, current.scene_revision, action);
        setScene(outcome.scene);
        await saveCachedScene(outcome.scene).catch(() => undefined);
        // A successful save proves connectivity: finish anything still queued.
        const drained = await flushPending();
        if (drained) {
          await refresh().catch(() => undefined);
        }
      } catch (error) {
        if (isNetworkFailure(error)) {
          if (action.op === 'add_stroke') {
            // Keep the finished stroke on-device, visibly unsaved, for exactly-once retry.
            const entry: PendingSceneOperation = {
              operationId,
              sessionId,
              queuedAt: new Date().toISOString(),
              action,
            };
            try {
              setPendingOps(await enqueueOperation(entry));
            } catch {
              // Device storage failed too: keep the ink visible and retryable from memory
              // for this session, and say plainly that it is not durable.
              setMemoryOps([...memoryOpsRef.current, entry]);
              setErrorMessage(MEMORY_ONLY_MESSAGE);
            }
          } else {
            // History edits depend on current server state; refuse rather than guess.
            setErrorMessage(
              'That change needs a connection to the tutor. Nothing was changed — try again when it is back.',
            );
          }
        } else {
          // The server answered and refused: show its reason, resync to real state.
          setErrorMessage(
            error instanceof Error
              ? `The tutor could not save that: ${error.message}`
              : 'That change could not be saved.',
          );
          await refresh().catch(() => undefined);
        }
      } finally {
        releaseBusy();
      }
    },
    [flushPending, guardBusy, refresh, releaseBusy, sessionId, setMemoryOps, setPendingOps, sync],
  );

  const commitStroke = useCallback(
    async (points: readonly LogicalPoint[]) => {
      if (points.length === 0) return;
      await commitSceneAction(
        { op: 'add_stroke', points: points.map((p) => ({ x: p.x, y: p.y })) },
        'Saving…',
      );
    },
    [commitSceneAction],
  );

  const eraseObject = useCallback(
    (objectId: string) =>
      commitSceneAction({ op: 'erase_object', target_object_id: objectId }, 'Erasing…'),
    [commitSceneAction],
  );
  const undo = useCallback(
    () => commitSceneAction({ op: 'undo' }, 'Undoing…'),
    [commitSceneAction],
  );
  const redo = useCallback(
    () => commitSceneAction({ op: 'redo' }, 'Redoing…'),
    [commitSceneAction],
  );
  const undoTutorMove = useCallback(
    () => commitSceneAction({ op: 'undo_tutor_move' }, 'Removing tutor marks…'),
    [commitSceneAction],
  );

  const lastTurn = committed !== null && committed.sessionId === sessionId ? committed.turn : null;
  const needsCheckIn = state !== null && state.current_problem === null;
  const unsavedOps = useMemo(() => mergeQueues(pendingOps, memoryOps), [pendingOps, memoryOps]);
  const pendingStrokes = useMemo(() => previewsFromQueue(unsavedOps), [unsavedOps]);

  return {
    phase,
    state,
    scene,
    lastUtterance: lastTurn?.utterance ?? null,
    lastExpectedAction: lastTurn?.expected_student_action ?? null,
    lastTurn,
    providerLabel,
    providerIsMock,
    busyLabel,
    errorMessage,
    pendingStrokes,
    pendingCount: unsavedOps.length,
    memoryOnlyCount: memoryOps.filter(
      (op) => !pendingOps.some((durable) => durable.operationId === op.operationId),
    ).length,
    needsCheckIn,
    retry,
    retryPending,
    checkIn,
    submitWork,
    requestHelp,
    commitStroke,
    eraseObject,
    undo,
    redo,
    undoTutorMove,
  };
}
