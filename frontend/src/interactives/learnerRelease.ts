/**
 * Load and read the offline learner explanation.
 *
 * The response is the backend's `learner-explanation.v1`: a notice plus a released spec.
 * `live_services_contacted` must be false. The released spec is then parsed by the existing
 * bounded parser before anything is drawn. This module does not send a credential.
 */

import { z } from "zod";

import { parseReleasedExplanation, type ReleasedExplanation } from "./explanationSpec";

export type { ReleasedExplanation };

export type ExplanationConceptId = "concept.distribution" | "concept.grouping";

export type LearnerExplanationRequest = {
  concept_id: ExplanationConceptId;
  misconception: string;
  context_note: string;
};

export const LEARNER_MISCONCEPTION = "Needs a concrete picture of this idea";

export const UNAVAILABLE_EXPLANATION =
  "This explanation is unavailable. Your work on the board is unchanged.";

const STATE_WORDS: Record<string, string> = {
  disabled: "disabled",
  not_configured: "not configured",
  configured_unverified: "configured, unverified",
};

const learnerEnvelope = z.object({
  schema_version: z.literal("learner-explanation.v1"),
  live_services_contacted: z.boolean(),
  notice: z.string().min(1).max(400),
  release: z.unknown(),
});

export type ReadLearnerExplanation =
  | { ok: true; notice: string; release: ReleasedExplanation }
  | { ok: false; error: string };

export function requestForConcept(conceptId: string | null | undefined): LearnerExplanationRequest {
  const concept_id: ExplanationConceptId =
    conceptId === "concept.grouping" || conceptId === "concept.distribution"
      ? conceptId
      : "concept.distribution";
  return {
    concept_id,
    misconception: LEARNER_MISCONCEPTION,
    context_note: "",
  };
}

export function integrationStateLabel(service: "Factory" | "Daytona", state: string): string {
  return `${service}: ${STATE_WORDS[state] ?? "unavailable"}`;
}

/** Accept a learner envelope or a bare released explanation. Never throws. */
export function readLearnerExplanation(input: unknown): ReadLearnerExplanation {
  const envelope = learnerEnvelope.safeParse(input);
  if (envelope.success) {
    if (envelope.data.live_services_contacted) {
      return { ok: false, error: "This explanation could not be shown safely." };
    }
    const parsed = parseReleasedExplanation(envelope.data.release);
    if (!parsed.ok) {
      return parsed;
    }
    return { ok: true, notice: envelope.data.notice, release: parsed.value };
  }
  if (
    input !== null &&
    typeof input === "object" &&
    "schema_version" in input &&
    (input as { schema_version?: unknown }).schema_version === "learner-explanation.v1"
  ) {
    return { ok: false, error: "This explanation could not be shown safely." };
  }
  const parsed = parseReleasedExplanation(input);
  if (!parsed.ok) {
    return parsed;
  }
  return { ok: true, notice: "", release: parsed.value };
}

export type FetchLike = (
  input: string,
  init?: { method?: string; headers?: Record<string, string>; body?: string; signal?: AbortSignal },
) => Promise<{ ok: boolean; status: number; json: () => Promise<unknown> }>;

const TIMEOUT_MS = 8000;

export async function fetchLearnerExplanation(
  baseUrl: string,
  request: LearnerExplanationRequest,
  fetchImpl: FetchLike = (input, init) => fetch(input, init),
): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetchImpl(`${baseUrl}/explanations/learner`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}
