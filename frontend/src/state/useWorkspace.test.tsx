/**
 * Workspace durability tests, driven through the REAL ApiClient with a fake fetch
 * transport. The fake backend is a transport double: it mirrors the wire contract
 * (idempotent operation ids, revision CAS, snapshot reads) so these tests exercise the
 * client's outbox/cache/save-state behavior. The authoritative history semantics are
 * covered by the backend pytest suite; here we prove the client sends, queues, retries
 * and renders honestly.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { act, renderHook, waitFor } from '@testing-library/react-native';

import { ApiClient } from '../api/client';
import { enqueueOperation, loadPendingOperations } from '../storage/outbox';
import { saveCachedScene } from '../storage/sceneCache';

import { useWorkspace } from './useWorkspace';

const SESSION_ID = 's1';

type FakeObject = {
  id: string;
  author_role: 'student' | 'tutor';
  kind: string;
  payload: Record<string, unknown>;
  moveId: string | null;
  deleted: boolean;
};

type PostedOp = {
  operationId: string;
  expectedRevision: number;
  action: Record<string, unknown>;
};

function makeFakeBackend(seed?: { objects?: FakeObject[]; sceneRevision?: number }) {
  let sceneGate: (() => void) | null = null;
  const backend = {
    online: true,
    /** When set, every commit fails with this decided server response (a rejection). */
    rejectCommitsWith: null as null | { status: number; code: string; message: string },
    /** When true, scene snapshot fetches hang until releaseScene() is called. */
    holdSceneFetch: false,
    /** Number of scene fetches currently parked on the hold gate. */
    heldSceneRequests: 0,
    releaseScene() {
      backend.holdSceneFetch = false;
      sceneGate?.();
      sceneGate = null;
    },
    sceneRevision: seed?.sceneRevision ?? 0,
    objects: [...(seed?.objects ?? [])],
    /** Every POST the client attempted, including ones the network swallowed. */
    attempts: [] as PostedOp[],
    /** Successful (accepted) commits only. */
    posted: [] as PostedOp[],
    opLog: new Map<string, string>(),
  };

  // Author-safe student history: undo reverses the latest in-effect own add/erase;
  // a new op invalidates the redo stack. Tutor moves undo as a group, untouched by
  // student undo/redo. (The authoritative semantics live server-side; this double only
  // mirrors the wire-level effects the client renders.)
  type HistoryEntry = { undo: () => void; redo: () => void };
  const history: HistoryEntry[] = [];
  const redoStack: HistoryEntry[] = [];

  const visibleObjects = () =>
    backend.objects
      .filter((object) => !object.deleted)
      .map((object) => ({
        schema_version: 'scene-object.v1',
        id: object.id,
        learner_id: 'learner-1',
        session_id: SESSION_ID,
        author_role: object.author_role,
        semantic_role: 'work',
        kind: object.kind,
        payload: object.payload,
        teaching_step_id: object.moveId,
        created_at: '2026-10-17T00:00:00.000Z',
        deleted_at: null,
      }));

  const snapshot = () => ({
    schema_version: 'scene-snapshot.v1',
    session_id: SESSION_ID,
    scene_revision: backend.sceneRevision,
    board_width: 1600,
    board_height: 1200,
    pen_width: 3,
    objects: visibleObjects(),
    student_undo_available: history.length > 0,
    student_redo_available: redoStack.length > 0,
    tutor_move_undo_available: backend.objects.some((o) => o.author_role === 'tutor' && !o.deleted),
  });

  const errorEnvelope = (code: string, message: string) => ({
    schema_version: 'error.v1',
    error: { code, message },
  });

  const commit = (body: {
    operation_id: string;
    expected_scene_revision: number;
    action: Record<string, unknown> & { op: string; points?: { x: number; y: number }[] };
  }) => {
    if (backend.rejectCommitsWith !== null) {
      const rejection = backend.rejectCommitsWith;
      return { status: rejection.status, body: errorEnvelope(rejection.code, rejection.message) };
    }
    const contentHash = JSON.stringify(body.action);
    const known = backend.opLog.get(body.operation_id);
    if (known !== undefined) {
      if (known === contentHash) {
        return {
          status: 200,
          body: {
            schema_version: 'scene-operation-result.v1',
            operation_id: body.operation_id,
            session_id: SESSION_ID,
            scene_revision: backend.sceneRevision,
            kind: 'add_object',
            author_role: 'student',
            object_id: null,
            affected_object_ids: [],
            replayed: true,
          },
        };
      }
      return { status: 409, body: errorEnvelope('idempotency_conflict', 'same id, different content') };
    }
    if (body.expected_scene_revision !== backend.sceneRevision) {
      return { status: 409, body: errorEnvelope('revision_conflict', 'stale scene revision') };
    }
    backend.sceneRevision += 1;
    backend.opLog.set(body.operation_id, contentHash);
    backend.posted.push({
      operationId: body.operation_id,
      expectedRevision: body.expected_scene_revision,
      action: body.action,
    });
    let affected: string[] = [];
    if (body.action.op === 'add_stroke') {
      const object: FakeObject = {
        id: `obj-${body.operation_id}`,
        author_role: 'student',
        kind: 'path',
        payload: { points: body.action.points ?? [], width: 3, color_role: 'student' },
        moveId: null,
        deleted: false,
      };
      backend.objects.push(object);
      history.push({
        undo: () => {
          object.deleted = true;
        },
        redo: () => {
          object.deleted = false;
        },
      });
      redoStack.length = 0;
      affected = [object.id];
    } else if (body.action.op === 'erase_object') {
      const target = backend.objects.find((o) => o.id === body.action.target_object_id);
      if (target && !target.deleted) {
        target.deleted = true;
        history.push({
          undo: () => {
            target.deleted = false;
          },
          redo: () => {
            target.deleted = true;
          },
        });
        redoStack.length = 0;
        affected = [target.id];
      }
    } else if (body.action.op === 'undo') {
      const entry = history.pop();
      if (entry) {
        entry.undo();
        redoStack.push(entry);
        affected = ['undone'];
      }
    } else if (body.action.op === 'redo') {
      const entry = redoStack.pop();
      if (entry) {
        entry.redo();
        history.push(entry);
        affected = ['redone'];
      }
    } else if (body.action.op === 'undo_tutor_move') {
      const tutorMoves = backend.objects.filter((o) => o.author_role === 'tutor' && !o.deleted);
      const newest = tutorMoves.map((o) => o.moveId).filter((m): m is string => m !== null).pop();
      for (const object of tutorMoves.filter((o) => o.moveId === newest)) {
        object.deleted = true;
        affected.push(object.id);
      }
    }
    return {
      status: 200,
      body: {
        schema_version: 'scene-operation-result.v1',
        operation_id: body.operation_id,
        session_id: SESSION_ID,
        scene_revision: backend.sceneRevision,
        kind: body.action.op === 'add_stroke' ? 'add_object' : body.action.op,
        author_role: 'student',
        object_id: affected[0] ?? null,
        affected_object_ids: affected,
        replayed: false,
      },
    };
  };

  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    // Record every operation commit the client attempted, even ones the network drops.
    if (url.endsWith(`/sessions/${SESSION_ID}/scene/operations`) && init?.method === 'POST') {
      const parsed = JSON.parse(String(init.body)) as {
        operation_id: string;
        expected_scene_revision: number;
        action: Record<string, unknown>;
      };
      backend.attempts.push({
        operationId: parsed.operation_id,
        expectedRevision: parsed.expected_scene_revision,
        action: parsed.action,
      });
    }
    if (!backend.online) {
      throw new TypeError('Network request failed');
    }
    const respond = (status: number, body: unknown) =>
      ({
        ok: status >= 200 && status < 300,
        status,
        json: async () => body,
      }) as Response;
    if (url.endsWith(`/sessions/${SESSION_ID}/state`)) {
      return respond(200, {
        schema_version: 'session-state.v1',
        session: {
          schema_version: 'session.v1',
          id: SESSION_ID,
          learner_id: 'learner-1',
          status: 'active',
          goal: null,
          revision: 1,
          started_at: '2026-10-17T00:00:00.000Z',
          ended_at: null,
        },
        current_problem: {
          problem_id: 'problem.distribute',
          attempt_id: 'attempt-1',
          statement: '2(x + 3) = 14',
          kind: 'practice',
          concept_id: 'concept.distribution',
          statement_object_id: null,
        },
        pace: 'standard',
        pending_turn_id: null,
        session_context_recheck: false,
        persona: null,
      });
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/scene`)) {
      if (backend.holdSceneFetch) {
        backend.heldSceneRequests += 1;
        await new Promise<void>((resolve) => {
          sceneGate = resolve;
        });
        backend.heldSceneRequests -= 1;
      }
      return respond(200, snapshot());
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/scene/operations`) && init?.method === 'POST') {
      const result = commit(JSON.parse(String(init.body)));
      return respond(result.status, result.body);
    }
    return respond(404, errorEnvelope('not_found', url));
  }) as typeof fetch;

  return { backend, fetchImpl };
}

function tutorMark(id: string, moveId: string): FakeObject {
  return {
    id,
    author_role: 'tutor',
    kind: 'bracket',
    payload: { start: { x: 1, y: 2 }, end: { x: 3, y: 2 }, color_role: 'tutor' },
    moveId,
    deleted: false,
  };
}

function studentMark(id: string): FakeObject {
  return {
    id,
    author_role: 'student',
    kind: 'path',
    payload: { points: [{ x: 5, y: 5 }, { x: 6, y: 6 }], width: 3, color_role: 'student' },
    moveId: null,
    deleted: false,
  };
}

async function renderWorkspace(fetchImpl: typeof fetch) {
  const client = new ApiClient('http://tutor.test', 'token', fetchImpl);
  const hook = renderHook(() => useWorkspace(client, SESSION_ID));
  await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
  return hook;
}

beforeEach(async () => {
  await AsyncStorage.clear();
});

describe('useWorkspace durable scene pipeline', () => {
  it('loads the scene and mirrors it into the durable cache', async () => {
    const { backend, fetchImpl } = makeFakeBackend({ objects: [studentMark('s1')] });
    const hook = await renderWorkspace(fetchImpl);
    expect(hook.result.current.scene?.objects.map((o) => o.id)).toEqual(['s1']);
    const cached = await AsyncStorage.getItem(`rubberducky.scene-cache.v1.${SESSION_ID}`);
    expect(cached).not.toBeNull();
    expect(JSON.parse(cached!).objects).toHaveLength(1);
    expect(backend.posted).toHaveLength(0);
  });

  it('commits a stroke once and persists the new snapshot to the cache', async () => {
    const { backend, fetchImpl } = makeFakeBackend();
    const hook = await renderWorkspace(fetchImpl);
    await act(async () => {
      await hook.result.current.commitStroke([{ x: 10, y: 10 }, { x: 40, y: 12 }]);
    });
    expect(backend.posted).toHaveLength(1);
    expect(backend.posted[0].action.op).toBe('add_stroke');
    expect(hook.result.current.scene?.objects).toHaveLength(1);
    expect(hook.result.current.pendingCount).toBe(0);
    const cached = JSON.parse(
      (await AsyncStorage.getItem(`rubberducky.scene-cache.v1.${SESSION_ID}`))!,
    );
    expect(cached.objects).toHaveLength(1);
  });

  it('queues a finished stroke during a disconnect and keeps it visibly unsaved', async () => {
    const { backend, fetchImpl } = makeFakeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.online = false;
    await act(async () => {
      await hook.result.current.commitStroke([{ x: 1, y: 1 }, { x: 2, y: 8 }]);
    });
    // Not committed, not lost: queued with a stable id and previewed as unsaved.
    expect(backend.attempts).toHaveLength(1); // the failed attempt
    expect(backend.posted).toHaveLength(0); // never committed server-side
    expect(hook.result.current.pendingCount).toBe(1);
    expect(hook.result.current.pendingStrokes[0].points).toEqual([
      { x: 1, y: 1 },
      { x: 2, y: 8 },
    ]);
    expect(hook.result.current.scene?.objects).toHaveLength(0);
    const queued = await loadPendingOperations(SESSION_ID);
    expect(queued).toHaveLength(1);
    expect(queued[0].operationId).toBe(backend.attempts[0].operationId);
  });

  it('reconnect flushes the queued stroke exactly once with the SAME operation id', async () => {
    const { backend, fetchImpl } = makeFakeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.online = false;
    await act(async () => {
      await hook.result.current.commitStroke([{ x: 1, y: 1 }, { x: 9, y: 9 }]);
    });
    const queuedId = (await loadPendingOperations(SESSION_ID))[0].operationId;
    backend.online = true;
    await act(async () => {
      await hook.result.current.retryPending();
    });
    expect(hook.result.current.pendingCount).toBe(0);
    expect(await loadPendingOperations(SESSION_ID)).toEqual([]);
    const retried = backend.posted.filter((p) => p.operationId === queuedId);
    // Exactly one effective commit: the retry reuses the id; replay never duplicates.
    expect(retried).toHaveLength(1);
    expect(hook.result.current.scene?.objects).toHaveLength(1);
  });

  it('after a reload, a stroke that actually landed is replayed, not duplicated', async () => {
    const { backend, fetchImpl } = makeFakeBackend({ objects: [studentMark('obj-lost-ack')] });
    // The stroke committed server-side, but the acknowledgement was lost: the op is
    // still in the durable outbox AND already in the server op log.
    const action = { op: 'add_stroke' as const, points: [{ x: 3, y: 3 }] };
    backend.opLog.set('lost-ack-op', JSON.stringify(action));
    await enqueueOperation({
      operationId: 'lost-ack-op',
      sessionId: SESSION_ID,
      queuedAt: '2026-10-17T00:00:00.000Z',
      action,
    });
    const hook = await renderWorkspace(fetchImpl);
    await waitFor(() => expect(hook.result.current.pendingCount).toBe(0));
    expect(backend.posted.filter((p) => p.operationId === 'lost-ack-op')).toHaveLength(0);
    expect(hook.result.current.scene?.objects).toHaveLength(1); // replayed, not duplicated
  });

  it('paints the cached committed scene immediately on re-entry, then refreshes', async () => {
    const { backend, fetchImpl } = makeFakeBackend({ objects: [studentMark('server-1')] });
    backend.holdSceneFetch = true;
    await saveCachedScene({
      schema_version: 'scene-snapshot.v1',
      session_id: SESSION_ID,
      scene_revision: 2,
      board_width: 1600,
      board_height: 1200,
      pen_width: 3,
      objects: [
        {
          schema_version: 'scene-object.v1',
          id: 'cached-1',
          learner_id: 'learner-1',
          session_id: SESSION_ID,
          author_role: 'student',
          semantic_role: 'work',
          kind: 'path',
          payload: { points: [{ x: 1, y: 1 }, { x: 2, y: 2 }], width: 3, color_role: 'student' },
          teaching_step_id: null,
          created_at: '2026-10-17T00:00:00.000Z',
          deleted_at: null,
        },
      ],
      student_undo_available: true,
      student_redo_available: false,
      tutor_move_undo_available: false,
    });
    // Create the client once: a fresh client per render would re-run the load effect.
    const client = new ApiClient('http://tutor.test', 'token', fetchImpl);
    const hook = renderHook(() => useWorkspace(client, SESSION_ID));
    // The held server fetch has not resolved: the board still paints the cached scene.
    await waitFor(() =>
      expect(hook.result.current.scene?.objects.map((o) => o.id)).toEqual(['cached-1']),
    );
    expect(hook.result.current.phase).toBe('loading');
    // Wait until the server fetch is actually parked on the gate, then release it.
    await waitFor(() => expect(backend.heldSceneRequests).toBe(1));
    backend.releaseScene();
    // Once the server answers, authoritative state replaces the cache paint.
    await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
    expect(hook.result.current.scene?.objects.map((o) => o.id)).toEqual(['server-1']);
  });

  it('a server rejection surfaces the reason and is NOT queued for blind retry', async () => {
    const { backend, fetchImpl } = makeFakeBackend();
    const hook = await renderWorkspace(fetchImpl);
    // A decided server refusal (e.g. the session ended or validation failed) can never
    // be repaired by retrying, so it must surface honestly and stay out of the outbox.
    backend.rejectCommitsWith = {
      status: 409,
      code: 'session_inactive',
      message: 'This session has ended.',
    };
    await act(async () => {
      await hook.result.current.commitStroke([{ x: 4, y: 4 }, { x: 8, y: 8 }]);
    });
    expect(hook.result.current.errorMessage).toMatch(/could not save/i);
    expect(hook.result.current.errorMessage).toMatch(/session has ended/i);
    expect(hook.result.current.pendingCount).toBe(0);
    expect(await loadPendingOperations(SESSION_ID)).toEqual([]);
  });

  it('refuses history edits while offline instead of guessing at stale state', async () => {
    const { backend, fetchImpl } = makeFakeBackend({ objects: [studentMark('s1')] });
    const hook = await renderWorkspace(fetchImpl);
    backend.online = false;
    const postsBefore = backend.posted.length;
    await act(async () => {
      await hook.result.current.undo();
    });
    expect(backend.posted.length).toBe(postsBefore); // the failed attempt only
    expect(hook.result.current.errorMessage).toMatch(/needs a connection/);
    expect(await loadPendingOperations(SESSION_ID)).toEqual([]); // never queued
    expect(hook.result.current.scene?.objects.map((o) => o.id)).toEqual(['s1']); // unchanged
  });

  it('drives erase, student undo/redo and grouped tutor undo through interleaved history', async () => {
    const { backend, fetchImpl } = makeFakeBackend();
    const hook = await renderWorkspace(fetchImpl);

    // Student stroke BEFORE the tutor move.
    await act(async () => {
      await hook.result.current.commitStroke([{ x: 10, y: 10 }, { x: 60, y: 10 }]);
    });
    const strokeA = `obj-${backend.posted[backend.posted.length - 1].operationId}`;

    // A tutor teaching move lands server-side (two grouped objects) mid-session.
    backend.objects.push(tutorMark('t1', 'move-1'), tutorMark('t2', 'move-1'));
    backend.sceneRevision += 1;

    // Student stroke AFTER the tutor move: resyncs past the tutor's revision, commits.
    await act(async () => {
      await hook.result.current.commitStroke([{ x: 10, y: 90 }, { x: 60, y: 90 }]);
    });
    const strokeB = `obj-${backend.posted[backend.posted.length - 1].operationId}`;
    const visibleAfterMix = hook.result.current.scene?.objects.map((o) => o.id) ?? [];
    expect(visibleAfterMix).toEqual([strokeA, 't1', 't2', strokeB]);

    // Erase targets exactly the intended student stroke.
    await act(async () => {
      await hook.result.current.eraseObject(strokeA);
    });
    expect(backend.posted[backend.posted.length - 1].action).toEqual({
      op: 'erase_object',
      target_object_id: strokeA,
    });
    expect(hook.result.current.scene?.objects.map((o) => o.id)).toEqual(['t1', 't2', strokeB]);

    // Student undo reverses the erase; redo re-applies it. Tutor marks untouched.
    await act(async () => {
      await hook.result.current.undo();
    });
    expect(hook.result.current.scene?.objects.map((o) => o.id)).toEqual([
      strokeA,
      't1',
      't2',
      strokeB,
    ]);
    await act(async () => {
      await hook.result.current.redo();
    });
    expect(hook.result.current.scene?.objects.map((o) => o.id)).toEqual(['t1', 't2', strokeB]);
    await act(async () => {
      await hook.result.current.undo();
    });

    // Grouped tutor undo removes the whole move and leaves BOTH student strokes.
    await act(async () => {
      await hook.result.current.undoTutorMove();
    });
    expect(backend.posted[backend.posted.length - 1].action).toEqual({ op: 'undo_tutor_move' });
    const visible = hook.result.current.scene?.objects.map((o) => o.id) ?? [];
    expect(visible).toContain(strokeA);
    expect(visible).toContain(strokeB);
    expect(visible).not.toContain('t1');
    expect(visible).not.toContain('t2');

    // Student history is still intact after the tutor undo: redo erases A again.
    await act(async () => {
      await hook.result.current.redo();
    });
    const finalVisible = hook.result.current.scene?.objects.map((o) => o.id) ?? [];
    expect(finalVisible).toEqual([strokeB]);
  });
});
