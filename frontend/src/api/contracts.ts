/**
 * Zod contracts mirroring the backend's versioned Pydantic schemas.
 *
 * Only the fields the client reads are decoded; unknown server fields are tolerated,
 * while required fields and literals must match so a drifted backend fails loudly.
 */

import { z } from 'zod';

export const APPEARANCES = ['animal', 'older_adult', 'younger_adult'] as const;
export const PERSONALITIES = ['gentle', 'matter_of_fact', 'playful', 'mildly_sassy'] as const;

export const appearanceSchema = z.enum(APPEARANCES);
export const personalitySchema = z.enum(PERSONALITIES);
export const comfortOverrideSchema = z.enum(['none', 'neutral_supportive', 'reduced_sass']);

export type Appearance = z.infer<typeof appearanceSchema>;
export type Personality = z.infer<typeof personalitySchema>;
export type ComfortOverride = z.infer<typeof comfortOverrideSchema>;

export const learnerSchema = z
  .object({
    schema_version: z.literal('learner.v1'),
    id: z.string(),
    display_name: z.string(),
    is_fictional: z.boolean(),
  })
  .loose();
export type Learner = z.infer<typeof learnerSchema>;

export const tutorConfigurationSchema = z
  .object({
    schema_version: z.literal('tutor-configuration.v1'),
    id: z.string(),
    learner_id: z.string(),
    appearance: appearanceSchema,
    personality: personalitySchema,
    comfort_override: comfortOverrideSchema,
    chosen_at: z.string(),
    last_changed_at: z.string(),
  })
  .loose();
export type TutorConfiguration = z.infer<typeof tutorConfigurationSchema>;

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
    schema_version: z.literal('pairing-result.v1'),
    learner: learnerSchema,
    access_token: z.string(),
    token_type: z.literal('bearer'),
    notice: z.string(),
  })
  .loose();
export type PairingResult = z.infer<typeof pairingResultSchema>;

export const meResponseSchema = z
  .object({
    schema_version: z.literal('me.v1'),
    learner: learnerSchema,
    tutor_configuration: tutorConfigurationSchema.nullable(),
    notice: z.string(),
  })
  .loose();
export type MeResponse = z.infer<typeof meResponseSchema>;

export const sessionSchema = z
  .object({
    schema_version: z.literal('session.v1'),
    id: z.string(),
    learner_id: z.string(),
    status: z.enum(['active', 'ended', 'expired']),
    goal: z.string().nullable(),
    revision: z.number().int().nonnegative(),
    started_at: z.string(),
    ended_at: z.string().nullable(),
  })
  .loose();
export type Session = z.infer<typeof sessionSchema>;
export const sessionListSchema = z.array(sessionSchema);

export const sceneObjectSchema = z
  .object({
    schema_version: z.literal('scene-object.v1'),
    id: z.string(),
    learner_id: z.string(),
    session_id: z.string(),
    author_role: z.enum(['student', 'tutor']),
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
    schema_version: z.literal('scene-snapshot.v1'),
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
    schema_version: z.literal('scene-operation-result.v1'),
    operation_id: z.string(),
    session_id: z.string(),
    scene_revision: z.number().int().nonnegative(),
    kind: z.enum(['add_object', 'erase_object', 'undo', 'redo', 'undo_tutor_move']),
    author_role: z.enum(['student', 'tutor']),
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
    kind: z.enum(['practice', 'transfer', 'explanation']),
    concept_id: z.string(),
    statement_object_id: z.string().nullable(),
  })
  .loose();
export type ProblemView = z.infer<typeof problemViewSchema>;

export const sessionStateSchema = z
  .object({
    schema_version: z.literal('session-state.v1'),
    session: sessionSchema,
    current_problem: problemViewSchema.nullable(),
    pace: z.enum(['standard', 'lighter']),
    pending_turn_id: z.string().nullable(),
    session_context_recheck: z.boolean(),
    persona: tutorConfigurationSchema.nullable(),
  })
  .loose();
export type SessionState = z.infer<typeof sessionStateSchema>;

export const providerLabelSchema = z
  .object({ name: z.string(), is_mock: z.boolean(), label: z.string() })
  .loose();

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
  })
  .loose();
export type StudentInputOutcome = z.infer<typeof studentInputOutcomeSchema>;

export const committedDrawingSchema = z
  .object({ object_id: z.string(), tool: z.string(), semantic_role: z.string() })
  .loose();

export const tutorTurnResultSchema = z
  .object({
    schema_version: z.literal('tutor-turn-result.v1'),
    turn_id: z.string(),
    session_id: z.string(),
    kind: z.enum(['check_in', 'work']),
    status: z.enum(['pending', 'committed', 'rejected', 'failed', 'superseded']),
    base_revision: z.number().int().nonnegative(),
    session_revision: z.number().int().nonnegative(),
    provider: providerLabelSchema,
    student_input: studentInputOutcomeSchema.nullable(),
    current_problem: problemViewSchema.nullable(),
    pace: z.enum(['standard', 'lighter']),
    action_type: z.string(),
    utterance: z.string().nullable(),
    expected_student_action: z.string().nullable(),
    hint_level: z.number().int(),
    answer_revealed: z.boolean(),
    drawings: z.array(committedDrawingSchema),
    replayed: z.boolean(),
  })
  .loose();
export type TutorTurnResult = z.infer<typeof tutorTurnResultSchema>;

export const errorEnvelopeSchema = z
  .object({
    schema_version: z.literal('error.v1'),
    error: z.object({ code: z.string(), message: z.string() }),
  })
  .loose();
