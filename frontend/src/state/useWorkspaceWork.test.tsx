/**
 * Typed work through the real ApiClient against a transport double that mirrors the server's
 * idempotency/revision rules (work is recorded when the key is first reserved; a replayed key
 * returns the stored outcome; a stale expected revision is a definite 409). The authoritative
 * semantics live in the backend suite; these tests pin the client's command identity: an
 * uncertain failure keeps one key and body, a definite outcome ends it, and a changed problem
 * or session never inherits an old command.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { act, renderHook, waitFor } from '@testing-library/react-native';

import { ApiClient } from '../api/client';
import { METHOD_SLIP_TURN } from '../testing/teachingFixtures';

import { useWorkspace } from './useWorkspace';

type WorkMode = 'conflict' | 'drop_before' | 'drop_after' | 'invalid' | 'rejected' | 'hold';

type WorkCall = { key: string; body: Record<string, unknown> };

function makeBackend(sessionId = 's1') {
  const backend = {
    revision: 1,
    epoch: 0,
    attemptId: 'attempt-1',
    pending: null as string | null,
    effects: 0,
    modes: [] as WorkMode[],
    calls: [] as WorkCall[],
    helpCalls: 0,
    interruptCalls: 0,
    stored: new Map<string, unknown>(),
    held: null as null | (() => void),
  };
  const respond = (status: number, body: unknown) =>
    ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;
  const error = (status: number, code: string, message = code) =>
    respond(status, { schema_version: 'error.v1', error: { code, message } });

  const turnFor = (status: 'committed' | 'rejected' | 'superseded', index: number) => ({
    ...METHOD_SLIP_TURN,
    turn_id: `turn-${index}`,
    status,
    base_revision: index,
    session_revision: index + 1,
    cancellation_epoch: backend.epoch,
    utterance: status === 'committed' ? `Reply ${index}` : null,
    expected_student_action: status === 'committed' ? 'Try the next step.' : null,
    rejections: status === 'superseded' ? [{ code: 'interrupted', message: 'stopped' }] : [],
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
          cancellation_epoch: backend.epoch,
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
        pending_turn_id: backend.pending,
        session_context_recheck: false,
        persona: null,
      });
    }
    if (url.endsWith(`/sessions/${sessionId}/scene`)) {
      return respond(200, {
        schema_version: 'scene-snapshot.v1',
        session_id: sessionId,
        scene_revision: 1,
        board_width: 1600,
        board_height: 1200,
        pen_width: 3,
        objects: [],
        student_undo_available: false,
        student_redo_available: false,
        tutor_move_undo_available: false,
      });
    }
    if (url.endsWith(`/sessions/${sessionId}/help`) && method === 'POST') {
      backend.helpCalls += 1;
      return error(500, 'unexpected', 'help must not be used for typed work');
    }
    if (url.endsWith(`/sessions/${sessionId}/interrupt`) && method === 'POST') {
      backend.interruptCalls += 1;
      const stopped = backend.pending === null ? [] : [backend.pending];
      backend.pending = null;
      backend.epoch += 1;
      return respond(200, {
        schema_version: 'interrupt-result.v1',
        session_id: sessionId,
        cancellation_epoch: backend.epoch,
        session_revision: backend.revision,
        interrupted_turn_ids: stopped,
        replayed: false,
      });
    }
    if (url.endsWith(`/sessions/${sessionId}/work`) && method === 'POST') {
      const headers = init?.headers as Record<string, string>;
      const key = headers['Idempotency-Key'];
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      backend.calls.push({ key, body });
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
      if (mode === 'invalid') return error(422, 'validation_error', 'That step could not be read.');
      const index = backend.revision;
      backend.revision += 1;
      backend.effects += 1;
      backend.pending = `turn-${index}`;
      if (mode === 'hold') {
        await new Promise<void>((resolve) => {
          backend.held = resolve;
        });
        const late = backend.pending === null ? 'superseded' : 'committed';
        backend.pending = null;
        return respond(200, turnFor(late, index));
      }
      backend.pending = null;
      const result = turnFor(mode === 'rejected' ? 'rejected' : 'committed', index);
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

describe('useWorkspace submitWork', () => {
  it('a normal send is one /work command with the typed text and the current revision', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);

    let outcome: string | undefined;
    await act(async () => {
      outcome = await hook.result.current.submitWork('  2x + 6 = 14  ');
    });

    expect(outcome).toBe('resolved');
    expect(backend.helpCalls).toBe(0);
    expect(backend.calls).toHaveLength(1);
    expect(backend.calls[0].body).toEqual({
      schema_version: 'work-request.v1',
      expected_revision: 1,
      text: '2x + 6 = 14',
      input_mode: 'typed',
    });
    expect(hook.result.current.lastUtterance).toBe('Reply 1');
    expect(backend.effects).toBe(1);
  });

  it('a failure before the server received it keeps the work retryable with the SAME key and body', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['drop_before'];

    let first: string | undefined;
    await act(async () => {
      first = await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(first).toBe('retained');
    expect(hook.result.current.errorMessage).toMatch(/kept|not be counted twice/i);
    expect(hook.result.current.lastUtterance).toBeNull();
    expect(backend.effects).toBe(0);

    let second: string | undefined;
    await act(async () => {
      second = await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(second).toBe('resolved');
    expect(backend.calls).toHaveLength(2);
    expect(backend.calls[1]).toEqual(backend.calls[0]);
    expect(backend.effects).toBe(1);
    expect(hook.result.current.lastUtterance).toBe('Reply 1');
    expect(hook.result.current.errorMessage).toBeNull();
  });

  it('a lost acknowledgement replays the stored outcome: one effect, never a second turn', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['drop_after'];

    let first: string | undefined;
    await act(async () => {
      first = await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(first).toBe('retained');
    expect(backend.effects).toBe(1);
    expect(backend.revision).toBe(2);

    let second: string | undefined;
    await act(async () => {
      second = await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(second).toBe('resolved');
    expect(backend.calls).toHaveLength(2);
    expect(backend.calls[1]).toEqual(backend.calls[0]);
    expect(backend.effects).toBe(1);
    expect(backend.revision).toBe(2);
    expect(hook.result.current.lastTurn?.replayed).toBe(true);
    expect(hook.result.current.state?.session.revision).toBe(2);
  });

  it('a lost acknowledgement then an edited step is a new command, not a body change under the old key', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['drop_before'];
    await act(async () => {
      await hook.result.current.submitWork('2x + 6 = 14');
    });

    await act(async () => {
      await hook.result.current.submitWork('2x + 6 = 14, so x = 4');
    });
    expect(backend.calls).toHaveLength(2);
    expect(backend.calls[1].key).not.toBe(backend.calls[0].key);
    expect(backend.calls[1].body.text).toBe('2x + 6 = 14, so x = 4');
    expect(backend.effects).toBe(1);
  });

  it('a definite rejection is not retried blindly and the next send is a new command', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['invalid'];

    let first: string | undefined;
    await act(async () => {
      first = await hook.result.current.submitWork('???');
    });
    expect(first).toBe('retained');
    expect(hook.result.current.errorMessage).toMatch(/could not be read/);
    expect(backend.effects).toBe(0);

    await act(async () => {
      await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(backend.calls[1].key).not.toBe(backend.calls[0].key);
    expect(backend.effects).toBe(1);
  });

  it('a rejected tutor turn is an authoritative outcome for the work (the work is recorded)', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['rejected'];

    let outcome: string | undefined;
    await act(async () => {
      outcome = await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(outcome).toBe('resolved');
    expect(hook.result.current.errorMessage).toMatch(/could not use that turn/);
    expect(hook.result.current.lastTurn).toBeNull();
    expect(backend.effects).toBe(1);
  });

  it('a revision conflict on the same problem resyncs and sends exactly one fresh command', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.revision = 3;

    let outcome: string | undefined;
    await act(async () => {
      outcome = await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(outcome).toBe('resolved');
    expect(backend.calls).toHaveLength(2);
    expect(backend.calls[0].body.expected_revision).toBe(1);
    expect(backend.calls[1].body.expected_revision).toBe(3);
    expect(backend.calls[1].key).not.toBe(backend.calls[0].key);
    expect(backend.effects).toBe(1);
  });

  it('a conflict after the problem changed resyncs but never applies the stale work', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.revision = 5;
    backend.attemptId = 'attempt-2';

    let outcome: string | undefined;
    await act(async () => {
      outcome = await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(outcome).toBe('stale');
    expect(backend.calls).toHaveLength(1);
    expect(backend.effects).toBe(0);
    expect(hook.result.current.state?.current_problem?.attempt_id).toBe('attempt-2');
    expect(hook.result.current.errorMessage).toMatch(/problem changed/i);
  });

  it('never replays an uncertain command onto a new problem', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['drop_before'];
    await act(async () => {
      await hook.result.current.submitWork('2x + 6 = 14');
    });

    // The learner's problem moves on while the command is still uncertain.
    backend.attemptId = 'attempt-2';
    await act(async () => {
      await hook.result.current.retryPending();
    });

    let outcome: string | undefined;
    await act(async () => {
      outcome = await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(outcome).toBe('stale');
    expect(backend.calls).toHaveLength(1);
    expect(hook.result.current.errorMessage).toMatch(/problem changed/i);

    // Only a fresh, explicit send for the current problem goes out, under a new key.
    await act(async () => {
      outcome = await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(outcome).toBe('resolved');
    expect(backend.calls).toHaveLength(2);
    expect(backend.calls[1].key).not.toBe(backend.calls[0].key);
  });

  it('discards a response that arrives after the session changed and reports it stale', async () => {
    const { backend, fetchImpl } = makeBackend('s1');
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['hold'];
    let pending: Promise<string> | undefined;
    await act(async () => {
      pending = hook.result.current.submitWork('2x + 6 = 14');
      await Promise.resolve();
    });
    hook.rerender({ sessionId: 's2' });
    let outcome: string | undefined;
    await act(async () => {
      backend.held?.();
      outcome = await pending;
    });
    expect(outcome).toBe('stale');
    expect(hook.result.current.lastUtterance).toBeNull();
    expect(hook.result.current.lastTurn).toBeNull();
  });

  it('Stop ends the command: the work is saved, the late reply is ignored and the next send is new', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['hold'];

    let pending: Promise<string> | undefined;
    await act(async () => {
      pending = hook.result.current.submitWork('2x + 6 = 14');
      await Promise.resolve();
    });
    await waitFor(() => expect(hook.result.current.canInterrupt).toBe(true));
    await act(async () => {
      await hook.result.current.interrupt();
    });
    expect(backend.interruptCalls).toBe(1);

    let outcome: string | undefined;
    await act(async () => {
      backend.held?.();
      outcome = await pending;
    });
    expect(outcome).toBe('resolved');
    expect(hook.result.current.lastUtterance).toBeNull();

    await act(async () => {
      await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(backend.calls).toHaveLength(2);
    expect(backend.calls[1].key).not.toBe(backend.calls[0].key);
    expect(backend.calls[1].body.expected_revision).toBe(2);
    expect(hook.result.current.lastUtterance).toBe('Reply 2');
  });

  it('ignores a send while another command is running', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.modes = ['hold'];
    let pending: Promise<string> | undefined;
    await act(async () => {
      pending = hook.result.current.submitWork('2x + 6 = 14');
      await Promise.resolve();
    });
    let second: string | undefined;
    await act(async () => {
      second = await hook.result.current.submitWork('another');
    });
    expect(second).toBe('ignored');
    expect(backend.calls).toHaveLength(1);
    await act(async () => {
      backend.held?.();
      await pending;
    });
  });
});
