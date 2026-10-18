/**
 * Load the fictional Chalk, Droid, and Daytona walkthrough.
 * The payload is invented demo content; the request does not send a credential.
 */

import { z } from "zod";

import { explanationSpecSchema } from "../interactives/explanationSpec";

const scoreSchema = z.object({
  dimension: z.string(),
  value: z.number().nullable(),
});

const turnSchema = z.object({
  scenario: z.string(),
  learner_message: z.string(),
  reply: z.string(),
  scores: z.array(scoreSchema),
});

const candidateSchema = z.object({
  candidate_name: z.string(),
  note: z.string(),
  errors: z.number(),
  dimensions: z.array(
    z.object({
      dimension: z.string(),
      mean: z.number().nullable(),
      scored_rows: z.number(),
      missing_rows: z.number(),
    }),
  ),
  turns: z.array(turnSchema),
});

export const integrationDemosSchema = z.object({
  schema_version: z.literal("fictional-integration-demos.v1"),
  is_fictional: z.literal(true),
  live_services_contacted: z.literal(false),
  notice: z.string(),
  chalk: z.object({
    title: z.string(),
    notice: z.string(),
    dataset_name: z.string(),
    dataset_rows: z.number(),
    uploaded: z.literal(false),
    trained_model_result: z.literal(false),
    learning_gain_claim: z.literal(false),
    candidates: z.array(candidateSchema).min(1),
  }),
  droid: z.object({
    title: z.string(),
    notice: z.string(),
    misconception: z.string(),
    context_note: z.string(),
    self_check_notes: z.array(z.string()),
    factory_contacted: z.literal(false),
    credits_spent: z.literal(0),
    picture_label: z.string(),
    spec: explanationSpecSchema,
  }),
  daytona: z.object({
    title: z.string(),
    notice: z.string(),
    sandbox_id: z.string(),
    sandbox_created: z.literal(false),
    passed: z.boolean(),
    checks: z.array(
      z.object({
        name: z.string(),
        passed: z.boolean(),
        detail: z.string(),
      }),
    ),
  }),
});

export type IntegrationDemos = z.infer<typeof integrationDemosSchema>;
export type FetchLike = (
  input: string,
  init?: { signal?: AbortSignal },
) => Promise<Response>;

const TIMEOUT_MS = 8000;

export async function fetchIntegrationDemos(
  baseUrl: string,
  fetchImpl: FetchLike = (input, init) => fetch(input, init),
): Promise<IntegrationDemos> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetchImpl(`${baseUrl}/demo/integrations`, {
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }
    return integrationDemosSchema.parse(await response.json());
  } finally {
    clearTimeout(timer);
  }
}
