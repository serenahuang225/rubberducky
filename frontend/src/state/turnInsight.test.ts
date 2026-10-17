import { tutorTurnResultSchema, type TutorTurnResult } from '../api/contracts';
import { METHOD_SLIP_TURN } from '../testing/teachingFixtures';

import { describeTurn } from './turnInsight';

function turn(overrides: Record<string, unknown>): TutorTurnResult {
  return tutorTurnResultSchema.parse({ ...METHOD_SLIP_TURN, ...overrides });
}

function withStudent(overrides: Record<string, unknown>): TutorTurnResult {
  return turn({ student_input: { ...METHOD_SLIP_TURN.student_input, ...overrides } });
}

describe('describeTurn', () => {
  it('keeps the mathematical and pedagogical judgments separate and denies independence', () => {
    const insight = describeTurn(turn({}));
    expect(insight.mathJudgment).toMatch(/solves the equation/i);
    expect(insight.reasoningJudgment).toMatch(/tentative/i);
    expect(insight.reasoningJudgment).toMatch(/left 3 unchanged/);
    expect(insight.reasoningJudgment).not.toMatch(/wrong|incorrect/i);
    expect(insight.independence).toMatch(/not counted as independent/i);
    expect(insight.independence).toMatch(/reasoning/i);
    expect(insight.representation).toBe('Outside factor');
    expect(insight.hintLevel).toBe('Hint level 1');
    expect(insight.disclosure).toBeNull();
    expect(insight.supportChange).toBeNull();
  });

  it('exposes the tentative hypothesis, alternatives, both source lists and the justification', () => {
    const { diagnostic } = describeTurn(turn({}));
    expect(diagnostic).not.toBeNull();
    expect(diagnostic?.hypothesisLabel).toBe('May be distributing to only the first term');
    expect(diagnostic?.confidencePercent).toBe(40);
    expect(diagnostic?.status).toBe('tentative');
    expect(diagnostic?.alternatives).toEqual(['A copying slip rather than a method gap']);
    expect(diagnostic?.supportingSourceIds).toEqual(['obs-1']);
    expect(diagnostic?.contradictingSourceIds).toEqual(['obs-0']);
    expect(diagnostic?.substantiveCounterevidence).toBe(false);
    expect(diagnostic?.justification).toMatch(/skips a term/);
    expect(diagnostic?.eligibilityNotes[0]).toMatch(/reasoning/i);
  });

  it('flags substantive counterevidence honestly', () => {
    const { diagnostic } = describeTurn(
      turn({
        hypothesis: { ...METHOD_SLIP_TURN.hypothesis, substantive_counterevidence: true },
      }),
    );
    expect(diagnostic?.substantiveCounterevidence).toBe(true);
  });

  it('discloses a revealed answer and a reduced-support move in plain words', () => {
    const insight = describeTurn(
      turn({ answer_revealed: true, support_change: 'reduced', hint_level: 4, representation: 'worked_step' }),
    );
    expect(insight.disclosure).toMatch(/showed/i);
    expect(insight.disclosure).toMatch(/assisted/i);
    expect(insight.supportChange).toMatch(/less help/i);
    expect(insight.representation).toBe('Worked step');
    expect(insight.hintLevel).toBe('Hint level 4');
  });

  it('says assisted when the server marked the observation assisted', () => {
    const insight = describeTurn(
      withStudent({
        assessment_independent: false,
        eligibility: [
          { ...METHOD_SLIP_TURN.student_input.eligibility[0], assisted: true, reason: 'hint_in_attempt' },
        ],
      }),
    );
    expect(insight.independence).toMatch(/assisted/i);
  });

  it('reports a verified independent step only when the server says so', () => {
    const insight = describeTurn(
      withStudent({
        classification: 'solution_with_reasoning',
        assessment_independent: true,
        reasoning_assessment: null,
        eligibility: [],
      }),
    );
    expect(insight.independence).toMatch(/counted as independent/i);
    expect(insight.independence).not.toMatch(/not counted/i);
    expect(insight.reasoningJudgment).toBeNull();
  });

  it('states an invalid step without calling the learner wrong', () => {
    const insight = describeTurn(
      withStudent({
        classification: 'invalid_step',
        assessment_independent: null,
        reasoning_assessment: null,
        verification: {
          ...METHOD_SLIP_TURN.student_input.verification,
          check: 'equation_step',
          status: 'invalid',
          reason: 'not_equivalent',
        },
      }),
    );
    expect(insight.mathJudgment).toMatch(/not equivalent/i);
    expect(insight.independence).toBeNull();
  });

  it('says an unchecked input could not be checked', () => {
    const insight = describeTurn(
      withStudent({
        verification: { ...METHOD_SLIP_TURN.student_input.verification, status: 'unknown', reason: 'candidate_not_checkable' },
      }),
    );
    expect(insight.mathJudgment).toMatch(/could not check/i);
  });

  it('shows nothing about work for a check-in or a help-button turn', () => {
    const checkIn = describeTurn(
      turn({
        kind: 'check_in',
        hypothesis: null,
        representation: null,
        hint_level: 0,
        decision_justification: null,
        student_input: {
          ...METHOD_SLIP_TURN.student_input,
          input_mode: 'check_in',
          classification: 'check_in',
          verification: null,
          reasoning_assessment: null,
          assessment_independent: null,
          eligibility: [],
        },
      }),
    );
    expect(checkIn).toEqual({
      representation: null,
      disclosure: null,
      supportChange: null,
      hintLevel: null,
      mathJudgment: null,
      reasoningJudgment: null,
      independence: null,
      diagnostic: null,
    });
  });
});
