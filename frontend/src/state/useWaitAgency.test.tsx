/**
 * Wait agency under a controlled clock. The fake transport records every request, so the
 * tests can prove that idle time creates no work, help, diagnosis or mastery effects: the
 * only POST the hook ever makes is the learner's explicit Still thinking press.
 */

import { act, renderHook } from '@testing-library/react-native';

import { ApiClient } from '../api/client';

import { useWaitAgency } from './useWaitAgency';

type Request = { method: string; url: string; body: unknown };

function iso(ms: number): string {
  return new Date(ms).toISOString();
}

function makeBackend(sessionId = 's1') {
  const requests: Request[] = [];
  const server = {
    nowMs: Date.parse('2026-10-17T10:00:00.000Z'),
    activityMs: Date.parse('2026-10-17T10:00:00.000Z'),
    stillThinkingMs: null as number | null,
    stillThinkingCount: 0,
    waitSeconds: 45,
    source: 'default' as 'default' | 'preference',
    failStillThinking: false,
    sessionEnded: false,
    heldWait: null as null | (() => void),
    holdNextWait: false,
  };
  const waitState = () => {
    const quietFrom = Math.max(server.activityMs, server.stillThinkingMs ?? 0);
    const quietAt = quietFrom + server.waitSeconds * 1000;
    return {
      schema_version: 'wait-state.v1',
      session_id: sessionId,
      now: iso(server.nowMs),
      wait_seconds: server.waitSeconds,
      wait_source: server.source,
      last_activity_at: iso(server.activityMs),
      still_thinking_at: server.stillThinkingMs === null ? null : iso(server.stillThinkingMs),
      still_thinking_count: server.stillThinkingCount,
      quiet_hint_at: iso(quietAt),
      quiet_hint_available: server.nowMs >= quietAt,
      next_hint_level: 1,
      proactive_prompt: 'none',
      silence_interpretation: 'missing_evidence',
    };
  };
  const preference = () => ({
    schema_version: 'wait-preference.v1',
    wait_seconds: server.waitSeconds,
    source: server.source,
    default_seconds: 45,
    min_seconds: 5,
    max_seconds: 300,
    updated_at: null,
  });
  const respond = (status: number, body: unknown) =>
    ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;
  const error = (status: number, code: string) =>
    respond(status, { schema_version: 'error.v1', error: { code, message: code } });

  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    requests.push({
      method,
      url: url.replace('http://tutor.test', ''),
      body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
    });
    if (url.endsWith('/me/wait-preference')) {
      if (method === 'PUT') {
        const body = JSON.parse(String(init?.body)) as { wait_seconds: number };
        server.waitSeconds = body.wait_seconds;
        server.source = 'preference';
      }
      return respond(200, preference());
    }
    if (url.endsWith(`/sessions/${sessionId}/wait`)) {
      if (server.sessionEnded) return error(409, 'session_not_active');
      const snapshot = waitState();
      if (server.holdNextWait) {
        server.holdNextWait = false;
        await new Promise<void>((resolve) => {
          server.heldWait = resolve;
        });
      }
      return respond(200, snapshot);
    }
    if (url.endsWith(`/sessions/${sessionId}/still-thinking`) && method === 'POST') {
      if (server.failStillThinking) throw new TypeError('Network request failed');
      server.stillThinkingMs = server.nowMs;
      server.stillThinkingCount += 1;
      return respond(200, waitState());
    }
    return error(404, 'not_found');
  }) as typeof fetch;

  return {
    requests,
    server,
    client: new ApiClient('http://tutor.test', 'token', fetchImpl),
    /** Move the server clock and the fake timers together. */
    async advance(ms: number) {
      server.nowMs += ms;
      await act(async () => {
        await jest.advanceTimersByTimeAsync(ms);
      });
    },
    posts: () => requests.filter((request) => request.method !== 'GET'),
    reads: () => requests.filter((request) => request.method === 'GET').length,
  };
}

async function flush() {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(0);
  });
}

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
});

describe('useWaitAgency', () => {
  it('does nothing until enabled, then loads the server preference and wait state', async () => {
    const fake = makeBackend();
    const hook = renderHook(
      (props: { enabled: boolean }) =>
        useWaitAgency(fake.client, 's1', { enabled: props.enabled, activityKey: 'a' }),
      { initialProps: { enabled: false } },
    );
    await flush();
    expect(fake.requests).toEqual([]);
    expect(hook.result.current.hintAvailable).toBe(false);

    hook.rerender({ enabled: true });
    await flush();
    expect(hook.result.current.preference).toMatchObject({
      wait_seconds: 45,
      source: 'default',
      min_seconds: 5,
      max_seconds: 300,
    });
    expect(hook.result.current.waitState?.proactive_prompt).toBe('none');
    expect(fake.posts()).toEqual([]);
  });

  it('quietly makes a hint available when the server wait elapses, and does nothing else', async () => {
    const fake = makeBackend();
    const hook = renderHook(() =>
      useWaitAgency(fake.client, 's1', { enabled: true, activityKey: 'a' }),
    );
    await flush();
    const readsAfterLoad = fake.reads();
    expect(hook.result.current.hintAvailable).toBe(false);

    await fake.advance(44_000);
    expect(hook.result.current.hintAvailable).toBe(false);
    await fake.advance(2_000);
    expect(hook.result.current.hintAvailable).toBe(true);

    // Ten more quiet minutes: still no work, help, check-in, still-thinking or polling.
    await fake.advance(600_000);
    expect(fake.posts()).toEqual([]);
    expect(fake.reads()).toBe(readsAfterLoad);
    expect(hook.result.current.hintAvailable).toBe(true);
  });

  it('Still thinking posts only explicit wait metadata, resets the hint and reschedules it', async () => {
    const fake = makeBackend();
    const hook = renderHook(() =>
      useWaitAgency(fake.client, 's1', { enabled: true, activityKey: 'a' }),
    );
    await flush();
    await fake.advance(50_000);
    expect(hook.result.current.hintAvailable).toBe(true);

    await act(async () => {
      await hook.result.current.stillThinking();
    });
    expect(fake.posts()).toEqual([
      { method: 'POST', url: '/sessions/s1/still-thinking', body: undefined },
    ]);
    expect(hook.result.current.stillThinkingStatus).toBe('sent');
    expect(hook.result.current.hintAvailable).toBe(false);
    expect(hook.result.current.waitState?.still_thinking_count).toBe(1);

    await fake.advance(44_000);
    expect(hook.result.current.hintAvailable).toBe(false);
    await fake.advance(2_000);
    expect(hook.result.current.hintAvailable).toBe(true);
    expect(fake.posts()).toHaveLength(1);
  });

  it('a failed Still thinking is reported once and never replayed automatically', async () => {
    const fake = makeBackend();
    fake.server.failStillThinking = true;
    const hook = renderHook(() =>
      useWaitAgency(fake.client, 's1', { enabled: true, activityKey: 'a' }),
    );
    await flush();
    await act(async () => {
      await hook.result.current.stillThinking();
    });
    expect(hook.result.current.stillThinkingStatus).toBe('failed');
    await fake.advance(300_000);
    expect(fake.posts()).toHaveLength(1);

    act(() => hook.result.current.clearStillThinkingNote());
    expect(hook.result.current.stillThinkingStatus).toBe('idle');
  });

  it('saves a clamped preference, then refreshes and reschedules the quiet hint', async () => {
    const fake = makeBackend();
    const hook = renderHook(() =>
      useWaitAgency(fake.client, 's1', { enabled: true, activityKey: 'a' }),
    );
    await flush();

    await act(async () => {
      await hook.result.current.setWaitSeconds(1000);
    });
    const puts = fake.requests.filter((request) => request.method === 'PUT');
    expect(puts).toEqual([
      {
        method: 'PUT',
        url: '/me/wait-preference',
        body: { schema_version: 'wait-preference-request.v1', wait_seconds: 300 },
      },
    ]);
    expect(hook.result.current.preference?.source).toBe('preference');
    expect(hook.result.current.waitState?.wait_seconds).toBe(300);

    await fake.advance(100_000);
    expect(hook.result.current.hintAvailable).toBe(false);

    await act(async () => {
      await hook.result.current.setWaitSeconds(0);
    });
    expect(fake.requests.filter((request) => request.method === 'PUT')[1].body).toEqual({
      schema_version: 'wait-preference-request.v1',
      wait_seconds: 5,
    });
    expect(fake.posts().filter((request) => request.url !== '/me/wait-preference')).toEqual([]);
  });

  it('refreshes after real activity and withdraws the hint without any other request', async () => {
    const fake = makeBackend();
    const hook = renderHook(
      (props: { activityKey: string }) =>
        useWaitAgency(fake.client, 's1', { enabled: true, activityKey: props.activityKey }),
      { initialProps: { activityKey: 'a' } },
    );
    await flush();
    await fake.advance(50_000);
    expect(hook.result.current.hintAvailable).toBe(true);

    fake.server.activityMs = fake.server.nowMs;
    hook.rerender({ activityKey: 'b' });
    await flush();
    expect(hook.result.current.hintAvailable).toBe(false);
    expect(fake.posts()).toEqual([]);
  });

  it('keeps hints unavailable and surfaces nothing alarming when the session already ended', async () => {
    const fake = makeBackend();
    fake.server.sessionEnded = true;
    const hook = renderHook(() =>
      useWaitAgency(fake.client, 's1', { enabled: true, activityKey: 'a' }),
    );
    await flush();
    await fake.advance(120_000);
    expect(hook.result.current.waitState).toBeNull();
    expect(hook.result.current.hintAvailable).toBe(false);
    expect(fake.posts()).toEqual([]);
  });

  it('clears its timer on unmount and discards a response that arrives afterwards', async () => {
    const fake = makeBackend();
    const hook = renderHook(() =>
      useWaitAgency(fake.client, 's1', { enabled: true, activityKey: 'a' }),
    );
    await flush();
    expect(jest.getTimerCount()).toBeGreaterThan(0);
    hook.unmount();
    expect(jest.getTimerCount()).toBe(0);

    const second = makeBackend();
    second.server.holdNextWait = true;
    const late = renderHook(() =>
      useWaitAgency(second.client, 's1', { enabled: true, activityKey: 'a' }),
    );
    await flush();
    late.unmount();
    await act(async () => {
      second.server.heldWait?.();
      await jest.advanceTimersByTimeAsync(0);
    });
    expect(jest.getTimerCount()).toBe(0);
  });

  it('drops a stale response and old timer when the session changes', async () => {
    const fake = makeBackend('s1');
    fake.server.holdNextWait = true;
    const hook = renderHook(
      (props: { sessionId: string }) =>
        useWaitAgency(fake.client, props.sessionId, { enabled: true, activityKey: 'a' }),
      { initialProps: { sessionId: 's1' } },
    );
    await flush();
    hook.rerender({ sessionId: 's2' });
    await flush();
    expect(hook.result.current.waitState).toBeNull();
    await act(async () => {
      fake.server.heldWait?.();
      await jest.advanceTimersByTimeAsync(0);
    });
    // The old session's wait state never lands on the new session.
    expect(hook.result.current.waitState).toBeNull();
    await fake.advance(120_000);
    expect(hook.result.current.hintAvailable).toBe(false);
    expect(fake.posts()).toEqual([]);
  });
});
