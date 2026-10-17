/**
 * Typed API client for the Rubberducky backend.
 *
 * Every call validates the response against its zod contract and decodes the backend's
 * error envelope into an ApiClientError carrying the server error code, so the workspace
 * can resync on `revision_conflict` instead of guessing.
 */

import {
  errorEnvelopeSchema,
  meResponseSchema,
  pairingResultSchema,
  personaOptionsSchema,
  sceneOperationResultSchema,
  sceneSnapshotSchema,
  sessionListSchema,
  sessionSchema,
  sessionStateSchema,
  tutorConfigurationSchema,
  tutorTurnResultSchema,
  type Appearance,
  type ComfortOverride,
  type MeResponse,
  type PairingResult,
  type PersonaOptions,
  type Personality,
  type SceneOperationResult,
  type SceneSnapshot,
  type Session,
  type SessionState,
  type TutorConfiguration,
  type TutorTurnResult,
} from './contracts';
import type { LogicalPoint } from '../board/geometry';

export class ApiClientError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'ApiClientError';
  }
}

export type SceneActionRequest =
  | { op: 'add_stroke'; points: LogicalPoint[] }
  | { op: 'erase_object'; target_object_id: string }
  | { op: 'undo' }
  | { op: 'redo' }
  | { op: 'undo_tutor_move' };

const REQUEST_TIMEOUT_MS = 15000;

export class ApiClient {
  private readonly fetchImpl: typeof fetch;

  constructor(
    private readonly baseUrl: string,
    private readonly accessToken: string | null = null,
    fetchImpl?: typeof fetch,
  ) {
    // Wrap the global fetch: extracting it bare loses its Window receiver in browsers
    // ("Illegal invocation"), so the default calls it through the global identifier.
    this.fetchImpl = fetchImpl ?? ((input, init) => fetch(input, init));
  }

  withToken(accessToken: string): ApiClient {
    return new ApiClient(this.baseUrl, accessToken, this.fetchImpl);
  }

  bootstrapDemoLearner(displayName: string): Promise<PairingResult> {
    return this.request('POST', '/demo/bootstrap', pairingResultSchema, {
      body: { display_name: displayName },
      authenticated: false,
    });
  }

  me(): Promise<MeResponse> {
    return this.request('GET', '/me', meResponseSchema);
  }

  personaOptions(): Promise<PersonaOptions> {
    return this.request('GET', '/persona/options', personaOptionsSchema);
  }

  putTutorConfiguration(
    appearance: Appearance,
    personality: Personality,
    comfortOverride: ComfortOverride = 'none',
  ): Promise<TutorConfiguration> {
    return this.request('PUT', '/me/tutor-configuration', tutorConfigurationSchema, {
      body: {
        schema_version: 'tutor-configuration-request.v1',
        appearance,
        personality,
        comfort_override: comfortOverride,
      },
    });
  }

  startSession(goal?: string): Promise<Session> {
    return this.request('POST', '/sessions', sessionSchema, { body: { goal: goal ?? null } });
  }

  listSessions(): Promise<Session[]> {
    return this.request('GET', '/sessions', sessionListSchema);
  }

  sessionState(sessionId: string): Promise<SessionState> {
    return this.request('GET', `/sessions/${sessionId}/state`, sessionStateSchema);
  }

  sceneSnapshot(sessionId: string): Promise<SceneSnapshot> {
    return this.request('GET', `/sessions/${sessionId}/scene`, sceneSnapshotSchema);
  }

  commitSceneOperation(
    sessionId: string,
    operationId: string,
    expectedSceneRevision: number,
    action: SceneActionRequest,
  ): Promise<SceneOperationResult> {
    return this.request('POST', `/sessions/${sessionId}/scene/operations`, sceneOperationResultSchema, {
      body: {
        schema_version: 'scene-operation-request.v1',
        operation_id: operationId,
        expected_scene_revision: expectedSceneRevision,
        action,
      },
    });
  }

  checkIn(
    sessionId: string,
    idempotencyKey: string,
    expectedRevision: number,
    energy: 'ready' | 'a_bit_tired' | 'tired' | null,
  ): Promise<TutorTurnResult> {
    return this.request('POST', `/sessions/${sessionId}/check-in`, tutorTurnResultSchema, {
      body: {
        schema_version: 'check-in-request.v1',
        expected_revision: expectedRevision,
        goal: 'solve_equations_with_parentheses',
        energy,
      },
      idempotencyKey,
    });
  }

  submitWork(
    sessionId: string,
    idempotencyKey: string,
    expectedRevision: number,
    text: string,
    inputMode: 'typed' | 'confirmed_ink' | 'unconfirmed_ink' = 'typed',
  ): Promise<TutorTurnResult> {
    return this.request('POST', `/sessions/${sessionId}/work`, tutorTurnResultSchema, {
      body: {
        schema_version: 'work-request.v1',
        expected_revision: expectedRevision,
        text,
        input_mode: inputMode,
      },
      idempotencyKey,
    });
  }

  private async request<T>(
    method: 'GET' | 'POST' | 'PUT',
    path: string,
    schema: { parse: (value: unknown) => T },
    options: { body?: unknown; idempotencyKey?: string; authenticated?: boolean } = {},
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (options.body !== undefined) {
        headers['Content-Type'] = 'application/json';
      }
      if (options.idempotencyKey !== undefined) {
        headers['Idempotency-Key'] = options.idempotencyKey;
      }
      if (options.authenticated !== false && this.accessToken !== null) {
        headers.Authorization = `Bearer ${this.accessToken}`;
      }
      const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        const envelope = errorEnvelopeSchema.safeParse(payload);
        if (envelope.success) {
          throw new ApiClientError(response.status, envelope.data.error.code, envelope.data.error.message);
        }
        throw new ApiClientError(response.status, 'http_error', `Request failed with status ${response.status}`);
      }
      return schema.parse(payload);
    } finally {
      clearTimeout(timer);
    }
  }
}
