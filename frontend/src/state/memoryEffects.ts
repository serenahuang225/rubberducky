/**
 * Plain-language summaries of what a correction, deletion or removal changed, built only from
 * the server's receipt so the learner sees the real derived updates (and the real limits of
 * deletion: the active local store, not secure disk, backup or vendor erasure).
 */

import type {
  CorrectionReceipt,
  DeletionReceipt,
  DerivedEffects,
  RemovalReceipt,
} from "../api/contracts";

export type ChangeSummary = {
  title: string;
  lines: string[];
  notice: string | null;
};

function plural(
  count: number,
  singular: string,
  pluralForm = `${singular}s`,
): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function effectLines(effects: DerivedEffects): string[] {
  const lines: string[] = [];
  const retracted = effects.hypotheses_retracted.length;
  if (retracted > 0) {
    lines.push(
      `${plural(retracted, "tentative belief")} that relied on it ${retracted === 1 ? "was" : "were"} withdrawn.`,
    );
  }
  const hypothesesDeleted = effects.hypotheses_deleted.length;
  if (hypothesesDeleted > 0) {
    lines.push(
      `${plural(hypothesesDeleted, "tentative belief")} deleted because ${hypothesesDeleted === 1 ? "it" : "they"} cited it.`,
    );
  }
  const flagged = effects.notes_flagged_for_review.length;
  if (flagged > 0) {
    lines.push(`${plural(flagged, "note")} marked for your review.`);
  }
  const notesDeleted = effects.notes_deleted.length;
  if (notesDeleted > 0) {
    lines.push(`${plural(notesDeleted, "note")} deleted.`);
  }
  const turns = effects.turns_deleted.length;
  if (turns > 0) {
    lines.push(
      `${plural(turns, "tutor reply", "tutor replies")} that used it removed.`,
    );
  }
  if (effects.pending_turns_invalidated.length > 0) {
    lines.push(
      "A reply that was being prepared was withdrawn so it cannot use the old information.",
    );
  }
  for (const estimate of effects.mastery_estimates) {
    lines.push(
      `Estimate for ${estimate.concept_id} recomputed: about ${Math.round(estimate.p_known * 100)}% likely known (uncalibrated guess, not a measured level).`,
    );
  }
  return lines;
}

export function summarizeCorrection(receipt: CorrectionReceipt): ChangeSummary {
  if (!receipt.changed) {
    return {
      title: "Nothing changed",
      lines: [
        "What you entered already matched the current value, so nothing changed.",
      ],
      notice: null,
    };
  }
  const lines: string[] = [];
  if (receipt.original !== null && receipt.current !== null) {
    lines.push(`Changed from ${receipt.original} to ${receipt.current}.`);
  }
  lines.push(...effectLines(receipt.effects));
  return { title: "Corrected", lines, notice: null };
}

export function summarizeDeletion(receipt: DeletionReceipt): ChangeSummary {
  const lines = [
    `${plural(receipt.deleted_ids.length, "item")} removed.`,
    ...effectLines(receipt.effects),
  ];
  return { title: "Deleted", lines, notice: receipt.notice };
}

export function summarizeRemoval(receipt: RemovalReceipt): ChangeSummary {
  const lines = Object.keys(receipt.before)
    .sort()
    .filter(
      (key) => receipt.before[key] !== 0 || (receipt.after[key] ?? 0) !== 0,
    )
    .map(
      (key) =>
        `${key.replace(/_/g, " ")}: ${receipt.before[key]} → ${receipt.after[key] ?? 0}`,
    );
  if (receipt.scope === "profile") {
    lines.push(
      `${plural(receipt.credentials_revoked, "sign-in")} on this profile revoked.`,
    );
  }
  lines.push(...effectLines(receipt.effects));
  return {
    title: receipt.scope === "profile" ? "Profile removed" : "Session removed",
    lines,
    notice: receipt.notice,
  };
}
