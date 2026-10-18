/**
 * Typed API client for the Rubberducky backend.
 *
 * Every call validates the response against its zod contract and decodes the backend's
 * error envelope into an ApiClientError carrying the server error code, so the workspace
 * can resync on `revision_conflict` instead of guessing.
 */

import { z } from "zod";

import {
  accessibilityPreferencesSchema,
  correctionReceiptSchema,
  deletionReceiptSchema,
  errorEnvelopeSchema,
  interruptResultSchema,
  knowledgeMapSchema,
  mediaCapabilitiesSchema,
  mediaEventResultSchema,
  memoryInspectionSchema,
  meResponseSchema,
  pairingResultSchema,
  personaOptionsSchema,
  personaStateSchema,
  removalReceiptSchema,
  sceneOperationResultSchema,
  sceneSnapshotSchema,
  sessionListSchema,
  sessionSchema,
  sessionStateSchema,
  tutorTurnResultSchema,
  voiceTurnSchema,
  waitPreferenceSchema,
  waitStateSchema,
  type AccessibilityPatch,
  type HandholdMode,
  type LearnerControl,
  type AccessibilityPreferences,
  type Appearance,
  type ComfortOverride,
  type CorrectionReceipt,
  type DeletionReceipt,
  type InterruptResult,
  type MediaCapabilities,
  type MediaEventRequest,
  type MediaEventResult,
  type KnowledgeMap,
  type MemoryInspection,
  type MeResponse,
  type PairingResult,
  type PersonaOptions,
  type PersonaState,
  type Personality,
  type RemovalReceipt,
  type SceneOperationResult,
  type SceneSnapshot,
  type Session,
  type SessionState,
  type TutorTurnResult,
  type VoiceTurnResult,
  type WaitPreference,
  type WaitState,
} from "./contracts";
import type { LogicalPoint } from "../board/geometry";
import { modelReadinessSchema, type ModelReadiness } from "./health";

export class ApiClientError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

export type SceneActionRequest =
  | { op: "add_stroke"; points: LogicalPoint[] }
  | { op: "erase_object"; target_object_id: string }
  | { op: "undo" }
  | { op: "redo" }
  | { op: "undo_tutor_move" };

const REQUEST_TIMEOUT_MS = 15000;
const TUTOR_TURN_TIMEOUT_MS = 90000;

export type QuestionImage = {
  mediaType: "image/png" | "image/jpeg" | "image/webp";
  base64: string;
};

export type CheckInInput = {
  energy: "ready" | "a_bit_tired" | "tired" | null;
  questionText?: string;
  image?: QuestionImage | null;
  practice?: boolean;
  calculus?: boolean;
  handhold?: HandholdMode;
};

function handholdBody(
  handhold?: HandholdMode,
  learnerControl?: LearnerControl,
): { handhold?: HandholdMode; learner_control?: LearnerControl } {
  return {
    ...(handhold !== undefined && handhold !== "balanced" ? { handhold } : {}),
    ...(learnerControl !== undefined ? { learner_control: learnerControl } : {}),
  };
}

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
    return this.request("POST", "/demo/bootstrap", pairingResultSchema, {
      body: { display_name: displayName },
      authenticated: false,
    });
  }

  me(): Promise<MeResponse> {
    return this.request("GET", "/me", meResponseSchema);
  }

  personaOptions(): Promise<PersonaOptions> {
    return this.request("GET", "/persona/options", personaOptionsSchema);
  }

  /** The stored pair, comfort override and the server's seven-day lock state (all UTC). */
  getTutorConfiguration(): Promise<PersonaState> {
    return this.request("GET", "/me/tutor-configuration", personaStateSchema);
  }

  /**
   * Choose or change the durable appearance/personality pair. Comfort is deliberately not
   * sent: omitting it keeps the current override, and comfort has its own immediate route.
   * A locked change rejects with ApiClientError code `persona_change_locked`.
   */
  putTutorConfiguration(
    appearance: Appearance,
    personality: Personality,
  ): Promise<PersonaState> {
    return this.request("PUT", "/me/tutor-configuration", personaStateSchema, {
      body: {
        schema_version: "tutor-configuration-request.v1",
        appearance,
        personality,
      },
    });
  }

  /** Immediate neutral/supportive or reduced-sass delivery; never cooldown-locked. */
  putComfortOverride(comfortOverride: ComfortOverride): Promise<PersonaState> {
    return this.request("PUT", "/me/comfort-override", personaStateSchema, {
      body: {
        schema_version: "comfort-override-request.v1",
        comfort_override: comfortOverride,
      },
    });
  }

  getAccessibilityPreferences(): Promise<AccessibilityPreferences> {
    return this.request(
      "GET",
      "/me/accessibility-preferences",
      accessibilityPreferencesSchema,
    );
  }

  /** Only the supplied fields change; never locked and never touching the persona pair. */
  patchAccessibilityPreferences(
    patch: AccessibilityPatch,
  ): Promise<AccessibilityPreferences> {
    return this.request(
      "PATCH",
      "/me/accessibility-preferences",
      accessibilityPreferencesSchema,
      {
        body: {
          schema_version: "accessibility-preferences-request.v1",
          ...patch,
        },
      },
    );
  }

  /** The private memory view. `limit` bounds each of the five buckets, not the total. */
  inspectMemory(
    options: { limit?: number; sessionId?: string } = {},
  ): Promise<MemoryInspection> {
    const query = new URLSearchParams();
    if (options.limit !== undefined) query.set("limit", String(options.limit));
    if (options.sessionId !== undefined)
      query.set("session_id", options.sessionId);
    const suffix = query.size > 0 ? `?${query.toString()}` : "";
    return this.request(
      "GET",
      `/memory/inspect${suffix}`,
      memoryInspectionSchema,
    );
  }

  correctEvidence(
    observationId: string,
    correct: boolean,
  ): Promise<CorrectionReceipt> {
    return this.request(
      "POST",
      `/memory/evidence/${encodeURIComponent(observationId)}/correction`,
      correctionReceiptSchema,
      { body: { correct } },
    );
  }

  correctNote(memoryId: string, content: string): Promise<CorrectionReceipt> {
    return this.request(
      "POST",
      `/memory/notes/${encodeURIComponent(memoryId)}/correction`,
      correctionReceiptSchema,
      { body: { content } },
    );
  }

  deleteEvidence(observationId: string): Promise<DeletionReceipt> {
    return this.request(
      "DELETE",
      `/memory/evidence/${encodeURIComponent(observationId)}`,
      deletionReceiptSchema,
    );
  }

  deleteNote(memoryId: string): Promise<DeletionReceipt> {
    return this.request(
      "DELETE",
      `/memory/notes/${encodeURIComponent(memoryId)}`,
      deletionReceiptSchema,
    );
  }

  deleteHypothesis(hypothesisId: string): Promise<DeletionReceipt> {
    return this.request(
      "DELETE",
      `/memory/hypotheses/${encodeURIComponent(hypothesisId)}`,
      deletionReceiptSchema,
    );
  }

  deleteSession(sessionId: string): Promise<RemovalReceipt> {
    return this.request(
      "DELETE",
      `/sessions/${encodeURIComponent(sessionId)}`,
      removalReceiptSchema,
    );
  }

  /** Removes the whole profile and revokes every credential; the confirm token is required. */
  deleteProfile(): Promise<RemovalReceipt> {
    return this.request(
      "DELETE",
      "/me?confirm=delete-my-profile",
      removalReceiptSchema,
    );
  }

  startSession(goal?: string): Promise<Session> {
    return this.request("POST", "/sessions", sessionSchema, {
      body: { goal: goal ?? null },
    });
  }

  listSessions(): Promise<Session[]> {
    return this.request("GET", "/sessions", sessionListSchema);
  }

  sessionState(sessionId: string): Promise<SessionState> {
    return this.request(
      "GET",
      `/sessions/${sessionId}/state`,
      sessionStateSchema,
    );
  }

  sceneSnapshot(sessionId: string): Promise<SceneSnapshot> {
    return this.request(
      "GET",
      `/sessions/${sessionId}/scene`,
      sceneSnapshotSchema,
    );
  }

  endSession(sessionId: string): Promise<Session> {
    return this.request("POST", `/sessions/${sessionId}/end`, sessionSchema);
  }

  /** Committed and in-progress turns, oldest first, for the conversation panel. */
  turnEvents(sessionId: string): Promise<TutorTurnResult[]> {
    return this.request(
      "GET",
      `/sessions/${sessionId}/events?limit=50`,
      z.array(tutorTurnResultSchema),
    );
  }

  /** Shared concept graph with this learner's estimate and memory labels. */
  knowledgeMap(): Promise<KnowledgeMap> {
    return this.request("GET", "/graph/knowledge", knowledgeMapSchema);
  }

  /** Honest provider identity/readiness, so the UI can label a mock as a mock. */
  modelReadiness(): Promise<ModelReadiness> {
    return this.request("GET", "/health/model", modelReadinessSchema);
  }

  commitSceneOperation(
    sessionId: string,
    operationId: string,
    expectedSceneRevision: number,
    action: SceneActionRequest,
  ): Promise<SceneOperationResult> {
    return this.request(
      "POST",
      `/sessions/${sessionId}/scene/operations`,
      sceneOperationResultSchema,
      {
        body: {
          schema_version: "scene-operation-request.v1",
          operation_id: operationId,
          expected_scene_revision: expectedSceneRevision,
          action,
        },
      },
    );
  }

  checkIn(
    sessionId: string,
    idempotencyKey: string,
    expectedRevision: number,
    input: CheckInInput,
  ): Promise<TutorTurnResult> {
    const question = input.questionText?.trim() ?? "";
    const practice = input.practice === true || (question.length === 0 && input.image == null);
    const calculus = input.calculus === true;
    return this.request(
      "POST",
      `/sessions/${sessionId}/check-in`,
      tutorTurnResultSchema,
      {
        body: {
          schema_version: "check-in-request.v1",
          expected_revision: expectedRevision,
          goal: calculus
            ? "practice_calculus"
            : practice
              ? "solve_equations_with_parentheses"
              : "learner_question",
          energy: input.energy,
          question_text: practice || calculus || question.length === 0 ? null : question,
          question_image_media_type:
            practice || calculus ? null : (input.image?.mediaType ?? null),
          question_image_base64: practice || calculus ? null : (input.image?.base64 ?? null),
          use_practice_problem: practice && !calculus,
          ...handholdBody(input.handhold),
        },
        idempotencyKey,
        timeoutMs: TUTOR_TURN_TIMEOUT_MS,
      },
    );
  }

  readBoard(sessionId: string, sceneRevision: number, checkAnswer = false) {
    return this.request("POST", `/sessions/${sessionId}/scene/read`, z.object({
      text: z.string().max(500), legible: z.boolean(), boxed_answer: z.boolean().default(false), scene_revision: z.number().int(),
    }), { body: { scene_revision: sceneRevision, ...(checkAnswer ? { check_answer: true } : {}) }, timeoutMs: 120000 });
  }

  submitWork(
    sessionId: string,
    idempotencyKey: string,
    expectedRevision: number,
    text: string,
    inputMode: "typed" | "confirmed_ink" | "unconfirmed_ink" = "typed",
    handhold?: HandholdMode,
    boxedAnswer = false,
  ): Promise<TutorTurnResult> {
    return this.request(
      "POST",
      `/sessions/${sessionId}/work`,
      tutorTurnResultSchema,
      {
        body: {
          schema_version: "work-request.v1",
          expected_revision: expectedRevision,
          text,
          input_mode: inputMode,
          ...(boxedAnswer ? { boxed_answer: true } : {}),
          ...handholdBody(handhold),
        },
        idempotencyKey,
        timeoutMs: TUTOR_TURN_TIMEOUT_MS,
      },
    );
  }

  /**
   * Hold to talk. The recording stays in this request; the server transcribes it, runs the
   * tutor, and returns audio of the tutor's reply only.
   */
  submitVoice(
    sessionId: string,
    idempotencyKey: string,
    expectedRevision: number,
    observedEpoch: number,
    clip: { bytes: Blob; mime: string },
    options: { handhold?: HandholdMode; speak?: boolean } = {},
  ): Promise<VoiceTurnResult> {
    const form = new FormData();
    form.append("expected_revision", String(expectedRevision));
    form.append("observed_epoch", String(observedEpoch));
    form.append("handhold", options.handhold ?? "balanced");
    form.append("speak", options.speak === false ? "false" : "true");
    form.append("audio", clip.bytes, "clip");
    return this.request("POST", `/sessions/${sessionId}/voice/turn`, voiceTurnSchema, {
      body: form,
      idempotencyKey,
      timeoutMs: 120000,
    });
  }

  /** Help me: a hint (or, on request, an explanation) now. Same turn contract as /work. */
  requestHelp(
    sessionId: string,
    idempotencyKey: string,
    expectedRevision: number,
    mode: "hint" | "explain" = "hint",
    handhold?: HandholdMode,
    learnerControl?: LearnerControl,
  ): Promise<TutorTurnResult> {
    return this.request(
      "POST",
      `/sessions/${sessionId}/help`,
      tutorTurnResultSchema,
      {
        body: {
          schema_version: "help-request.v1",
          expected_revision: expectedRevision,
          mode,
          ...handholdBody(handhold, learnerControl),
        },
        idempotencyKey,
        timeoutMs: 180000,
      },
    );
  }

  /** Stop the reply being prepared. Safe to retry: the epoch advances once per observed value. */
  interruptSession(
    sessionId: string,
    observedEpoch: number,
    reason: "student_interrupt" | "speech_barge_in" = "student_interrupt",
  ): Promise<InterruptResult> {
    return this.request(
      "POST",
      `/sessions/${sessionId}/interrupt`,
      interruptResultSchema,
      {
        body: {
          schema_version: "interrupt-request.v1",
          observed_epoch: observedEpoch,
          reason,
        },
      },
    );
  }

  /** What optional media can and cannot do on this server, with limits and disclosures. */
  mediaCapabilities(): Promise<MediaCapabilities> {
    return this.request("GET", "/media/capabilities", mediaCapabilitiesSchema);
  }

  /**
   * One bounded media event (photo metadata, simulated transcript update, weak cue). The
   * server answers with an uncertain, never-assessed outcome, or 409 when the revision or
   * cancellation epoch is stale. Raw frames and audio are never sent by this client.
   */
  postMediaEvent(
    sessionId: string,
    event: MediaEventRequest,
    scope: { revision: number; epoch: number },
  ): Promise<MediaEventResult> {
    return this.request(
      "POST",
      `/sessions/${sessionId}/media/events`,
      mediaEventResultSchema,
      {
        body: {
          schema_version: "media-event-request.v1",
          expected_revision: scope.revision,
          observed_epoch: scope.epoch,
          ...(event.kind === "image_snapshot"
            ? { trigger: "explicit_capture" }
            : {}),
          ...event,
        },
      },
    );
  }

  waitPreference(): Promise<WaitPreference> {
    return this.request("GET", "/me/wait-preference", waitPreferenceSchema);
  }

  putWaitPreference(waitSeconds: number): Promise<WaitPreference> {
    return this.request("PUT", "/me/wait-preference", waitPreferenceSchema, {
      body: {
        schema_version: "wait-preference-request.v1",
        wait_seconds: waitSeconds,
      },
    });
  }

  waitState(sessionId: string): Promise<WaitState> {
    return this.request("GET", `/sessions/${sessionId}/wait`, waitStateSchema);
  }

  /** Explicit "Still thinking": wait metadata only. Not idempotent, so never auto-replayed. */
  stillThinking(sessionId: string): Promise<WaitState> {
    return this.request(
      "POST",
      `/sessions/${sessionId}/still-thinking`,
      waitStateSchema,
    );
  }

  private async request<T>(
    method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
    path: string,
    schema: { parse: (value: unknown) => T },
    options: {
      body?: unknown;
      idempotencyKey?: string;
      authenticated?: boolean;
      timeoutMs?: number;
    } = {},
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(),
      options.timeoutMs ?? REQUEST_TIMEOUT_MS,
    );
    try {
      const headers: Record<string, string> = { Accept: "application/json" };
      const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
      if (options.body !== undefined && !isForm) {
        headers["Content-Type"] = "application/json";
      }
      if (options.idempotencyKey !== undefined) {
        headers["Idempotency-Key"] = options.idempotencyKey;
      }
      if (options.authenticated !== false && this.accessToken !== null) {
        headers.Authorization = `Bearer ${this.accessToken}`;
      }
      let body: BodyInit | undefined;
      if (options.body instanceof FormData) body = options.body;
      else if (options.body !== undefined) body = JSON.stringify(options.body);
      const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers,
        body,
        signal: controller.signal,
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        const envelope = errorEnvelopeSchema.safeParse(payload);
        if (envelope.success) {
          throw new ApiClientError(
            response.status,
            envelope.data.error.code,
            envelope.data.error.message,
          );
        }
        throw new ApiClientError(
          response.status,
          "http_error",
          `Request failed with status ${response.status}`,
        );
      }
      return schema.parse(payload);
    } finally {
      clearTimeout(timer);
    }
  }
}
