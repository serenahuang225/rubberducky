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
 * - Stop reply withdraws the tutor reply being prepared on the server (a retry-safe interrupt)
 *   and invalidates this client's turn generation, so a late response, speech or drawing
 *   callback of the stopped turn is ignored instead of painting over the current board.
 * - Help me and typed work are each one logical command with one stable idempotency key and
 *   body. An uncertain transport failure keeps that command so the next send retries it
 *   unchanged; a definite revision conflict resyncs first and never carries a stale intent
 *   onto a new problem or session. submitWork reports whether the server gave an
 *   authoritative outcome, so the screen clears the learner's text only then.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from "react";

import type { LogicalPoint } from "../board/geometry";
import {
  ApiClient,
  ApiClientError,
  type SceneActionRequest,
} from "../api/client";
import type {
  SceneSnapshot,
  SessionState,
  TutorTurnResult,
} from "../api/contracts";
import { newId } from "../api/ids";
import { commitWithResync, makeSceneSync } from "../api/sceneSync";
import {
  enqueueOperation,
  loadPendingOperations,
  removeOperation,
  type PendingSceneOperation,
} from "../storage/outbox";
import { loadCachedScene, saveCachedScene } from "../storage/sceneCache";

import { noticeForTurn } from "./turnNotices";

export type WorkspacePhase = "loading" | "ready" | "failed";

export type WorkSubmitOutcome = "resolved" | "retained" | "stale" | "ignored";

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
  /**
   * When true the board ignores new ink. Stroke saves leave this false so the pen
   * stays live while a mark is still reaching the tutor.
   */
  penLocked: boolean;
  /** Finished strokes painted immediately, before the server snapshot replaces them. */
  settlingStrokes: readonly PendingStrokePreview[];
  errorMessage: string | null;
  /** Finished strokes held in the durable outbox, shown as visibly unsaved. */
  pendingStrokes: readonly PendingStrokePreview[];
  /** Number of changes not yet saved to the server. */
  pendingCount: number;
  /** Subset of pendingCount held only in memory because device storage failed. */
  memoryOnlyCount: number;
  needsCheckIn: boolean;
  /** A tutor reply is being prepared and can be stopped. */
  canInterrupt: boolean;
  /**
   * Advances whenever the learner stops a reply or the session/client changes. Anything
   * scheduled against an older generation (for example progressive drawing) must not run.
   */
  turnGeneration: number;
  /** The last request never reached the tutor service (offline, down or timed out). */
  connectionLost: boolean;
  /** The last command was definitively rejected or failed; cleared when the next one starts. */
  commandFailed: boolean;
  /** Stop the reply being prepared; the learner's own work is untouched. */
  interrupt: () => Promise<void>;
  retry: () => void;
  /** Retry saving queued changes now (also happens automatically after any success). */
  retryPending: () => Promise<void>;
  checkIn: (energy: "ready" | "a_bit_tired" | "tired") => Promise<void>;
  /**
   * Send typed work. 'resolved': the server recorded it (committed or not), so the caller may
   * clear exactly that text. 'retained': nothing authoritative came back; keep the text.
   * 'stale': the problem or session changed, nothing was sent for the old one. 'ignored':
   * another command was running.
   */
  submitWork: (text: string) => Promise<WorkSubmitOutcome>;
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
  return (
    error instanceof Error &&
    (error.name === "AbortError" || error instanceof TypeError)
  );
}

/**
 * One logical command (Help me or typed work): the key and body stay fixed until a definite
 * outcome. The fingerprint identifies the learner's content, so edited text never reuses
 * the key of an earlier body.
 */
type LogicalCommand = {
  key: string;
  expectedRevision: number;
  attemptId: string | null;
  fingerprint: string;
};

type LogicalSpec = {
  label: string;
  command: MutableRefObject<LogicalCommand | null>;
  fingerprint: string;
  /** Typed work belongs to the problem it was written for; Help is re-asked for the current one. */
  fenceProblem: boolean;
  send: (key: string, expectedRevision: number) => Promise<TutorTurnResult>;
  uncertainMessage: string;
  staleMessage: string;
  failureMessage: string;
};

const WORK_UNCERTAIN_MESSAGE =
  "The tutor may not have received that. Your step is kept; press Submit again and it will not be counted twice.";
const WORK_STALE_MESSAGE =
  "The problem changed while that was sending, so your step was not sent. Check it and press Submit again if you still want to send it.";

const HELP_UNCERTAIN_MESSAGE =
  "The tutor may not have received that. Press Help me again; it will not be counted twice.";
const HELP_STALE_MESSAGE =
  "The problem changed while that was sending, so Help me was not applied. Press Help me again if you still want a hint.";

const MEMORY_ONLY_MESSAGE =
  "Your last stroke is not saved to the tutor and could not be kept on this device. It stays on the board only in memory while this screen is open. Tap Retry now once the tutor is reachable.";

/** Durable entries plus session-memory entries, oldest first, without duplicate ids. */
function mergeQueues(
  durable: readonly PendingSceneOperation[],
  memory: readonly PendingSceneOperation[],
): PendingSceneOperation[] {
  const known = new Set(durable.map((entry) => entry.operationId));
  const merged = [
    ...durable,
    ...memory.filter((entry) => !known.has(entry.operationId)),
  ];
  return merged.sort((a, b) =>
    a.queuedAt < b.queuedAt ? -1 : a.queuedAt > b.queuedAt ? 1 : 0,
  );
}

function previewsFromQueue(
  queue: readonly PendingSceneOperation[],
): PendingStrokePreview[] {
  const previews: PendingStrokePreview[] = [];
  for (const entry of queue) {
    if (entry.action.op === "add_stroke") {
      previews.push({ id: entry.operationId, points: entry.action.points });
    }
  }
  return previews;
}

export function useWorkspace(
  client: ApiClient,
  sessionId: string,
): WorkspaceController {
  const [phase, setPhase] = useState<WorkspacePhase>("loading");
  const [state, setState] = useState<SessionState | null>(null);
  const [scene, setScene] = useState<SceneSnapshot | null>(null);
  const [pendingOps, setPendingOpsState] = useState<
    readonly PendingSceneOperation[]
  >([]);
  const [memoryOps, setMemoryOpsState] = useState<
    readonly PendingSceneOperation[]
  >([]);
  // Tagged with its session so a session change shows nothing from the previous one.
  const [committed, setCommitted] = useState<{
    sessionId: string;
    turn: TutorTurnResult;
  } | null>(null);
  const [providerLabel, setProviderLabel] = useState<string | null>(null);
  const [providerIsMock, setProviderIsMock] = useState(false);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [penLocked, setPenLocked] = useState(false);
  const [settlingStrokes, setSettlingStrokes] = useState<
    readonly PendingStrokePreview[]
  >([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const busyRef = useRef(false);
  const strokeQueueRef = useRef(Promise.resolve());
  const sceneRef = useRef<SceneSnapshot | null>(null);
  const flushingRef = useRef(false);
  const pendingOpsRef = useRef<readonly PendingSceneOperation[]>([]);
  const memoryOpsRef = useRef<readonly PendingSceneOperation[]>([]);
  const epochRef = useRef(0);
  // Advances when the learner stops a reply; anything started earlier is stale and ignored.
  const turnGenRef = useRef(0);
  const [turnInFlight, setTurnInFlight] = useState(false);
  const [turnGeneration, setTurnGeneration] = useState(0);
  const [connectionLost, setConnectionLost] = useState(false);
  const [commandFailed, setCommandFailed] = useState(false);
  // The command lock belongs to one session: when the session changes, release it in render
  // (React's sanctioned reset-on-prop-change) so the old session's request cannot strand it.
  const [lockSession, setLockSession] = useState(sessionId);
  if (lockSession !== sessionId) {
    setLockSession(sessionId);
    setBusyLabel(null);
    setTurnInFlight(false);
  }
  const pendingHelpRef = useRef<LogicalCommand | null>(null);
  const pendingWorkRef = useRef<LogicalCommand | null>(null);
  // Commands waiting on the server; a successful Stop settles them without waiting for the
  // withdrawn request, which only returns once the provider finishes.
  const stopWaitersRef = useRef<Set<() => void>>(new Set());

  const setPendingOps = useCallback(
    (next: readonly PendingSceneOperation[]) => {
      pendingOpsRef.current = next;
      setPendingOpsState(next);
    },
    [],
  );
  const setMemoryOps = useCallback((next: readonly PendingSceneOperation[]) => {
    memoryOpsRef.current = next;
    setMemoryOpsState(next);
  }, []);

  const sync = useMemo(
    () => makeSceneSync(client, sessionId),
    [client, sessionId],
  );

  useEffect(() => {
    sceneRef.current = scene;
  }, [scene]);

  // A new session invalidates pending commands and any in-flight response; the lock they held
  // belongs to the old session and must not strand the new one.
  useEffect(() => {
    epochRef.current += 1;
    turnGenRef.current += 1;
    setTurnGeneration(turnGenRef.current);
    pendingHelpRef.current = null;
    pendingWorkRef.current = null;
    busyRef.current = false;
    setPenLocked(false);
    setSettlingStrokes([]);
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
      setConnectionLost(false);
      setState(nextState);
      setScene(nextScene);
      // Mirror the committed server truth; never cache optimistic local guesses.
      await saveCachedScene(nextScene).catch(() => undefined);
    }
    return nextState;
  }, [client, sessionId]);

  const guardBusy = useCallback((label: string | null, lockPen = true): boolean => {
    if (busyRef.current) {
      return false;
    }
    busyRef.current = true;
    // A null label keeps the lock without changing the prompt. Stroke saves use that
    // so "Saving…" cannot resize the board underneath the pen.
    if (label !== null) {
      setBusyLabel(label);
    }
    setPenLocked(lockPen);
    setErrorMessage(null);
    setCommandFailed(false);
    return true;
  }, []);

  const releaseBusy = useCallback((): void => {
    busyRef.current = false;
    setBusyLabel(null);
    setPenLocked(false);
  }, []);

  const clearSettling = useCallback((operationId: string) => {
    setSettlingStrokes((current) =>
      current.filter((stroke) => stroke.id !== operationId),
    );
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
      const durable = await loadPendingOperations(sessionId).catch(
        () => pendingOpsRef.current,
      );
      const queued = mergeQueues(durable, memoryOpsRef.current);
      if (queued.length === 0) {
        setPendingOps([]);
        return true;
      }
      for (const entry of queued) {
        const currentRevision = sceneRef.current?.scene_revision ?? 0;
        try {
          // SAME operation id: a retried-but-already-saved op replays, never duplicates.
          const outcome = await commitWithResync(
            sync,
            entry.operationId,
            currentRevision,
            entry.action,
          );
          // Publish the authoritative snapshot BEFORE the pending preview goes away, so the
          // accepted stroke moves from preview to scene object without a gap.
          sceneRef.current = outcome.scene;
          setScene(outcome.scene);
          await saveCachedScene(outcome.scene).catch(() => undefined);
        } catch (error) {
          if (isNetworkFailure(error)) {
            setConnectionLost(true);
            return false;
          }
          setCommandFailed(true);
          // A real rejection (conflict/validation) cannot be repaired by retrying; drop
          // it from the queue so one bad entry cannot block the rest forever, and say so.
          setErrorMessage(
            "One unsaved change could not be accepted and was set aside. The rest of your work is unaffected.",
          );
        }
        setMemoryOps(
          memoryOpsRef.current.filter(
            (op) => op.operationId !== entry.operationId,
          ),
        );
        // Drop the preview locally first; a failed durable removal only leaves an
        // idempotent replay for the next flush.
        setPendingOps(
          pendingOpsRef.current.filter(
            (op) => op.operationId !== entry.operationId,
          ),
        );
        await removeOperation(sessionId, entry.operationId).catch(
          () => undefined,
        );
      }
      return true;
    } finally {
      flushingRef.current = false;
    }
  }, [sessionId, setMemoryOps, setPendingOps, sync]);

  const retryPending = useCallback(async () => {
    if (!guardBusy("Saving…")) {
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
      setPhase("loading");
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
          setPhase("ready");
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
          setPhase("failed");
          setErrorMessage(
            error instanceof Error
              ? error.message
              : "The workspace could not load.",
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
      if (result.status === "committed") {
        setCommitted({ sessionId, turn: result });
      } else {
        setErrorMessage(noticeForTurn(result));
        // A stopped (superseded) reply is the learner's own choice, not a failure.
        if (result.status === "rejected" || result.status === "failed")
          setCommandFailed(true);
      }
    },
    [sessionId],
  );

  const runTurn = useCallback(
    async (label: string, action: () => Promise<TutorTurnResult>) => {
      if (!guardBusy(label)) return;
      const generation = turnGenRef.current;
      const isStale = () => generation !== turnGenRef.current;
      setTurnInFlight(true);
      try {
        const result = await action();
        if (isStale()) return;
        applyTurnResult(result);
        await refresh();
        await flushPending();
      } catch (error) {
        if (isStale()) return;
        if (
          error instanceof ApiClientError &&
          error.code === "revision_conflict"
        ) {
          try {
            const result = await action();
            if (isStale()) return;
            applyTurnResult(result);
            await refresh();
          } catch (second) {
            if (isStale()) return;
            if (isNetworkFailure(second)) setConnectionLost(true);
            else setCommandFailed(true);
            setErrorMessage(
              second instanceof Error
                ? second.message
                : "The tutor turn failed to send.",
            );
            await refresh().catch(() => undefined);
          }
        } else if (isNetworkFailure(error)) {
          setConnectionLost(true);
          setErrorMessage(
            memoryOpsRef.current.length > 0
              ? "The tutor is not reachable right now. Some of your board work is held only in memory, not on this device."
              : "The tutor is not reachable right now. Your board work is kept on this device.",
          );
        } else {
          setCommandFailed(true);
          setErrorMessage(
            error instanceof Error
              ? error.message
              : "The tutor turn failed to send.",
          );
          await refresh().catch(() => undefined);
        }
      } finally {
        // A stopped turn already released the lock; it must not release a newer command's.
        if (!isStale()) {
          setTurnInFlight(false);
          releaseBusy();
        }
      }
    },
    [applyTurnResult, flushPending, guardBusy, refresh, releaseBusy],
  );

  const checkIn = useCallback(
    async (energy: "ready" | "a_bit_tired" | "tired") => {
      const current = state;
      if (current === null) return;
      await runTurn("Starting…", () =>
        client.checkIn(sessionId, newId(), current.session.revision, energy),
      );
    },
    [client, runTurn, sessionId, state],
  );

  const sendLogical = useCallback(
    async (spec: LogicalSpec): Promise<WorkSubmitOutcome> => {
      const current = state;
      if (current === null || current.current_problem === null)
        return "ignored";
      if (!guardBusy(spec.label)) return "ignored";
      const epoch = epochRef.current;
      const generation = turnGenRef.current;
      const isStale = () =>
        epoch !== epochRef.current || generation !== turnGenRef.current;
      // A session change drops the response; a Stop means the server already withdrew only
      // the reply, so the learner's recorded work still counts as answered.
      const staleOutcome = (): WorkSubmitOutcome =>
        epoch !== epochRef.current ? "stale" : "resolved";
      const attemptId = current.current_problem.attempt_id;
      let command = spec.command.current;
      if (
        spec.fenceProblem &&
        command !== null &&
        command.attemptId !== attemptId
      ) {
        spec.command.current = null;
        releaseBusy();
        setErrorMessage(spec.staleMessage);
        return "stale";
      }
      setTurnInFlight(true);
      let release: () => void = () => undefined;
      const stopped = new Promise<"stopped">((resolve) => {
        release = () => resolve("stopped");
      });
      stopWaitersRef.current.add(release);
      const sendOrStop = (
        key: string,
        revision: number,
      ): Promise<TutorTurnResult | "stopped"> => {
        const sent = spec.send(key, revision);
        sent.catch(() => undefined);
        return Promise.race([sent, stopped]);
      };
      if (
        command === null ||
        command.attemptId !== attemptId ||
        command.fingerprint !== spec.fingerprint
      ) {
        command = {
          key: newId(),
          expectedRevision: current.session.revision,
          attemptId,
          fingerprint: spec.fingerprint,
        };
        spec.command.current = command;
      }
      let result: TutorTurnResult | "stopped";
      try {
        try {
          result = await sendOrStop(command.key, command.expectedRevision);
        } catch (error) {
          if (!(
            error instanceof ApiClientError &&
            error.code === "revision_conflict"
          )) {
            throw error;
          }
          // A definite conflict applied nothing. Resync, and only re-ask for the problem the
          // learner was actually looking at; a new problem never inherits the old intent.
          spec.command.current = null;
          const fresh = await refresh();
          if (isStale()) return staleOutcome();
          if ((fresh.current_problem?.attempt_id ?? null) !== attemptId) {
            setErrorMessage(spec.staleMessage);
            return "stale";
          }
          command = {
            key: newId(),
            expectedRevision: fresh.session.revision,
            attemptId,
            fingerprint: spec.fingerprint,
          };
          spec.command.current = command;
          result = await sendOrStop(command.key, command.expectedRevision);
        }
        if (result === "stopped" || isStale()) return staleOutcome();
        if (result.status !== "pending") {
          spec.command.current = null;
        }
        applyTurnResult(result);
        // The server already answered; a failed re-read must not turn that into "uncertain".
        await refresh().catch(() => undefined);
        await flushPending().catch(() => false);
        return result.status === "pending" ? "retained" : "resolved";
      } catch (error) {
        if (isStale()) return staleOutcome();
        if (isNetworkFailure(error)) {
          // Keep the command: the next send retries the same key and body, never a duplicate.
          setConnectionLost(true);
          setErrorMessage(
            memoryOpsRef.current.length > 0
              ? `${spec.uncertainMessage} Some of your board work is held only in memory, not on this device.`
              : spec.uncertainMessage,
          );
        } else {
          spec.command.current = null;
          setCommandFailed(true);
          setErrorMessage(
            error instanceof Error ? error.message : spec.failureMessage,
          );
          await refresh().catch(() => undefined);
        }
        return "retained";
      } finally {
        stopWaitersRef.current.delete(release);
        if (generation === turnGenRef.current) {
          setTurnInFlight(false);
          releaseBusy();
        }
      }
    },
    [applyTurnResult, flushPending, guardBusy, refresh, releaseBusy, state],
  );

  const submitWork = useCallback(
    async (text: string): Promise<WorkSubmitOutcome> => {
      const trimmed = text.trim();
      if (trimmed.length === 0) return "ignored";
      return sendLogical({
        label: "Thinking…",
        command: pendingWorkRef,
        fingerprint: trimmed,
        fenceProblem: true,
        send: (key, revision) =>
          client.submitWork(sessionId, key, revision, trimmed, "typed"),
        uncertainMessage: WORK_UNCERTAIN_MESSAGE,
        staleMessage: WORK_STALE_MESSAGE,
        failureMessage: "The tutor turn failed to send.",
      });
    },
    [client, sendLogical, sessionId],
  );

  const requestHelp = useCallback(async () => {
    await sendLogical({
      label: "Thinking…",
      command: pendingHelpRef,
      fingerprint: "help:hint",
      fenceProblem: false,
      send: (key, revision) =>
        client.requestHelp(sessionId, key, revision, "hint"),
      uncertainMessage: HELP_UNCERTAIN_MESSAGE,
      staleMessage: HELP_STALE_MESSAGE,
      failureMessage: "Help me could not be sent.",
    });
  }, [client, sendLogical, sessionId]);

  const interrupt = useCallback(async () => {
    if (!turnInFlight) return;
    const generation = turnGenRef.current;
    try {
      // Read the server's own epoch and pending turn: only an actually reserved turn is
      // stoppable, and the retry-safe interrupt must name the epoch it observed.
      const fresh = await client.sessionState(sessionId);
      if (generation !== turnGenRef.current || fresh.pending_turn_id === null)
        return;
      await client.interruptSession(
        sessionId,
        fresh.session.cancellation_epoch,
      );
    } catch (error) {
      setErrorMessage(
        isNetworkFailure(error)
          ? "Could not reach the tutor to stop the reply. It may still arrive."
          : error instanceof Error
            ? error.message
            : "The reply could not be stopped.",
      );
      return;
    }
    if (generation !== turnGenRef.current) return;
    // The server has withdrawn the reply: ignore whatever the stopped request returns.
    turnGenRef.current += 1;
    setTurnGeneration(turnGenRef.current);
    pendingHelpRef.current = null;
    pendingWorkRef.current = null;
    for (const settle of stopWaitersRef.current) settle();
    setTurnInFlight(false);
    releaseBusy();
    setErrorMessage(
      "Stopped. Your work is saved and the unfinished reply was dropped.",
    );
    await refresh().catch(() => undefined);
  }, [client, refresh, releaseBusy, sessionId, turnInFlight]);

  const commitSceneAction = useCallback(
    async (
      action: SceneActionRequest,
      label: string,
      options?: { lockPen?: boolean; operationId?: string; quiet?: boolean },
    ) => {
      const current = sceneRef.current;
      const lockPen = options?.lockPen !== false;
      if (current === null || !guardBusy(options?.quiet ? null : label, lockPen)) return false;
      const operationId = options?.operationId ?? newId();
      try {
        const outcome = await commitWithResync(
          sync,
          operationId,
          current.scene_revision,
          action,
        );
        clearSettling(operationId);
        setScene(outcome.scene);
        await saveCachedScene(outcome.scene).catch(() => undefined);
        // A successful save proves connectivity: finish anything still queued.
        const drained = await flushPending();
        if (drained) {
          await refresh().catch(() => undefined);
        }
      } catch (error) {
        if (isNetworkFailure(error)) {
          setConnectionLost(true);
          if (action.op === "add_stroke") {
            // Keep the finished stroke on-device, visibly unsaved, for exactly-once retry.
            const entry: PendingSceneOperation = {
              operationId,
              sessionId,
              queuedAt: new Date().toISOString(),
              action,
            };
            try {
              const stored = await enqueueOperation(entry);
              clearSettling(operationId);
              setPendingOps(stored);
            } catch {
              // Device storage failed too: keep the ink visible and retryable from memory
              // for this session, and say plainly that it is not durable.
              clearSettling(operationId);
              setMemoryOps([...memoryOpsRef.current, entry]);
              setErrorMessage(MEMORY_ONLY_MESSAGE);
            }
          } else {
            // History edits depend on current server state; refuse rather than guess.
            setErrorMessage(
              "That change needs a connection to the tutor. Nothing was changed — try again when it is back.",
            );
          }
        } else {
          // The server answered and refused: show its reason, resync to real state.
          clearSettling(operationId);
          setCommandFailed(true);
          setErrorMessage(
            error instanceof Error
              ? `The tutor could not save that: ${error.message}`
              : "That change could not be saved.",
          );
          await refresh().catch(() => undefined);
        }
      } finally {
        releaseBusy();
      }
      return true;
    },
    [
      clearSettling,
      flushPending,
      guardBusy,
      refresh,
      releaseBusy,
      sessionId,
      setMemoryOps,
      setPendingOps,
      sync,
    ],
  );

  const commitStroke = useCallback(
    (points: readonly LogicalPoint[]) => {
      if (points.length === 0) return Promise.resolve();
      const operationId = newId();
      const epoch = epochRef.current;
      const copy = points.map((point) => ({ x: point.x, y: point.y }));
      setSettlingStrokes((current) => [
        ...current,
        { id: operationId, points: copy },
      ]);
      const job = strokeQueueRef.current.then(async () => {
        if (epoch !== epochRef.current) {
          clearSettling(operationId);
          return;
        }
        while (busyRef.current && epoch === epochRef.current) {
          await new Promise((resolve) => {
            setTimeout(resolve, 16);
          });
        }
        if (epoch !== epochRef.current) {
          clearSettling(operationId);
          return;
        }
        try {
          while (epoch === epochRef.current && sceneRef.current !== null) {
            while (busyRef.current && epoch === epochRef.current) {
              await new Promise((resolve) => {
                setTimeout(resolve, 16);
              });
            }
            if (epoch !== epochRef.current || sceneRef.current === null) {
              break;
            }
            const accepted = await commitSceneAction(
              { op: "add_stroke", points: copy },
              "Saving…",
              { lockPen: false, quiet: true, operationId },
            );
            if (accepted !== false) {
              break;
            }
          }
        } finally {
          clearSettling(operationId);
        }
      });
      strokeQueueRef.current = job.then(
        () => undefined,
        () => undefined,
      );
      return job;
    },
    [clearSettling, commitSceneAction],
  );

  const eraseObject = useCallback(
    async (objectId: string) => {
      await commitSceneAction(
        { op: "erase_object", target_object_id: objectId },
        "Erasing…",
        { quiet: true },
      );
    },
    [commitSceneAction],
  );
  const undo = useCallback(async () => {
    await commitSceneAction({ op: "undo" }, "Undoing…", { quiet: true });
  }, [commitSceneAction]);
  const redo = useCallback(async () => {
    await commitSceneAction({ op: "redo" }, "Redoing…", { quiet: true });
  }, [commitSceneAction]);
  const undoTutorMove = useCallback(async () => {
    await commitSceneAction(
      { op: "undo_tutor_move" },
      "Removing tutor marks…",
      { quiet: true },
    );
  }, [commitSceneAction]);

  const lastTurn =
    committed !== null && committed.sessionId === sessionId
      ? committed.turn
      : null;
  const needsCheckIn = state !== null && state.current_problem === null;
  const unsavedOps = useMemo(
    () => mergeQueues(pendingOps, memoryOps),
    [pendingOps, memoryOps],
  );
  const pendingStrokes = useMemo(
    () => previewsFromQueue(unsavedOps),
    [unsavedOps],
  );

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
    penLocked,
    settlingStrokes,
    errorMessage,
    pendingStrokes,
    pendingCount: unsavedOps.length,
    memoryOnlyCount: memoryOps.filter(
      (op) =>
        !pendingOps.some((durable) => durable.operationId === op.operationId),
    ).length,
    needsCheckIn,
    canInterrupt: turnInFlight,
    turnGeneration,
    connectionLost,
    commandFailed,
    interrupt,
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
