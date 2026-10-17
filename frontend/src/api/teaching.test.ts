/**
 * Adaptive-teaching wire contracts and the help/wait routes. Fixtures mirror the real
 * backend payloads (tutor-turn-result.v1, wait-state.v1, wait-preference.v1).
 */

import {
  tutorTurnResultSchema,
  waitPreferenceSchema,
  waitStateSchema,
} from './contracts';
import { METHOD_SLIP_TURN, WAIT_PREFERENCE, WAIT_STATE } from '../testing/teachingFixtures';
import { ApiClient, ApiClientError } from './client';

describe('adaptive teaching contracts', () => {
  it('decodes verifier, reasoning, eligibility, hypothesis and representation fields', () => {
    const turn = tutorTurnResultSchema.parse(METHOD_SLIP_TURN);
    expect(turn.student_input?.verification?.status).toBe('valid');
    expect(turn.student_input?.reasoning_assessment?.judgment_scope).toBe('pedagogical');
    expect(turn.student_input?.eligibility[0].reason).toBe('independent_reasoning_missing');
    expect(turn.hypothesis?.alternatives).toEqual(['A copying slip rather than a method gap']);
    expect(turn.hypothesis?.contradicting_source_ids).toEqual(['obs-0']);
    expect(turn.representation).toBe('outside_factor');
    expect(turn.support_change).toBe('none');
    expect(turn.decision_justification).toMatch(/skips a term/);
  });

  it('tolerates a turn with no teaching metadata but rejects an unknown representation', () => {
    const bare = { ...METHOD_SLIP_TURN } as Record<string, unknown>;
    delete bare.hypothesis;
    delete bare.representation;
    delete bare.support_change;
    delete bare.decision_justification;
    const parsed = tutorTurnResultSchema.parse(bare);
    expect(parsed.hypothesis).toBeNull();
    expect(parsed.representation).toBeNull();
    expect(parsed.support_change).toBe('none');
    expect(() =>
      tutorTurnResultSchema.parse({ ...METHOD_SLIP_TURN, representation: 'confetti' }),
    ).toThrow();
  });

  it('decodes wait state and refuses a proactive prompt', () => {
    expect(waitStateSchema.parse(WAIT_STATE).quiet_hint_available).toBe(false);
    expect(() => waitStateSchema.parse({ ...WAIT_STATE, proactive_prompt: 'check_in' })).toThrow();
    expect(waitPreferenceSchema.parse(WAIT_PREFERENCE).max_seconds).toBe(300);
  });
});

type Call = { method: string; url: string; headers: Record<string, string>; body: unknown };

function recordingClient(responses: Record<string, { status: number; body: unknown }>) {
  const calls: Call[] = [];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({
      method: init?.method ?? 'GET',
      url,
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
    });
    const hit = Object.entries(responses).find(([suffix]) => url.endsWith(suffix));
    const response = hit?.[1] ?? { status: 404, body: null };
    return { ok: response.status < 300, status: response.status, json: async () => response.body } as Response;
  }) as typeof fetch;
  return { calls, client: new ApiClient('http://tutor.test', 'tok', fetchImpl) };
}

describe('help and wait routes', () => {
  it('posts Help me to /help with expected_revision, mode and the Idempotency-Key', async () => {
    const { calls, client } = recordingClient({
      '/sessions/s1/help': { status: 200, body: { ...METHOD_SLIP_TURN, kind: 'work' } },
    });
    const result = await client.requestHelp('s1', 'help-key-0001', 3, 'hint');
    expect(result.kind).toBe('work');
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe('POST');
    expect(calls[0].url).toBe('http://tutor.test/sessions/s1/help');
    expect(calls[0].headers['Idempotency-Key']).toBe('help-key-0001');
    expect(calls[0].headers.Authorization).toBe('Bearer tok');
    expect(calls[0].body).toEqual({
      schema_version: 'help-request.v1',
      expected_revision: 3,
      mode: 'hint',
    });
  });

  it('reads and writes the bounded wait preference', async () => {
    const { calls, client } = recordingClient({
      '/me/wait-preference': { status: 200, body: WAIT_PREFERENCE },
    });
    expect((await client.waitPreference()).default_seconds).toBe(45);
    await client.putWaitPreference(90);
    expect(calls[1].method).toBe('PUT');
    expect(calls[1].body).toEqual({ schema_version: 'wait-preference-request.v1', wait_seconds: 90 });
  });

  it('Still thinking posts with no body, revision or idempotency header', async () => {
    const { calls, client } = recordingClient({
      '/sessions/s1/still-thinking': { status: 200, body: WAIT_STATE },
      '/sessions/s1/wait': { status: 200, body: WAIT_STATE },
    });
    await client.stillThinking('s1');
    await client.waitState('s1');
    expect(calls[0].method).toBe('POST');
    expect(calls[0].body).toBeUndefined();
    expect(calls[0].headers['Idempotency-Key']).toBeUndefined();
    expect(calls[1].method).toBe('GET');
  });

  it('surfaces the server error code for an ended session', async () => {
    const { client } = recordingClient({
      '/sessions/s1/still-thinking': {
        status: 409,
        body: { schema_version: 'error.v1', error: { code: 'session_not_active', message: 'ended' } },
      },
    });
    await expect(client.stillThinking('s1')).rejects.toMatchObject({
      status: 409,
      code: 'session_not_active',
    });
    await expect(client.stillThinking('s1')).rejects.toBeInstanceOf(ApiClientError);
  });
});
