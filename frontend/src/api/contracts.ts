/**
 * Zod contracts mirroring the backend's versioned Pydantic schemas.
 *
 * Only the fields the client reads are decoded; unknown server fields are tolerated,
 * while required fields and literals must match so a drifted backend fails loudly.
 */

import { z } from "zod";

export const APPEARANCES = ["animal", "older_adult", "younger_adult"] as const;
export const PERSONALITIES = [
  "gentle",
  "matter_of_fact",
  "playful",
  "mildly_sassy",
] as const;

export const appearanceSchema = z.enum(APPEARANCES);
export const personalitySchema = z.enum(PERSONALITIES);
export const comfortOverrideSchema = z.enum([
  "none",
  "neutral_supportive",
  "reduced_sass",
]);

export type Appearance = z.infer<typeof appearanceSchema>;
export type Personality = z.infer<typeof personalitySchema>;
export type ComfortOverride = z.infer<typeof comfortOverrideSchema>;

export const learnerSchema = z
  .object({
    schema_version: z.literal("learner.v1"),
    id: z.string(),
    display_name: z.string(),
    is_fictional: z.boolean(),
  })
  .loose();
export type Learner = z.infer<typeof learnerSchema>;

export const tutorConfigurationSchema = z
  .object({
    schema_version: z.literal("tutor-configuration.v1"),
    id: z.string(),
    learner_id: z.string(),
    appearance: appearanceSchema,
    personality: personalitySchema,
    comfort_override: comfortOverrideSchema,
    chosen_at: z.string(),
    last_changed_at: z.string(),
    // Comfort edits are separate from the durable pair and never move `last_changed_at`.
    comfort_updated_at: z.string().nullable().default(null),
  })
  .loose();
export type TutorConfiguration = z.infer<typeof tutorConfigurationSchema>;

export const PERSONA_OUTCOMES = [
  "initial_selection",
  "changed",
  "no_change",
] as const;

/**
 * The stored configuration plus the server's seven-day rule. Every instant is a server UTC
 * timestamp: the client only renders them and never decides eligibility from its own clock.
 */
export const personaStateSchema = tutorConfigurationSchema
  .extend({
    outcome: z.enum(PERSONA_OUTCOMES).nullable().default(null),
    comfort_changed: z.boolean().default(false),
    server_now: z.string(),
    change_cooldown_seconds: z.number().int(),
    persona_locked: z.boolean(),
    next_change_available_at: z.string().nullable().default(null),
  })
  .loose();
export type PersonaState = z.infer<typeof personaStateSchema>;

export const ANIMATION_PREFERENCES = [
  "system",
  "full",
  "reduced",
  "off",
] as const;
export const animationPreferenceSchema = z.enum(ANIMATION_PREFERENCES);
export type AnimationPreference = z.infer<typeof animationPreferenceSchema>;

export const accessibilityPreferencesSchema = z
  .object({
    schema_version: z.literal("accessibility-preferences.v1"),
    animation: animationPreferenceSchema,
    sound_enabled: z.boolean(),
    haptics_enabled: z.boolean(),
    text_only: z.boolean(),
    captions_enabled: z.boolean(),
    updated_at: z.string().nullable().default(null),
  })
  .loose();
export type AccessibilityPreferences = z.infer<
  typeof accessibilityPreferencesSchema
>;
export type AccessibilityPatch = Partial<
  Pick<
    AccessibilityPreferences,
    | "animation"
    | "sound_enabled"
    | "haptics_enabled"
    | "text_only"
    | "captions_enabled"
  >
>;

export const personaOptionsSchema = z
  .object({
    appearances: z.array(appearanceSchema),
    personalities: z.array(personalitySchema),
    comfort_overrides: z.array(comfortOverrideSchema),
    note: z.string(),
  })
  .loose();
export type PersonaOptions = z.infer<typeof personaOptionsSchema>;

export const pairingResultSchema = z
  .object({
    schema_version: z.literal("pairing-result.v1"),
    learner: learnerSchema,
    access_token: z.string(),
    token_type: z.literal("bearer"),
    notice: z.string(),
  })
  .loose();
export type PairingResult = z.infer<typeof pairingResultSchema>;

export const meResponseSchema = z
  .object({
    schema_version: z.literal("me.v1"),
    learner: learnerSchema,
    tutor_configuration: tutorConfigurationSchema.nullable(),
    notice: z.string(),
  })
  .loose();
export type MeResponse = z.infer<typeof meResponseSchema>;

export const sessionSchema = z
  .object({
    schema_version: z.literal("session.v1"),
    id: z.string(),
    learner_id: z.string(),
    status: z.enum(["active", "ended", "expired"]),
    goal: z.string().nullable(),
    revision: z.number().int().nonnegative(),
    // Advances whenever pending tutor output is withdrawn (interrupt, new work, restart).
    cancellation_epoch: z.number().int().nonnegative().default(0),
    started_at: z.string(),
    ended_at: z.string().nullable(),
  })
  .loose();
export type Session = z.infer<typeof sessionSchema>;
export const sessionListSchema = z.array(sessionSchema);

export const sceneObjectSchema = z
  .object({
    schema_version: z.literal("scene-object.v1"),
    id: z.string(),
    learner_id: z.string(),
    session_id: z.string(),
    author_role: z.enum(["student", "tutor"]),
    semantic_role: z.string(),
    kind: z.string(),
    payload: z.record(z.string(), z.unknown()),
    teaching_step_id: z.string().nullable(),
    created_at: z.string(),
    deleted_at: z.string().nullable(),
  })
  .loose();
export type SceneObjectDto = z.infer<typeof sceneObjectSchema>;

export const sceneSnapshotSchema = z
  .object({
    schema_version: z.literal("scene-snapshot.v1"),
    session_id: z.string(),
    scene_revision: z.number().int().nonnegative(),
    board_width: z.number(),
    board_height: z.number(),
    pen_width: z.number(),
    objects: z.array(sceneObjectSchema),
    student_undo_available: z.boolean(),
    student_redo_available: z.boolean(),
    tutor_move_undo_available: z.boolean(),
  })
  .loose();
export type SceneSnapshot = z.infer<typeof sceneSnapshotSchema>;

export const sceneOperationResultSchema = z
  .object({
    schema_version: z.literal("scene-operation-result.v1"),
    operation_id: z.string(),
    session_id: z.string(),
    scene_revision: z.number().int().nonnegative(),
    kind: z.enum([
      "add_object",
      "erase_object",
      "undo",
      "redo",
      "undo_tutor_move",
    ]),
    author_role: z.enum(["student", "tutor"]),
    object_id: z.string().nullable(),
    affected_object_ids: z.array(z.string()),
    replayed: z.boolean(),
  })
  .loose();
export type SceneOperationResult = z.infer<typeof sceneOperationResultSchema>;

export const problemViewSchema = z
  .object({
    problem_id: z.string(),
    attempt_id: z.string(),
    statement: z.string(),
    kind: z.enum(["practice", "transfer", "explanation"]),
    concept_id: z.string(),
    statement_object_id: z.string().nullable(),
  })
  .loose();
export type ProblemView = z.infer<typeof problemViewSchema>;

export const sessionStateSchema = z
  .object({
    schema_version: z.literal("session-state.v1"),
    session: sessionSchema,
    current_problem: problemViewSchema.nullable(),
    pace: z.enum(["standard", "lighter"]),
    pending_turn_id: z.string().nullable(),
    session_context_recheck: z.boolean(),
    persona: tutorConfigurationSchema.nullable(),
  })
  .loose();
export type SessionState = z.infer<typeof sessionStateSchema>;

export const providerLabelSchema = z
  .object({ name: z.string(), is_mock: z.boolean(), label: z.string() })
  .loose();

/** The verifier's judgment: a mathematical claim only, never about reasoning or independence. */
export const verificationResultSchema = z
  .object({
    check: z.enum(["expression_step", "equation_step", "solution"]),
    status: z.enum(["valid", "invalid", "unknown"]),
    reason: z.string(),
    judgment_scope: z.literal("mathematical"),
  })
  .loose();
export type VerificationResult = z.infer<typeof verificationResultSchema>;

/** A bounded, tentative reading of the learner's stated method (never a verdict on them). */
export const reasoningAssessmentSchema = z
  .object({
    judgment_scope: z.literal("pedagogical"),
    evidence_kind: z.literal("inference"),
    status: z.literal("questionable"),
    pattern: z.string(),
    confidence: z.number().min(0).max(1),
    explanation_text: z.string(),
  })
  .loose();
export type ReasoningAssessment = z.infer<typeof reasoningAssessmentSchema>;

export const eligibilityNoteSchema = z
  .object({
    observation_id: z.string(),
    evidence_kind: z.string(),
    source_type: z.string(),
    assisted: z.boolean(),
    eligible: z.boolean(),
    reason: z.string().nullable(),
    update_status: z.string().nullable().optional(),
  })
  .loose();
export type EligibilityNote = z.infer<typeof eligibilityNoteSchema>;

export const studentInputOutcomeSchema = z
  .object({
    input_mode: z.string(),
    text: z.string().nullable(),
    classification: z.string(),
    step_id: z.string().nullable(),
    observation_ids: z.array(z.string()),
    assessment_id: z.string().nullable(),
    assessment_kind: z.string().nullable(),
    assessment_independent: z.boolean().nullable(),
    verification: verificationResultSchema.nullable().default(null),
    reasoning_assessment: reasoningAssessmentSchema.nullable().default(null),
    eligibility: z.array(eligibilityNoteSchema).default([]),
  })
  .loose();
export type StudentInputOutcome = z.infer<typeof studentInputOutcomeSchema>;

export const committedDrawingSchema = z
  .object({
    object_id: z.string(),
    tool: z.string(),
    semantic_role: z.string(),
  })
  .loose();

/** A tentative inference with its confidence, alternatives and actual supporting sources. */
export const hypothesisViewSchema = z
  .object({
    id: z.string(),
    label: z.string(),
    confidence: z.number().min(0).max(1),
    alternatives: z.array(z.string()),
    status: z.string(),
    source_ids: z.array(z.string()),
    contradicting_source_ids: z.array(z.string()).default([]),
    substantive_counterevidence: z.boolean().default(false),
  })
  .loose();
export type HypothesisView = z.infer<typeof hypothesisViewSchema>;

export const REPRESENTATIONS = [
  "outside_factor",
  "groups_picture",
  "number_case",
  "copy_check",
  "worked_step",
  "next_step",
] as const;
export const representationSchema = z.enum(REPRESENTATIONS);
export type Representation = z.infer<typeof representationSchema>;

export const tutorTurnResultSchema = z
  .object({
    schema_version: z.literal("tutor-turn-result.v1"),
    turn_id: z.string(),
    session_id: z.string(),
    // Help me also returns kind 'work'; the server has no separate 'help' kind.
    kind: z.enum(["check_in", "work"]),
    status: z.enum([
      "pending",
      "committed",
      "rejected",
      "failed",
      "superseded",
    ]),
    base_revision: z.number().int().nonnegative(),
    session_revision: z.number().int().nonnegative(),
    cancellation_epoch: z.number().int().nonnegative().default(0),
    provider: providerLabelSchema,
    student_input: studentInputOutcomeSchema.nullable(),
    current_problem: problemViewSchema.nullable(),
    pace: z.enum(["standard", "lighter"]),
    action_type: z.string(),
    utterance: z.string().nullable(),
    expected_student_action: z.string().nullable(),
    hypothesis: hypothesisViewSchema.nullable().default(null),
    hint_level: z.number().int(),
    answer_revealed: z.boolean(),
    representation: representationSchema.nullable().default(null),
    support_change: z.enum(["none", "reduced"]).default("none"),
    decision_justification: z.string().nullable().default(null),
    drawings: z.array(committedDrawingSchema),
    rejections: z
      .array(z.object({ code: z.string(), message: z.string() }).loose())
      .default([]),
    replayed: z.boolean(),
  })
  .loose();
export type TutorTurnResult = z.infer<typeof tutorTurnResultSchema>;

export const interruptResultSchema = z
  .object({
    schema_version: z.literal("interrupt-result.v1"),
    session_id: z.string(),
    cancellation_epoch: z.number().int().nonnegative(),
    session_revision: z.number().int().nonnegative(),
    interrupted_turn_ids: z.array(z.string()),
    replayed: z.boolean(),
  })
  .loose();
export type InterruptResult = z.infer<typeof interruptResultSchema>;

export const waitPreferenceSchema = z
  .object({
    schema_version: z.literal("wait-preference.v1"),
    wait_seconds: z.number().int(),
    source: z.enum(["preference", "default"]),
    default_seconds: z.number().int(),
    min_seconds: z.number().int(),
    max_seconds: z.number().int(),
    updated_at: z.string().nullable(),
  })
  .loose();
export type WaitPreference = z.infer<typeof waitPreferenceSchema>;

/** Thinking-time state. The tutor never speaks on a timer and silence is missing evidence. */
export const waitStateSchema = z
  .object({
    schema_version: z.literal("wait-state.v1"),
    session_id: z.string(),
    now: z.string(),
    wait_seconds: z.number().int(),
    wait_source: z.enum(["preference", "default"]),
    last_activity_at: z.string(),
    still_thinking_at: z.string().nullable(),
    still_thinking_count: z.number().int().nonnegative(),
    quiet_hint_at: z.string(),
    quiet_hint_available: z.boolean(),
    next_hint_level: z.number().int(),
    proactive_prompt: z.literal("none"),
    silence_interpretation: z.literal("missing_evidence"),
  })
  .loose();
export type WaitState = z.infer<typeof waitStateSchema>;

export const errorEnvelopeSchema = z
  .object({
    schema_version: z.literal("error.v1"),
    error: z.object({ code: z.string(), message: z.string() }),
  })
  .loose();

// --- Private memory view, correction and removal -------------------------------------------

export const sourceExplanationSchema = z
  .object({
    id: z.string(),
    kind: z.string(),
    label: z.string(),
    at: z.string().nullable().default(null),
    excerpt: z.string().nullable().default(null),
    available: z.boolean().default(true),
  })
  .loose();
export type SourceExplanation = z.infer<typeof sourceExplanationSchema>;

export const memoryItemActionSchema = z
  .object({
    action: z.enum(["correct", "delete"]),
    method: z.enum(["POST", "DELETE"]),
    path: z.string(),
  })
  .loose();

export const memoryItemSchema = z
  .object({
    kind: z.enum([
      "evidence",
      "hypothesis",
      "note",
      "session_context",
      "estimate",
    ]),
    id: z.string(),
    layer: z.string(),
    title: z.string(),
    summary: z.string(),
    epistemic_status: z.string(),
    evidence_kind: z.string().nullable().default(null),
    state: z.string(),
    uncertainty: z
      .object({
        qualitative: z.string(),
        confidence: z.number().nullable().default(null),
        explanation: z.string(),
      })
      .loose(),
    why_it_matters: z.string(),
    provenance: z.string(),
    origin: z.string(),
    sources: z.array(sourceExplanationSchema),
    correction: z
      .object({
        original: z.string(),
        current: z.string(),
        corrected_at: z.string(),
      })
      .loose()
      .nullable()
      .default(null),
    supersedes_id: z.string().nullable().default(null),
    at: z.string(),
    actions: z.array(memoryItemActionSchema),
  })
  .loose();
export type MemoryItem = z.infer<typeof memoryItemSchema>;

export const memoryInspectionSchema = z
  .object({
    schema_version: z.literal("memory-inspection.v1"),
    generated_at: z.string(),
    // Per-bucket bound (five buckets), not a total cap or a page size.
    limit: z.number().int(),
    items: z.array(memoryItemSchema),
    notice: z.string(),
  })
  .loose();
export type MemoryInspection = z.infer<typeof memoryInspectionSchema>;

export const derivedEffectsSchema = z
  .object({
    hypotheses_retracted: z.array(z.string()).default([]),
    hypotheses_deleted: z.array(z.string()).default([]),
    notes_flagged_for_review: z.array(z.string()).default([]),
    notes_deleted: z.array(z.string()).default([]),
    turns_deleted: z.array(z.string()).default([]),
    pending_turns_invalidated: z.array(z.string()).default([]),
    recomputed_parameter_versions: z.array(z.string()).default([]),
    mastery_estimates: z
      .array(z.object({ concept_id: z.string(), p_known: z.number() }).loose())
      .default([]),
  })
  .loose();
export type DerivedEffects = z.infer<typeof derivedEffectsSchema>;

export const correctionReceiptSchema = z
  .object({
    schema_version: z.literal("memory-correction.v1"),
    kind: z.string(),
    record_id: z.string(),
    changed: z.boolean(),
    replacement_id: z.string().nullable().default(null),
    original: z.string().nullable().default(null),
    current: z.string().nullable().default(null),
    effects: derivedEffectsSchema,
  })
  .loose();
export type CorrectionReceipt = z.infer<typeof correctionReceiptSchema>;

export const deletionReceiptSchema = z
  .object({
    schema_version: z.literal("memory-deletion.v1"),
    kind: z.string(),
    record_id: z.string(),
    deleted_ids: z.array(z.string()),
    tombstones_written: z.number().int(),
    effects: derivedEffectsSchema,
    notice: z.string(),
  })
  .loose();
export type DeletionReceipt = z.infer<typeof deletionReceiptSchema>;

export const removalReceiptSchema = z
  .object({
    schema_version: z.literal("removal-receipt.v1"),
    scope: z.enum(["session", "profile"]),
    record_id: z.string(),
    before: z.record(z.string(), z.number()),
    after: z.record(z.string(), z.number()),
    credentials_revoked: z.number().int().default(0),
    tombstones_written: z.number().int(),
    effects: derivedEffectsSchema,
    notice: z.string(),
  })
  .loose();
export type RemovalReceipt = z.infer<typeof removalReceiptSchema>;

// --- Optional media: capabilities, bounded events and their uncertain outcomes ---------------

export const mediaCapabilitiesSchema = z
  .object({
    schema_version: z.literal("media-capabilities.v1"),
    perception: z.object({ status: z.string(), detail: z.string() }).loose(),
    transcription: z.object({ status: z.string(), detail: z.string() }).loose(),
    speech_interruption: z
      .object({
        supported: z.boolean(),
        acoustic_barge_in: z.literal(false),
        detail: z.string(),
      })
      .loose(),
    fixtures: z.object({ enabled: z.boolean(), detail: z.string() }).loose(),
    limits: z
      .object({
        max_image_bytes: z.number(),
        max_image_edge: z.number(),
        max_image_events_per_minute: z.number(),
        max_image_events_per_session: z.number(),
        max_events_per_minute: z.number(),
        max_events_per_session: z.number(),
        max_transcript_chars: z.number(),
      })
      .loose(),
    defaults: z
      .object({
        raw_media_stored: z.literal(false),
        raw_media_logged: z.literal(false),
        transcripts_retained: z.literal(false),
        provider_transmission: z.string(),
      })
      .loose(),
    disclosures: z.object({
      local: z.array(z.string()),
      transmitted: z.array(z.string()),
    }),
  })
  .loose();
export type MediaCapabilities = z.infer<typeof mediaCapabilitiesSchema>;

export const MEDIA_STATUSES = [
  "provisional",
  "final_accepted",
  "duplicate_final",
  "ignored_late",
  "perception_unavailable",
  "candidates_uncertain",
  "clarification_prompt",
] as const;

export const recognitionCandidateSchema = z
  .object({
    text: z.string(),
    confidence: z.number(),
    status: z.literal("uncertain"),
    editable: z.literal(true),
    synthetic: z.boolean(),
  })
  .loose();
export type RecognitionCandidate = z.infer<typeof recognitionCandidateSchema>;

export const mediaEventResultSchema = z
  .object({
    schema_version: z.literal("media-event-result.v1"),
    event_id: z.string(),
    kind: z.enum(["image_snapshot", "transcript", "weak_context"]),
    status: z.enum(MEDIA_STATUSES),
    simulated: z.boolean(),
    session_id: z.string(),
    session_revision: z.number().int(),
    cancellation_epoch: z.number().int(),
    replayed: z.boolean().default(false),
    candidates: z.array(recognitionCandidateSchema).default([]),
    requires_confirmation: z.boolean().default(false),
    message: z.string(),
    assessment_effect: z.literal("none"),
    evidence_recorded: z.literal(false),
    raw_media_retained: z.literal(false),
  })
  .loose();
export type MediaEventResult = z.infer<typeof mediaEventResultSchema>;

export type MediaEventRequest =
  | {
      kind: "image_snapshot";
      event_id: string;
      source: "device" | "simulated";
      orientation: "student_facing" | "work_facing";
      mime: "image/jpeg" | "image/png";
      width: number;
      height: number;
    }
  | {
      kind: "transcript";
      event_id: string;
      source: "simulated";
      utterance_id: string;
      sequence: number;
      phase: "interim" | "final";
      text: string;
    }
  | {
      kind: "weak_context";
      event_id: string;
      source: "simulated";
      signal: "silence" | "voice_level" | "expression_cue" | "gaze_cue";
    };
