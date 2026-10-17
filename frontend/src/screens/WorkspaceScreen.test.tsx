/**
 * WorkspaceScreen journey controls, driven through the REAL ApiClient with a fake fetch
 * transport that records every request. These tests pin two honesty rules:
 *
 * - "Still thinking" is a local acknowledgement ONLY: it never submits work, checks in,
 *   or mutates the scene, and it leaves the draft, problem and board untouched.
 * - The tutor's provider identity is shown honestly (the mock says it is a mock), and
 *   "Finish for today" really ends the session and hands control back to the app.
 */

import { fireEvent, render, waitFor } from '@testing-library/react-native';
import React from 'react';

import { ApiClient } from '../api/client';
import type { TutorConfiguration } from '../api/contracts';

import { WorkspaceScreen } from './WorkspaceScreen';

const SESSION_ID = 's1';

const PERSONA: TutorConfiguration = {
  schema_version: 'tutor-configuration.v1',
  id: 'cfg-1',
  learner_id: 'learner-1',
  appearance: 'animal',
  personality: 'gentle',
  comfort_override: 'none',
  chosen_at: '2026-10-17T00:00:00.000Z',
  last_changed_at: '2026-10-17T00:00:00.000Z',
};

const READINESS = {
  schema_version: 'model-readiness.v1',
  provider: 'mock',
  state: 'ready',
  ready: true,
  is_mock: true,
  label: 'Deterministic mock tutor (not a language model)',
  model_id: null,
  model_revision: null,
  detail: 'The demo tutor renders deterministic wording; no language model is involved.',
};

const SESSION = {
  schema_version: 'session.v1',
  id: SESSION_ID,
  learner_id: 'learner-1',
  status: 'active',
  goal: 'solve_equations_with_parentheses',
  revision: 1,
  started_at: '2026-10-17T00:00:00.000Z',
  ended_at: null,
};

const SESSION_STATE = {
  schema_version: 'session-state.v1',
  session: SESSION,
  current_problem: {
    problem_id: 'problem.distribute',
    attempt_id: 'attempt-1',
    statement: '2(x + 3) = 14',
    kind: 'practice',
    concept_id: 'concept.distribution',
    statement_object_id: 'obj-statement',
  },
  pace: 'standard',
  pending_turn_id: null,
  session_context_recheck: false,
  persona: PERSONA,
};

const SCENE = {
  schema_version: 'scene-snapshot.v1',
  session_id: SESSION_ID,
  scene_revision: 1,
  board_width: 1600,
  board_height: 1200,
  pen_width: 3,
  objects: [
    {
      schema_version: 'scene-object.v1',
      id: 'obj-statement',
      learner_id: 'learner-1',
      session_id: SESSION_ID,
      author_role: 'tutor',
      semantic_role: 'problem_statement',
      kind: 'text',
      payload: { text: '2(x + 3) = 14', x: 80, y: 120, color_role: 'tutor' },
      teaching_step_id: null,
      created_at: '2026-10-17T00:00:00.000Z',
      deleted_at: null,
    },
  ],
  student_undo_available: false,
  student_redo_available: false,
  tutor_move_undo_available: false,
};

type RecordedRequest = { method: string; url: string; body: unknown };

function makeFakeApi() {
  const requests: RecordedRequest[] = [];
  const control = { failState: false };
  const respond = (status: number, body: unknown) =>
    ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    requests.push({
      method,
      url,
      body: init?.body !== undefined ? JSON.parse(String(init.body)) : undefined,
    });
    if (url.endsWith(`/sessions/${SESSION_ID}/state`)) {
      if (control.failState) {
        return respond(500, {
          schema_version: 'error.v1',
          error: { code: 'boom', message: 'Database unavailable' },
        });
      }
      return respond(200, SESSION_STATE);
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/scene`)) {
      return respond(200, SCENE);
    }
    if (url.endsWith('/health/model')) {
      return respond(200, READINESS);
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/end`) && method === 'POST') {
      return respond(200, { ...SESSION, status: 'ended', ended_at: '2026-10-17T01:00:00.000Z' });
    }
    return respond(404, {
      schema_version: 'error.v1',
      error: { code: 'not_found', message: url },
    });
  }) as typeof fetch;
  return { requests, control, fetchImpl };
}

function renderWorkspace(fetchImpl: typeof fetch, onSessionEnded = jest.fn()) {
  const client = new ApiClient('http://tutor.test', 'token', fetchImpl);
  const screen = render(
    <WorkspaceScreen
      client={client}
      sessionId={SESSION_ID}
      persona={PERSONA}
      displayName="Riley"
      onSessionEnded={onSessionEnded}
    />,
  );
  return { ...screen, onSessionEnded };
}

/** Every tutor/board mutation call the client made (plain GET reads are always allowed). */
function mutatingRequests(requests: readonly RecordedRequest[]): RecordedRequest[] {
  return requests.filter((request) => request.method !== 'GET');
}

describe('WorkspaceScreen', () => {
  it('Still thinking only acknowledges locally: no work, check-in or scene mutation', async () => {
    const { requests, fetchImpl } = makeFakeApi();
    const screen = renderWorkspace(fetchImpl);
    await waitFor(() => expect(screen.getByTestId('prompt-problem')).toBeTruthy());
    expect(screen.getByTestId('prompt-problem').props.children).toBe('2(x + 3) = 14');

    // The learner has an unfinished typed draft and taps Still thinking twice.
    fireEvent.changeText(screen.getByTestId('typed-step-input'), '2x +');
    fireEvent.press(screen.getByTestId('still-thinking'));
    fireEvent.press(screen.getByTestId('still-thinking'));

    // A local, honest acknowledgement appears.
    expect(screen.getByTestId('prompt-status').props.children).toBe(
      'Take your time — your tutor will wait.',
    );
    // Nothing was submitted, checked in, or drawn: zero mutating calls ever happened.
    expect(mutatingRequests(requests)).toEqual([]);
    // The draft, the posed problem and the board are exactly as before.
    expect(screen.getByTestId('typed-step-input').props.value).toBe('2x +');
    expect(screen.getByTestId('prompt-problem').props.children).toBe('2(x + 3) = 14');
    expect(screen.getByTestId('whiteboard').props.accessibilityLabel).toBe(
      'Whiteboard: 0 of your marks, 1 tutor marks',
    );
  });

  it('labels the tutor provider honestly, straight from the service', async () => {
    const { fetchImpl } = makeFakeApi();
    const screen = renderWorkspace(fetchImpl);
    await waitFor(() =>
      expect(screen.getByText(/Deterministic mock tutor \(not a language model\)/)).toBeTruthy(),
    );
    const chip = screen.getByTestId('provider-label');
    expect(chip.props.accessibilityLabel).toMatch(/mock/i);
  });

  it('Finish for today really ends the session and hands back to the app', async () => {
    const { requests, fetchImpl } = makeFakeApi();
    const onSessionEnded = jest.fn();
    const screen = renderWorkspace(fetchImpl, onSessionEnded);
    await waitFor(() => expect(screen.getByTestId('prompt-problem')).toBeTruthy());

    fireEvent.press(screen.getByTestId('finish-session'));
    await waitFor(() => expect(onSessionEnded).toHaveBeenCalledTimes(1));
    const endCalls = requests.filter(
      (request) => request.method === 'POST' && request.url.endsWith(`/sessions/${SESSION_ID}/end`),
    );
    expect(endCalls).toHaveLength(1);
  });

  it('explains loading and a recoverable load failure honestly', async () => {
    const { control, fetchImpl } = makeFakeApi();
    control.failState = true;
    const screen = renderWorkspace(fetchImpl);
    // The loading state is shown first.
    expect(screen.getByText(/Setting up your board/)).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/board could not load/i)).toBeTruthy());
    expect(screen.getByText(/Database unavailable/)).toBeTruthy();

    control.failState = false;
    fireEvent.press(screen.getByTestId('workspace-retry'));
    await waitFor(() => expect(screen.getByTestId('prompt-problem')).toBeTruthy());
    expect(screen.getByTestId('prompt-problem').props.children).toBe('2(x + 3) = 14');
  });
});
