import {
  correctionReceiptSchema,
  deletionReceiptSchema,
  removalReceiptSchema,
} from "../api/contracts";
import {
  EVIDENCE_CORRECTION_RECEIPT,
  NOTE_DELETION_RECEIPT,
  PROFILE_REMOVAL_RECEIPT,
  SESSION_REMOVAL_RECEIPT,
} from "../testing/agencyFixtures";

import {
  summarizeCorrection,
  summarizeDeletion,
  summarizeRemoval,
} from "./memoryEffects";

describe("memory change summaries", () => {
  it("lists what a correction recomputed or withdrew, with the new estimate as a percent", () => {
    const summary = summarizeCorrection(
      correctionReceiptSchema.parse(EVIDENCE_CORRECTION_RECEIPT),
    );
    expect(summary.title).toMatch(/corrected/i);
    expect(summary.lines.join(" ")).toMatch(
      /changed from incorrect to correct/i,
    );
    expect(summary.lines.join(" ")).toMatch(/1 tentative belief.* withdrawn/i);
    expect(summary.lines.join(" ")).toMatch(/concept\.distribution.*67%/);
    expect(summary.lines.join(" ")).toMatch(/uncalibrated/i);
  });

  it("says plainly when a correction changed nothing", () => {
    const receipt = correctionReceiptSchema.parse({
      ...EVIDENCE_CORRECTION_RECEIPT,
      changed: false,
      effects: {
        ...EVIDENCE_CORRECTION_RECEIPT.effects,
        hypotheses_retracted: [],
        mastery_estimates: [],
      },
    });
    expect(summarizeCorrection(receipt).lines.join(" ")).toMatch(
      /already matched|nothing changed/i,
    );
  });

  it("describes a deletion with its honest local-store scope", () => {
    const summary = summarizeDeletion(
      deletionReceiptSchema.parse(NOTE_DELETION_RECEIPT),
    );
    expect(summary.title).toMatch(/deleted/i);
    expect(summary.lines.join(" ")).toMatch(/1 item/);
    expect(summary.notice).toMatch(/no deleted text is retained/i);
    expect(summary.notice).not.toMatch(/securely|permanently erased/i);
  });

  it("reports before/after counts for a session and profile removal", () => {
    const session = summarizeRemoval(
      removalReceiptSchema.parse(SESSION_REMOVAL_RECEIPT),
    );
    expect(session.title).toMatch(/session removed/i);
    expect(session.lines.join(" ")).toMatch(/observations: 4 → 0/);
    expect(session.notice).toMatch(
      /not secure disk, backup or vendor erasure/i,
    );
    const profile = summarizeRemoval(
      removalReceiptSchema.parse(PROFILE_REMOVAL_RECEIPT),
    );
    expect(profile.title).toMatch(/profile removed/i);
    expect(profile.lines.join(" ")).toMatch(/1 sign-in/i);
  });

  it("mentions replies that were being prepared and got withdrawn", () => {
    const base = correctionReceiptSchema.parse(EVIDENCE_CORRECTION_RECEIPT);
    const summary = summarizeCorrection({
      ...base,
      effects: { ...base.effects, pending_turns_invalidated: ["turn-9"] },
    });
    expect(summary.lines.join(" ")).toMatch(
      /reply that was being prepared was withdrawn/i,
    );
  });

  it("leaves out counts that were zero before and after, so the receipt shows only real removals", () => {
    const summary = summarizeRemoval(
      removalReceiptSchema.parse({
        ...SESSION_REMOVAL_RECEIPT,
        before: { observations: 4, hints: 0 },
        after: { observations: 0, hints: 0 },
      }),
    );
    expect(summary.lines.join(" ")).toContain("observations: 4 → 0");
    expect(summary.lines.join(" ")).not.toContain("hints");
  });
});
