/**
 * Stop reply through the real ApiClient against a transport double. The authoritative
 * cancellation semantics are covered by the backend race suite; these tests pin what the
 * client does: it names the epoch it observed, ignores the stopped turn's late response and
 * callbacks, keeps the learner's work, and still accepts the next current turn.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { act, renderHook, waitFor } from '@testing-library/react-native';

import { ApiClient } from '../api/client';
import { METHOD_SLIP_TURN } from '../testing/teachingFixtures';

import { useWorkspace } from './useWorkspace';

type InterruptMode = 'ok' | 'drop';

function makeBackend() {
  const backend = {
    revision: 1,
    epoch: 0,
    pending: null as string | null,
    interruptMode: 'ok' as InterruptMode,
    interruptCalls: [] as Record<string, unknown>[],
    workCalls: 0,
    hold: null as null | ((status: 'committed' | 'superseded') => void),
    holdNext: true,
  };
  const respond = (status: number, body: unknown) =>
    ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;
  const turn = (status: 'committed' | 'superseded', index: number) => ({
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
    if (url.endsWith('/sessions/s1/state')) {
      return respond(200, {
        schema_version: 'session-state.v1',
        session: {
          schema_version: 'session.v1',
          id: 's1',
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
          attempt_id: 'attempt-1',
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
    if (url.endsWith('/sessions/s1/scene')) {
      return respond(200, {
        schema_version: 'scene-snapshot.v1',
        session_id: 's1',
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
    if (url.endsWith('/sessions/s1/work') && method === 'POST') {
      backend.workCalls += 1;
      const index = backend.revision;
      backend.revision += 1;
      backend.pending = `turn-${index}`;
      if (backend.holdNext) {
        backend.holdNext = false;
        const outcome = await new Promise<'committed' | 'superseded'>((resolve) => {
          backend.hold = resolve;
        });
        // A late provider response is what a stopped request eventually returns.
        return respond(200, turn(outcome, index));
      }
      backend.pending = null;
      return respond(200, turn('committed', index));
    }
    if (url.endsWith('/sessions/s1/interrupt') && method === 'POST') {
      backend.interruptCalls.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      if (backend.interruptMode === 'drop') throw new TypeError('Network request failed');
      backend.epoch += 1;
      const stopped = backend.pending === null ? [] : [backend.pending];
      backend.pending = null;
      return respond(200, {
        schema_version: 'interrupt-result.v1',
        session_id: 's1',
        cancellation_epoch: backend.epoch,
        session_revision: backend.revision,
        interrupted_turn_ids: stopped,
        replayed: false,
      });
    }
    if (url.endsWith('/health/model')) {
      return respond(404, { schema_version: 'error.v1', error: { code: 'not_found', message: 'x' } });
    }
    return respond(404, { schema_version: 'error.v1', error: { code: 'not_found', message: url } });
  }) as typeof fetch;

  return { backend, fetchImpl };
}

async function renderWorkspace(fetchImpl: typeof fetch) {
  const client = new ApiClient('http://tutor.test', 'token', fetchImpl);
  const hook = renderHook(() => useWorkspace(client, 's1'));
  await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
  return hook;
}

beforeEach(async () => {
  await AsyncStorage.clear();
});

async function startHeldTurn(hook: Awaited<ReturnType<typeof renderWorkspace>>) {
  let pending: Promise<unknown> | undefined;
  await act(async () => {
    pending = hook.result.current.submitWork('2x + 3 = 14');
    await Promise.resolve();
  });
  await waitFor(() => expect(hook.result.current.canInterrupt).toBe(true));
  return { done: pending as Promise<unknown> };
}

describe('useWorkspace interrupt', () => {
  it('stops a pending reply, frees the board, and ignores the stopped turn\'s late response', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    const { done: inflight } = await startHeldTurn(hook);
    expect(hook.result.current.busyLabel).toBe('Thinking…');

    await act(async () => {
      await hook.result.current.interrupt();
    });
    expect(backend.interruptCalls).toEqual([
      { schema_version: 'interrupt-request.v1', observed_epoch: 0, reason: 'student_interrupt' },
    ]);
    expect(hook.result.current.canInterrupt).toBe(false);
    expect(hook.result.current.busyLabel).toBeNull();
    expect(hook.result.current.errorMessage).toMatch(/Stopped.*work is saved/);
    expect(hook.result.current.state?.session.cancellation_epoch).toBe(1);

    // The stopped request returns late, even claiming it committed: nothing is applied.
    await act(async () => {
      backend.hold?.('committed');
      await inflight;
    });
    expect(hook.result.current.lastUtterance).toBeNull();
    expect(hook.result.current.lastTurn).toBeNull();
    expect(hook.result.current.busyLabel).toBeNull();
  });

  it('accepts the next current turn after a stop and does not let the old request release its lock', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    const { done: inflight } = await startHeldTurn(hook);
    await act(async () => {
      await hook.result.current.interrupt();
    });
    await act(async () => {
      await hook.result.current.submitWork('2x + 6 = 14');
    });
    expect(backend.workCalls).toBe(2);
    expect(hook.result.current.lastUtterance).toBe('Reply 2');
    await act(async () => {
      backend.hold?.('committed');
      await inflight;
    });
    // The late answer to the stopped turn does not overwrite the current one.
    expect(hook.result.current.lastUtterance).toBe('Reply 2');
  });

  it('shows a superseded reply as stopped, never as a tutor message', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    const { done: inflight } = await startHeldTurn(hook);
    await act(async () => {
      backend.hold?.('superseded');
      await inflight;
    });
    expect(hook.result.current.lastUtterance).toBeNull();
    expect(hook.result.current.errorMessage).toMatch(/Stopped/);
    expect(hook.result.current.busyLabel).toBeNull();
  });

  it('keeps waiting when the stop request itself cannot reach the server', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    const { done: inflight } = await startHeldTurn(hook);
    backend.interruptMode = 'drop';
    await act(async () => {
      await hook.result.current.interrupt();
    });
    expect(hook.result.current.errorMessage).toMatch(/Could not reach the tutor to stop/);
    expect(hook.result.current.canInterrupt).toBe(true);
    // The server never stopped it, so its real reply still lands.
    await act(async () => {
      backend.hold?.('committed');
      await inflight;
    });
    expect(hook.result.current.lastUtterance).toBe('Reply 1');
  });

  it('does nothing when the server has no pending reply to stop', async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    const { done: inflight } = await startHeldTurn(hook);
    backend.pending = null;
    await act(async () => {
      await hook.result.current.interrupt();
    });
    expect(backend.interruptCalls).toHaveLength(0);
    await act(async () => {
      backend.hold?.('committed');
      await inflight;
    });
    expect(hook.result.current.lastUtterance).toBe('Reply 1');
  });
});
