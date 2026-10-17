/**
 * Wire-shaped persona, accessibility and memory fixtures mirroring the backend's
 * PersonaState, AccessibilityPreferences, MemoryInspection and receipt payloads.
 * Test-only; never bundled.
 */

export const PERSONA_STATE_LOCKED = {
  schema_version: "tutor-configuration.v1",
  id: "cfg-1",
  learner_id: "learner-1",
  appearance: "animal",
  personality: "mildly_sassy",
  comfort_override: "none",
  provenance: "submitted",
  chosen_at: "2026-10-10T12:30:00Z",
  last_changed_at: "2026-10-10T12:30:00Z",
  comfort_updated_at: null,
  outcome: null,
  comfort_changed: false,
  server_now: "2026-10-12T09:00:00Z",
  change_cooldown_seconds: 604800,
  persona_locked: true,
  next_change_available_at: "2026-10-17T12:30:00Z",
};

export const PERSONA_STATE_OPEN = {
  ...PERSONA_STATE_LOCKED,
  server_now: "2026-10-18T09:00:00Z",
  persona_locked: false,
  next_change_available_at: null,
};

export const ACCESSIBILITY_DEFAULTS = {
  schema_version: "accessibility-preferences.v1",
  animation: "system",
  sound_enabled: true,
  haptics_enabled: true,
  text_only: false,
  captions_enabled: true,
  updated_at: null,
};

const NO_DERIVED = {
  hypotheses_retracted: [],
  hypotheses_deleted: [],
  notes_flagged_for_review: [],
  notes_deleted: [],
  turns_deleted: [],
  pending_turns_invalidated: [],
  recomputed_parameter_versions: [],
  mastery_estimates: [],
};

export const NOTE_ITEM = {
  kind: "note",
  id: "mem-1",
  layer: "episodic_note",
  title: "Distributing over a sum",
  summary: "You distributed the 2 to the first term only.",
  epistemic_status: "inference",
  evidence_kind: "inference",
  state: "current",
  uncertainty: {
    qualitative: "moderate",
    confidence: 0.6,
    explanation: "One attempt only.",
  },
  why_it_matters: "Used to choose a hint about the outside factor.",
  provenance: "submitted",
  origin: "tutor_proposal",
  sources: [
    {
      id: "obs-1",
      kind: "observation",
      label: 'Your step "2x + 3 = 14"',
      at: "2026-10-10T12:40:00Z",
      excerpt: "2x + 3 = 14",
      available: true,
    },
  ],
  correction: null,
  supersedes_id: null,
  at: "2026-10-10T12:41:00Z",
  actions: [
    {
      action: "correct",
      method: "POST",
      path: "/memory/notes/mem-1/correction",
    },
    { action: "delete", method: "DELETE", path: "/memory/notes/mem-1" },
  ],
};

export const EVIDENCE_ITEM = {
  kind: "evidence",
  id: "obs-1",
  layer: "raw_evidence",
  title: "Step check",
  summary: "Recorded as incorrect.",
  epistemic_status: "verified",
  evidence_kind: "verified_assessment",
  state: "current",
  uncertainty: {
    qualitative: "low",
    confidence: null,
    explanation: "Checked by the verifier.",
  },
  why_it_matters: "Feeds your estimate for this concept.",
  provenance: "submitted",
  origin: "measured",
  sources: [],
  correction: null,
  supersedes_id: null,
  at: "2026-10-10T12:40:00Z",
  actions: [
    {
      action: "correct",
      method: "POST",
      path: "/memory/evidence/obs-1/correction",
    },
    { action: "delete", method: "DELETE", path: "/memory/evidence/obs-1" },
  ],
};

export const ESTIMATE_ITEM = {
  kind: "estimate",
  id: "est-1",
  layer: "derived_estimate",
  title: "Distribution estimate",
  summary: "Roughly 40% likely known (uncalibrated).",
  epistemic_status: "derived_estimate",
  evidence_kind: null,
  state: "uncalibrated",
  uncertainty: {
    qualitative: "high",
    confidence: 0.4,
    explanation: "Few observations.",
  },
  why_it_matters: "Shapes how much support the next problem starts with.",
  provenance: "submitted",
  origin: "system",
  sources: [],
  correction: null,
  supersedes_id: null,
  at: "2026-10-10T12:41:00Z",
  actions: [],
};

export const INSPECTION = {
  schema_version: "memory-inspection.v1",
  learner_id: "learner-1",
  generated_at: "2026-10-12T09:00:00Z",
  limit: 20,
  items: [NOTE_ITEM, EVIDENCE_ITEM, ESTIMATE_ITEM],
  notice:
    "This is your private memory view. Estimates are uncalibrated guesses from limited evidence; you can correct or delete anything here.",
};

export const NOTE_DELETION_RECEIPT = {
  schema_version: "memory-deletion.v1",
  kind: "note",
  record_id: "mem-1",
  deleted_ids: ["mem-1"],
  tombstones_written: 1,
  effects: { ...NO_DERIVED, notes_deleted: ["mem-1"] },
  notice: "Removed from the active local store; no deleted text is retained.",
};

export const EVIDENCE_CORRECTION_RECEIPT = {
  schema_version: "memory-correction.v1",
  kind: "evidence",
  record_id: "obs-1",
  changed: true,
  replacement_id: null,
  original: "incorrect",
  current: "correct",
  effects: {
    ...NO_DERIVED,
    hypotheses_retracted: ["hyp-1"],
    recomputed_parameter_versions: ["bkt.v1"],
    mastery_estimates: [{ concept_id: "concept.distribution", p_known: 0.67 }],
  },
};

export const SESSION_REMOVAL_RECEIPT = {
  schema_version: "removal-receipt.v1",
  scope: "session",
  record_id: "s1",
  before: { observations: 4, memory_entries: 2 },
  after: { observations: 0, memory_entries: 0 },
  credentials_revoked: 0,
  tombstones_written: 2,
  effects: NO_DERIVED,
  notice:
    "Removed from the active local store. This is not secure disk, backup or vendor erasure, and the shared curriculum and other learners are untouched.",
};

export const PROFILE_REMOVAL_RECEIPT = {
  ...SESSION_REMOVAL_RECEIPT,
  scope: "profile",
  record_id: "learner-1",
  credentials_revoked: 1,
};
