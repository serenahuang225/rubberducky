/**
 * Contract and math for released, runtime-generated explanations.
 *
 * Mirrors the backend's `explanation-spec.v1` / `released-explanation.v1`: a closed set of
 * bounded components, integer ranges and short plain text. There is no field that can carry
 * script, markup, a URL or a component this app does not ship, and unknown fields are
 * rejected, so a drifted or hostile payload fails to parse instead of rendering.
 */

import { z } from "zod";

export const MIN_FACTOR = 1;
export const MAX_FACTOR = 12;

// Same rule as the backend: markup, script, links, placeholders and control characters.
const FORBIDDEN_TEXT = /[<>{}[\]\\`$|]|[\u0000-\u001f\u007f]|:\/\/|javascript:|data:|www\.|https?|file:|\.com\b/i;

function plainText(min: number, max: number) {
  return z
    .string()
    .min(min)
    .max(max)
    .refine((value) => value === value.trim() && !FORBIDDEN_TEXT.test(value), {
      message: "text must be plain words without markup, links or control characters",
    });
}

const factor = z.number().int().min(MIN_FACTOR).max(MAX_FACTOR);

const rangeSchema = z
  .strictObject({ min: factor, max: factor, initial: factor })
  .refine((range) => range.min <= range.initial && range.initial <= range.max, {
    message: "initial must lie within min..max",
  });
export type IntRange = z.infer<typeof rangeSchema>;

const groupingSchema = z.strictObject({
  component: z.literal("grouping"),
  groups: rangeSchema,
  per_group: rangeSchema,
  item_label: plainText(1, 24),
});

const distributionSchema = z.strictObject({
  component: z.literal("distribution"),
  outer: rangeSchema,
  left: rangeSchema,
  right: rangeSchema,
});

export const explanationSpecSchema = z.strictObject({
  schema_version: z.literal("explanation-spec.v1"),
  concept_id: z.enum(["concept.distribution", "concept.grouping"]),
  title: plainText(1, 80),
  prompt: plainText(1, 160),
  caption: plainText(1, 240),
  manipulative: z.discriminatedUnion("component", [groupingSchema, distributionSchema]),
});
export type ExplanationSpec = z.infer<typeof explanationSpecSchema>;
export type GroupingSpec = z.infer<typeof groupingSchema>;
export type DistributionSpec = z.infer<typeof distributionSchema>;

const integrationState = z.enum(["disabled", "not_configured", "configured_unverified"]);

export const releasedExplanationSchema = z
  .looseObject({
    schema_version: z.literal("released-explanation.v1"),
    source: z.enum(["generated_verified", "prevetted_fallback"]),
    label: plainText(1, 120),
    spec: explanationSpecSchema,
    fallback_reason: z.string().nullable(),
    factory_state: integrationState,
    daytona_state: integrationState,
    sandbox_ids_created: z.array(z.string()).default([]),
    sandbox_ids_deleted: z.array(z.string()).default([]),
  })
  .refine((released) => (released.source === "prevetted_fallback") === (released.fallback_reason !== null), {
    message: "a fallback names its reason; a verified release has none",
  })
  .refine(
    (released) =>
      released.source !== "generated_verified" ||
      [...released.sandbox_ids_created].sort().join("\n") ===
        [...released.sandbox_ids_deleted].sort().join("\n"),
    { message: "a verified release needs every created sandbox confirmed deleted" },
  );
export type ReleasedExplanation = z.infer<typeof releasedExplanationSchema>;

export type ParsedExplanation =
  | { ok: true; value: ReleasedExplanation }
  | { ok: false; error: string };

/** Accepts only a fully valid released explanation; never throws on hostile input. */
export function parseReleasedExplanation(input: unknown): ParsedExplanation {
  const result = releasedExplanationSchema.safeParse(input);
  if (!result.success) {
    return { ok: false, error: "This explanation could not be shown safely." };
  }
  return { ok: true, value: result.data };
}

export function clampToRange(value: number, range: IntRange): number {
  if (!Number.isFinite(value)) {
    return range.initial;
  }
  return Math.min(range.max, Math.max(range.min, Math.round(value)));
}

export function groupingTotal(groups: number, perGroup: number): number {
  return groups * perGroup;
}

export type DistributionAreas = { left: number; right: number; whole: number };

export function distributionAreas(outer: number, left: number, right: number): DistributionAreas {
  return { left: outer * left, right: outer * right, whole: outer * (left + right) };
}

export function pluralize(count: number, singular: string): string {
  return count === 1 ? singular : `${singular}s`;
}
