/**
 * Help me through the real ApiClient against a transport double that mirrors the server's
 * idempotency/revision rules (a replayed key returns the stored outcome; a stale expected
 * revision is a definite 409). The authoritative semantics live in the backend suite; these
 * tests pin the client's command identity, retry and resync behavior.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { act, renderHook, waitFor } from '@testing-library/react-native';

import { ApiClient } from '../api/client';
import { METHOD_SLIP_TURN } from '../testing/teachingFixtures';

import { useWorkspace } from './useWorkspace';

type HelpMode = 'conflict' | 'drop_before' | 'drop_after' | 'unavailable' | 'rejected' | 'hold';

type HelpCall = { key: string; body: Record<string, unknown> };

function makeBackend(sessionId = 's1') {
  const backend = {
    revision: 1,
    sceneRevision: 1,
    attemptId: 'attempt-1',
    tutorMarks: 0,
    modes: [] as HelpMode[],
    helpCalls: [] as HelpCall[],
    workCalls: 0,
    stored: new Map<string, unknown>(),
    held: null as null | (() => void),
  };
  const respond = (status: number, body: unknown) =>
    ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;
  const error = (status: number, code: string, message = code) =>
    respond(status, { schema_version: 'error.v1', error: { code, message } });

  const sceneObjects = () =>
    Array.from({ length: backend.tutorMarks }, (_, index) => ({
      schema_version: 'scene-object.v1',
      id: `mark-${index}`,
      learner_id: 'learner-1',
      session_id: sessionId,
      author_role: 'tutor',
      semantic_role: 'grouping_mark',
      kind: 'bracket',
      payload: { start: { x: 1, y: 2 }, end: { x: 3, y: 2 }, color_role: 'tutor' },
      teaching_step_id: 'move-1',
      created_at: '2026-10-17T00:00:00.000Z',
      deleted_at: null,
    }));

  const helpResult = (mode: 'rejected' | 'committed') => ({
    ...METHOD_SLIP_TURN,
    turn_id: `turn-${backend.revision}`,
    status: mode,
    base_revision: backend.revision - 1,
    session_revision: backend.revision,
    student_input: {
      ...METHOD_SLIP_TURN.student_input,
      input_mode: 'help_button',
      text: null,
      classification: 'not_sure',
      verification: null,
      reasoning_assessment: null,
      assessment_independent: null,
      eligibility: [],
    },
    action_type: 'smaller_scaffold',
    utterance: mode === 'committed' ? 'Let us start smaller: what does the 2 multiply?' : null,
    expected_student_action: mode === 'committed' ? 'Name what the 2 multiplies.' : null,
    hypothesis: null,
    representation: 'outside_factor',
    hint_level: 1,
    drawings: [],
  });

  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (url.endsWith(`/sessions/${sessionId}/state`)) {
      return respond(200, {
        schema_version: 'session-state.v1',
        session: {
          schema_version: 'session.v1',
          id: sessionId,
          learner_id: 'learner-1',
          status: 'active',
          goal: null,
          revision: backend.revision,
          started_at: '2026-10-17T00:00:00.000Z',
          ended_at: null,
        },
        current_problem: {
          problem_id: 'problem.distribute',
          attempt_id: backend.attemptId,
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
    if (url.endsWith(`/sessions/${sessionId}/scene`)) {
      return respond(200, {
        schema_version: 'scene-snapshot.v1',
        session_id: sessionId,
        scene_revision: backend.sceneRevision,
        board_width: 1600,
        board_height: 1200,
        pen_width: 3,
        objects: sceneObjects(),
        student_undo_available: false,
        student_redo_available: false,
        tutor_move_undo_available: backend.tutorMarks > 0,
      });
    }
    if (url.endsWith(`/sessions/${sessionId}/work`) && method === 'POST') {
      backend.workCalls += 1;
      return error(500, 'unexpected', 'work must not be used for Help me');
    }
    if (url.endsWith(`/sessions/${sessionId}/help`) && method === 'POST') {
      const headers = init?.headers as Record<string, string>;
      const key = headers['Idempotency-Key'];
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      backend.helpCalls.push({ key, body });
      const mode = backend.modes.shift();
      if (mode === 'drop_before') throw new TypeError('Network request failed');
      if (mode === 'conflict') return error(409, 'revision_conflict', 'stale revision');
      const known = backend.stored.get(key);
      if (known !== undefined) {
        return respond(200, { ...(known as object), replayed: true });
      }
      if (body.expected_revision !== backend.revision) {
        return error(409, 'revision_conflict', 'stale revision');
      }
      if (mode === 'unavailable') return error(503, 'provider_unavailable', 'The tutor model is not ready.');
      if (mode === 'hold') {
        await new Promise<void>((resolve) => {
          backend.held = resolve;
        });
      }
      backend.revision += 1;
      backend.sceneRevision += 2;
      backend.tutorMarks += 1;
      const result = helpResult(mode === 'rejected' ? 'rejected' : 'committed');
      backend.stored.set(key, result);
      if (mode === 'drop_after') throw new TypeError('Network request failed');
      return respond(200, result);
    }
    if (url.endsWith('/health/model')) return error(404, 'not_found');
    return error(404, 'not_found', url);
  }) as typeof fetch;

  return { backend, fetchImpl };
}

async function renderWorkspace(fetchImpl: typeof fetch, sessionId = 's1') {
  const client = new ApiClient('http://tutor.test', 'token', fetchImpl);
  const hook = renderHook((props: { sessionId: string }) => useWorkspace(client, props.sessionId), {
    initialProps: { sessionId },
  });
  await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
  return hook;
}

beforeEach(async () => {
  await AsyncStorage.clear();
});

describe('useWorkspace requestHelp', () => {
  it('sends Help me to /help with the current revision, never as work, and renders the committed move', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);

    await act(async () => {
      await hook.result.current.requestHelp();
    });

    expect(backend.workCalls).toBe(0);
    expect(backend.helpCalls).toHaveLength(1);
    expect(backend.helpCalls[0].body).toEqual({
      schema_version: 'help-request.v1',
      expected_revision: 1,
      mode: 'hint',
    });
    expect(backend.helpCalls[0].key.length).toBeGreaterThanOrEqual(8);
    expect(hook.result.current.lastUtterance).toBe('Let us start smaller: what does the 2 multiply?');
    expect(hook.result.current.lastExpectedAction).toBe('Name what the 2 multiplies.');
    expect(hook.result.current.lastTurn?.representation).toBe('outside_factor');
    expect(hook.result.current.lastTurn?.student_input?.input_mode).toBe('help_button');
    // The authoritative scene and revision were re-read after the committed move.
    expect(hook.result.current.scene?.objects).toHaveLength(1);
    expect(hook.result.current.state?.session.revision).toBe(2);
    expect(hook.result.current.errorMessage).toBeNull();
  });

  it('each separate Help me press is a new command with a new key', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    await act(async () => {
      await hook.result.current.requestHelp();
    });
    await act(async () => {
      await hook.result.current.requestHelp();
    });
    expect(backend.helpCalls).toHaveLength(2);
    expect(backend.helpCalls[0].key).not.toBe(backend.helpCalls[1].key);
    expect(backend.helpCalls[1].body.expected_revision).toBe(2);
  });

  it('an uncertain failure before the server saw it retries with the SAME key and body', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['drop_before'];

    await act(async () => {
      await hook.result.current.requestHelp();
    });
    expect(hook.result.current.errorMessage).toMatch(/not be counted twice|not sure/i);
    expect(hook.result.current.lastUtterance).toBeNull();

    await act(async () => {
      await hook.result.current.requestHelp();
    });
    expect(backend.helpCalls).toHaveLength(2);
    expect(backend.helpCalls[1]).toEqual(backend.helpCalls[0]);
    expect(hook.result.current.lastUtterance).toMatch(/start smaller/);
    expect(hook.result.current.errorMessage).toBeNull();
    expect(backend.revision).toBe(2);
  });

  it('a lost reply after the server committed replays one turn instead of creating a second', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['drop_after'];

    await act(async () => {
      await hook.result.current.requestHelp();
    });
    expect(backend.revision).toBe(2);

    await act(async () => {
      await hook.result.current.requestHelp();
    });
    expect(backend.helpCalls).toHaveLength(2);
    expect(backend.helpCalls[1]).toEqual(backend.helpCalls[0]);
    // Replay: the server still has exactly one committed help turn.
    expect(backend.revision).toBe(2);
    expect(backend.tutorMarks).toBe(1);
    expect(hook.result.current.lastTurn?.replayed).toBe(true);
    expect(hook.result.current.state?.session.revision).toBe(2);
  });

  it('a revision conflict on the same problem resyncs and sends one fresh command', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    // Another action moved the session on, but the learner is still on the same problem.
    backend.revision = 3;

    await act(async () => {
      await hook.result.current.requestHelp();
    });
    expect(backend.helpCalls).toHaveLength(2);
    expect(backend.helpCalls[0].body.expected_revision).toBe(1);
    expect(backend.helpCalls[1].body.expected_revision).toBe(3);
    expect(backend.helpCalls[1].key).not.toBe(backend.helpCalls[0].key);
    expect(hook.result.current.lastUtterance).toMatch(/start smaller/);
    expect(hook.result.current.state?.session.revision).toBe(4);
  });

  it('a conflict after the problem changed resyncs but never applies the stale intent', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.revision = 5;
    backend.attemptId = 'attempt-2';

    await act(async () => {
      await hook.result.current.requestHelp();
    });
    expect(backend.helpCalls).toHaveLength(1);
    expect(backend.revision).toBe(5);
    expect(backend.tutorMarks).toBe(0);
    expect(hook.result.current.lastUtterance).toBeNull();
    expect(hook.result.current.state?.current_problem?.attempt_id).toBe('attempt-2');
    expect(hook.result.current.state?.session.revision).toBe(5);
    expect(hook.result.current.errorMessage).toMatch(/problem changed|press Help me again/i);
  });

  it('gives up after one resync when the conflict repeats', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['conflict', 'conflict', 'conflict'];
    await act(async () => {
      await hook.result.current.requestHelp();
    });
    expect(backend.helpCalls).toHaveLength(2);
    expect(hook.result.current.errorMessage).not.toBeNull();
    expect(hook.result.current.lastUtterance).toBeNull();
    expect(backend.tutorMarks).toBe(0);
  });

  it('shows a provider outage honestly and uses a new command next time', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['unavailable'];
    await act(async () => {
      await hook.result.current.requestHelp();
    });
    expect(hook.result.current.errorMessage).toMatch(/not ready/);
    expect(hook.result.current.lastUtterance).toBeNull();

    await act(async () => {
      await hook.result.current.requestHelp();
    });
    expect(backend.helpCalls[1].key).not.toBe(backend.helpCalls[0].key);
    expect(hook.result.current.lastUtterance).toMatch(/start smaller/);
  });

  it('reports a rejected help turn as unchanged work and renders no tutor effects', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['rejected'];
    await act(async () => {
      await hook.result.current.requestHelp();
    });
    expect(hook.result.current.errorMessage).toMatch(/could not use that turn/);
    expect(hook.result.current.lastUtterance).toBeNull();
    expect(hook.result.current.lastTurn).toBeNull();
  });

  it('discards a help response that arrives after the session changed', async () => {
    const { backend, fetchImpl } = makeBackend('s1');
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['hold'];
    let pending: Promise<void> | undefined;
    await act(async () => {
      pending = hook.result.current.requestHelp();
      await Promise.resolve();
    });
    hook.rerender({ sessionId: 's2' });
    await act(async () => {
      backend.held?.();
      await pending;
    });
    expect(hook.result.current.lastUtterance).toBeNull();
    expect(hook.result.current.lastTurn).toBeNull();
  });
});
