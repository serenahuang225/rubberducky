import { fireEvent, render, waitFor } from "@testing-library/react-native";
import React from "react";
import { Platform } from "react-native";

import type { CheckInInput } from "../api/client";
import { getTheme } from "../board/palette";

import { QuestionIntake } from "./QuestionIntake";

jest.mock("expo-image-picker", () => ({
  requestCameraPermissionsAsync: async () => ({ granted: true }),
  launchCameraAsync: async () => ({
    canceled: false,
    assets: [{ base64: "abc123", uri: "file://question.jpg", width: 1280, height: 720 }],
  }),
  CameraType: { back: "back", front: "front" },
}));

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

  it("sends a photo from the device camera as the question", async () => {
    if (Platform.OS === "web") return;
    const { view, starts } = renderIntake();
    fireEvent.press(view.getByTestId("question-photo"));
    await waitFor(() => expect(view.getByText("Attached: Photo")).toBeTruthy());
    fireEvent.press(view.getByTestId("question-start"));
    expect(starts[0]?.image).toEqual({ mediaType: "image/jpeg", base64: "abc123" });
    expect(starts[0]?.practice).toBe(false);
  });
});
