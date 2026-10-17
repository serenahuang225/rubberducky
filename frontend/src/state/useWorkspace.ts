/**
 * Workspace controller: owns the session, scene snapshot and tutor conversation state
 * for the whiteboard screen. All mutations go through the real API; the scene is
 * re-fetched after every committed change so the board always shows durable truth.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { LogicalPoint } from '../board/geometry';
import { ApiClient, ApiClientError, type SceneActionRequest } from '../api/client';
import type { SceneSnapshot, SessionState, TutorTurnResult } from '../api/contracts';
import { newId } from '../api/ids';
import { commitWithResync, makeSceneSync } from '../api/sceneSync';

export type WorkspacePhase = 'loading' | 'ready' | 'failed';

export type WorkspaceController = {
  phase: WorkspacePhase;
  state: SessionState | null;
  scene: SceneSnapshot | null;
  /** Latest committed tutor utterance for the prompt bar. */
  lastUtterance: string | null;
  lastExpectedAction: string | null;
  /** Truthful short status for the prompt bar. */
  busyLabel: string | null;
  errorMessage: string | null;
  needsCheckIn: boolean;
  retry: () => void;
  checkIn: (energy: 'ready' | 'a_bit_tired' | 'tired') => Promise<void>;
  submitWork: (text: string) => Promise<void>;
  commitStroke: (points: readonly LogicalPoint[]) => Promise<void>;
  eraseObject: (objectId: string) => Promise<void>;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
  undoTutorMove: () => Promise<void>;
};

export function useWorkspace(client: ApiClient, sessionId: string): WorkspaceController {
  const [phase, setPhase] = useState<WorkspacePhase>('loading');
  const [state, setState] = useState<SessionState | null>(null);
  const [scene, setScene] = useState<SceneSnapshot | null>(null);
  const [lastUtterance, setLastUtterance] = useState<string | null>(null);
  const [lastExpectedAction, setLastExpectedAction] = useState<string | null>(null);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const busyRef = useRef(false);

  const sync = useMemo(() => makeSceneSync(client, sessionId), [client, sessionId]);

  const refresh = useCallback(async () => {
    const [nextState, nextScene] = await Promise.all([
      client.sessionState(sessionId),
      client.sceneSnapshot(sessionId),
    ]);
    setState(nextState);
    setScene(nextScene);
  }, [client, sessionId]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      setPhase('loading');
      setErrorMessage(null);
      try {
        await refresh();
        if (active) setPhase('ready');
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
  }, [refresh, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  const guardBusy = useCallback((label: string): boolean => {
    if (busyRef.current) {
      return false;
    }
    busyRef.current = true;
    setBusyLabel(label);
    setErrorMessage(null);
    return true;
  }, []);

  const releaseBusy = useCallback(() => {
    busyRef.current = false;
    setBusyLabel(null);
  }, []);

  const runTurn = useCallback(
    async (label: string, action: () => Promise<TutorTurnResult>) => {
      if (!guardBusy(label)) return;
      try {
        const result = await action();
        if (result.status === 'committed') {
          setLastUtterance(result.utterance);
          setLastExpectedAction(result.expected_student_action);
        } else if (result.status === 'rejected') {
          setErrorMessage('The tutor could not use that turn; your work is unchanged.');
        } else {
          setErrorMessage('The tutor turn did not complete; your work is unchanged.');
        }
        await refresh();
      } catch (error) {
        if (error instanceof ApiClientError && error.code === 'revision_conflict') {
          try {
            const result = await action();
            if (result.status === 'committed') {
              setLastUtterance(result.utterance);
              setLastExpectedAction(result.expected_student_action);
            }
            await refresh();
          } catch (second) {
            setErrorMessage(
              second instanceof Error ? second.message : 'The tutor turn failed to send.',
            );
            await refresh().catch(() => undefined);
          }
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
    [guardBusy, refresh, releaseBusy],
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

  const commitSceneAction = useCallback(
    async (action: SceneActionRequest, label: string) => {
      const current = scene;
      if (current === null || !guardBusy(label)) return;
      try {
        const outcome = await commitWithResync(
          sync,
          newId(),
          current.scene_revision,
          action,
        );
        setScene(outcome.scene);
      } catch (error) {
        setErrorMessage(
          error instanceof Error ? error.message : 'That change could not be saved.',
        );
        await refresh().catch(() => undefined);
      } finally {
        releaseBusy();
      }
    },
    [guardBusy, refresh, releaseBusy, scene, sync],
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

  const needsCheckIn = state !== null && state.current_problem === null;

  return {
    phase,
    state,
    scene,
    lastUtterance,
    lastExpectedAction,
    busyLabel,
    errorMessage,
    needsCheckIn,
    retry,
    checkIn,
    submitWork,
    commitStroke,
    eraseObject,
    undo,
    redo,
    undoTutorMove,
  };
}
