import { render, screen } from "@testing-library/react-native";
import React from "react";

import { getTheme } from "../board/palette";
import { deriveAvatarStatus, type AvatarInputs } from "../state/avatarStatus";

import { TutorAvatar } from "./TutorAvatar";

const BASE: AvatarInputs = {
  busy: false,
  connectionLost: false,
  unsavedChanges: 0,
  failed: false,
  waiting: false,
  media: null,
  mediaAllowed: { listening: true, speaking: true },
};

const renderAvatar = (patch: Partial<AvatarInputs>) =>
  render(
    <TutorAvatar
      appearance="animal"
      theme={getTheme("paper")}
      tutorName="Duck · Mildly sassy"
      status={deriveAvatarStatus({ ...BASE, ...patch })}
    />,
  );

describe("TutorAvatar", () => {
  it("shows the real state in words next to the figure and in its accessible name", () => {
    renderAvatar({ busy: true });
    expect(screen.getByTestId("avatar-status")).toHaveTextContent("Thinking");
    expect(
      screen.getByLabelText(/Duck · Mildly sassy avatar: Thinking\./),
    ).toBeTruthy();
  });

  it("reports idle without implying listening or competence", () => {
    renderAvatar({});
    expect(screen.getByTestId("avatar-status")).toHaveTextContent("Ready");
    expect(
      screen.queryByText(/listening|speaking|understand|expert/i),
    ).toBeNull();
  });

  it.each([
    [{ connectionLost: true }, "Reconnecting"],
    [{ failed: true }, "Something went wrong"],
    [{ waiting: true }, "Waiting for you"],
  ])("shows %j as %s", (patch, text) => {
    renderAvatar(patch);
    expect(screen.getByTestId("avatar-status")).toHaveTextContent(text);
  });

  it("labels simulated listening as simulated", () => {
    renderAvatar({ media: { kind: "listening", source: "simulated" } });
    expect(screen.getByTestId("avatar-status")).toHaveTextContent(
      "Listening (simulated)",
    );
  });

  it("is a polite live region so a state change is announced once", () => {
    renderAvatar({ busy: true });
    expect(
      screen.getByTestId("avatar-status").props.accessibilityLiveRegion,
    ).toBe("polite");
  });
});
