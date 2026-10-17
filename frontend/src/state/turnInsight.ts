/**
 * Plain-language reading of one committed tutor turn for the learner.
 *
 * Everything here restates what the server reported; nothing is inferred on the client.
 * The verifier's mathematical judgment, the tentative reading of the stated method and the
 * independence outcome stay three separate lines, so a correct value never reads as
 * mastery and a questionable method never reads as "wrong".
 */

import type {
  EligibilityNote,
  Representation,
  StudentInputOutcome,
  TutorTurnResult,
} from '../api/contracts';

export type DiagnosticView = {
  hypothesisLabel: string | null;
  confidencePercent: number | null;
  status: string | null;
  alternatives: string[];
  supportingSourceIds: string[];
  contradictingSourceIds: string[];
  substantiveCounterevidence: boolean;
  justification: string | null;
  eligibilityNotes: string[];
};

export type TurnInsight = {
  representation: string | null;
  disclosure: string | null;
  supportChange: string | null;
  hintLevel: string | null;
  mathJudgment: string | null;
  reasoningJudgment: string | null;
  independence: string | null;
  diagnostic: DiagnosticView | null;
};

const REPRESENTATION_LABELS: Record<Representation, string> = {
  outside_factor: 'Outside factor',
  groups_picture: 'Groups picture',
  number_case: 'Number case',
  copy_check: 'Copy check',
  worked_step: 'Worked step',
  next_step: 'Next step',
};

/** Input kinds that carry no judgment about the learner's math. */
const NON_WORK_CLASSIFICATIONS = new Set([
  'check_in',
  'not_sure',
  'explain_request',
  'unconfirmed_ink',
  'unsupported',
]);

function mathJudgment(student: StudentInputOutcome): string | null {
  const verification = student.verification;
  if (verification === null) return null;
  const isSolution = verification.check === 'solution';
  switch (verification.status) {
    case 'valid':
      return isSolution
        ? 'Math check: this value solves the equation.'
        : 'Math check: this step is equivalent to the problem.';
    case 'invalid':
      return isSolution
        ? 'Math check: this value does not solve the equation.'
        : 'Math check: this step is not equivalent to the problem.';
    default:
      return 'Math check: I could not check this input.';
  }
}

function reasoningJudgment(student: StudentInputOutcome): string | null {
  const assessment = student.reasoning_assessment;
  if (assessment === null) return null;
  return `Reasoning (tentative reading): "${assessment.explanation_text}" may leave part of the problem untouched. This is a question to check, not a verdict.`;
}

function humanize(reason: string): string {
  return reason.replace(/_/g, ' ');
}

function eligibilityNote(note: EligibilityNote): string {
  if (note.assisted) {
    return 'This work was assisted, so it is not counted as independent.';
  }
  if (note.reason === 'independent_reasoning_missing') {
    return 'No reasoning was shown yet, so this is not counted as independent.';
  }
  if (note.eligible) {
    return 'This observation can count as independent evidence.';
  }
  return note.reason === null
    ? 'This observation is not counted as independent evidence.'
    : `Not counted as independent evidence (${humanize(note.reason)}).`;
}

function independence(student: StudentInputOutcome): string | null {
  if (student.assessment_independent === null) return null;
  if (student.assessment_independent) {
    return 'Counted as independent work.';
  }
  const note = student.eligibility.find((entry) => entry.assisted) ?? student.eligibility[0];
  if (note?.assisted) {
    return 'Counted as assisted work, not independent success.';
  }
  if (note?.reason === 'independent_reasoning_missing') {
    return 'Not counted as independent success yet: no reasoning was shown.';
  }
  return 'Not counted as independent success.';
}

export function describeTurn(turn: TutorTurnResult): TurnInsight {
  const student = turn.student_input;
  const judgesWork = student !== null && !NON_WORK_CLASSIFICATIONS.has(student.classification);

  const diagnostic: DiagnosticView | null =
    turn.hypothesis !== null || turn.decision_justification !== null
      ? {
          hypothesisLabel: turn.hypothesis?.label ?? null,
          confidencePercent:
            turn.hypothesis === null ? null : Math.round(turn.hypothesis.confidence * 100),
          status: turn.hypothesis?.status ?? null,
          alternatives: turn.hypothesis?.alternatives ?? [],
          supportingSourceIds: turn.hypothesis?.source_ids ?? [],
          contradictingSourceIds: turn.hypothesis?.contradicting_source_ids ?? [],
          substantiveCounterevidence: turn.hypothesis?.substantive_counterevidence ?? false,
          justification: turn.decision_justification,
          eligibilityNotes: (student?.eligibility ?? [])
            .filter((note) => note.evidence_kind !== 'self_report')
            .map(eligibilityNote),
        }
      : null;

  return {
    representation: turn.representation === null ? null : REPRESENTATION_LABELS[turn.representation],
    disclosure: turn.answer_revealed
      ? 'The tutor showed the step in this explanation, so success on it will count as assisted.'
      : null,
    supportChange:
      turn.support_change === 'reduced' ? 'Support reduced: this one starts with less help.' : null,
    hintLevel: turn.hint_level > 0 ? `Hint level ${turn.hint_level}` : null,
    mathJudgment: judgesWork ? mathJudgment(student) : null,
    reasoningJudgment: judgesWork ? reasoningJudgment(student) : null,
    independence: judgesWork ? independence(student) : null,
    diagnostic,
  };
}
