import { fireEvent, render } from "@testing-library/react-native";
import React from "react";

import type { CheckInInput } from "../api/client";
import { getTheme } from "../board/palette";

import { QuestionIntake } from "./QuestionIntake";

const theme = getTheme("paper");

function renderIntake() {
  const starts: CheckInInput[] = [];
  const view = render(
    <QuestionIntake
      theme={theme}
      busy={false}
      onStart={(input) => {
        starts.push(input);
      }}
    />,
  );
  return { view, starts };
}

describe("QuestionIntake", () => {
  it("sends the typed question", () => {
    const { view, starts } = renderIntake();
    fireEvent.changeText(view.getByTestId("question-input"), "Solve 4x + 1 = 9");
    fireEvent.press(view.getByTestId("question-start"));
    expect(starts).toEqual([
      {
        energy: null,
        questionText: "Solve 4x + 1 = 9",
        image: null,
        practice: false,
      },
    ]);
  });

  it("can start the built-in practice problem instead", () => {
    const { view, starts } = renderIntake();
    fireEvent.press(view.getByTestId("question-practice"));
    expect(starts[0]?.practice).toBe(true);
    expect(starts[0]?.questionText).toBeUndefined();
  });

  it("does not start until there is a question", () => {
    const { view, starts } = renderIntake();
    fireEvent.press(view.getByTestId("question-start"));
    expect(starts).toEqual([]);
  });
});
