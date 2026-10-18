import { fireEvent, render } from "@testing-library/react-native";
import React from "react";

import type { TutorTurnResult } from "../api/contracts";
import { getTheme } from "../board/palette";

import { TutorChat } from "./TutorChat";
import { messagesFromTurns } from "./chatMessages";

const theme = getTheme("paper");

function turn(partial: Partial<TutorTurnResult> & Pick<TutorTurnResult, "turn_id">): TutorTurnResult {
  return {
    schema_version: "tutor-turn-result.v1",
    session_id: "s1",
    kind: "work",
    status: "committed",
    base_revision: 1,
    session_revision: 2,
    cancellation_epoch: 0,
    provider: { name: "claude", is_mock: false, label: "Claude" },
    student_input: null,
    current_problem: null,
    pace: "standard",
    action_type: "step_feedback",
    utterance: null,
    expected_student_action: null,
    hypothesis: null,
    hint_level: 0,
    answer_revealed: false,
    representation: null,
    support_change: "none",
    decision_justification: null,
    drawings: [],
    rejections: [],
    replayed: false,
    ...partial,
  };
}

describe("messagesFromTurns", () => {
  it("keeps the question, the learner's step, and a good-job reply", () => {
    const messages = messagesFromTurns([
      turn({
        turn_id: "t1",
        kind: "check_in",
        current_problem: {
          problem_id: "p1",
          attempt_id: "a1",
          statement: "Solve 4x + 1 = 9",
          kind: "practice",
          concept_id: "concept.linear_equations",
          statement_object_id: "obj-1",
        },
        utterance: "Subtract 1 from both sides.",
      }),
      turn({
        turn_id: "t2",
        student_input: {
          input_mode: "typed",
          text: "x = 2",
          classification: "solution_with_reasoning",
          step_id: "step-1",
          observation_ids: [],
          assessment_id: null,
          assessment_kind: null,
          assessment_independent: null,
          verification: null,
          reasoning_assessment: null,
          eligibility: [],
        },
        utterance: "Good job! x = 2 makes the equation true.",
      }),
      turn({ turn_id: "t3", status: "failed", utterance: "ignored" }),
    ]);
    expect(messages.map((message) => message.text)).toEqual([
      "Solve 4x + 1 = 9",
      "Subtract 1 from both sides.",
      "x = 2",
      "Good job! x = 2 makes the equation true.",
    ]);
  });
});

describe("TutorChat", () => {
  it("sends a reply and marks a solved turn", () => {
    const sent: string[] = [];
    const view = render(
      <TutorChat
        theme={theme}
        messages={messagesFromTurns([
          turn({ turn_id: "t1", utterance: "Good job! You solved it." }),
        ])}
        draft="ok"
        busy={false}
        canReply
        thinking={null}
        onChangeDraft={() => undefined}
        onSend={() => sent.push("ok")}
      />,
    );
    expect(view.getByTestId("chat-good-job")).toBeTruthy();
    fireEvent.press(view.getByTestId("chat-send"));
    expect(sent).toEqual(["ok"]);
  });
});
