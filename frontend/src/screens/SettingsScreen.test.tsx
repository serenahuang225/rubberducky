import {
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react-native";
import React from "react";

import {
  accessibilityPreferencesSchema,
  personaStateSchema,
} from "../api/contracts";
import { getTheme } from "../board/palette";
import {
  ACCESSIBILITY_DEFAULTS,
  PERSONA_STATE_LOCKED,
  PERSONA_STATE_OPEN,
} from "../testing/agencyFixtures";
import type { LearnerSettings } from "../state/useLearnerSettings";

import { SettingsScreen } from "./SettingsScreen";

function makeSettings(patch: Partial<LearnerSettings> = {}): LearnerSettings {
  return {
    persona: personaStateSchema.parse(PERSONA_STATE_LOCKED),
    accessibility: accessibilityPreferencesSchema.parse(ACCESSIBILITY_DEFAULTS),
    loaded: true,
    loadError: null,
    comfortError: null,
    accessibilityError: null,
    pairError: null,
    savingPair: false,
    refresh: jest.fn(async () => undefined),
    setComfort: jest.fn(async () => undefined),
    patchAccessibility: jest.fn(async () => undefined),
    changePair: jest.fn(async () => "saved" as const),
    ...patch,
  };
}

const renderSettings = (
  settings: LearnerSettings,
  extra: Partial<React.ComponentProps<typeof SettingsScreen>> = {},
) =>
  render(
    <SettingsScreen
      settings={settings}
      theme={getTheme("paper")}
      onClose={() => undefined}
      onOpenMemory={() => undefined}
      timeZone="UTC"
      locale="en-US"
      {...extra}
    />,
  );

describe("SettingsScreen", () => {
  it("re-reads the server lock state when it opens", () => {
    const settings = makeSettings();
    renderSettings(settings);
    expect(settings.refresh).toHaveBeenCalledTimes(1);
  });

  it("explains a locked persona with the server instant and keeps comfort and accessibility enabled", () => {
    const settings = makeSettings();
    renderSettings(settings);
    const availability = screen.getByTestId("persona-availability");
    expect(availability).toHaveTextContent(/2026-10-17 12:30 UTC/);
    expect(availability).toHaveTextContent(
      /comfort and accessibility can still change now/i,
    );

    expect(screen.queryByText("Sunny the duck")).toBeNull();
    expect(screen.queryByText("Rowan")).toBeNull();
    expect(screen.queryByText("Kai")).toBeNull();
    for (const option of ["vincent", "zeeshan", "tony", "janelle", "mary"]) {
      expect(
        screen.getByTestId(`settings-personality-${option}`).props
          .accessibilityState.disabled,
      ).toBe(true);
    }
    expect(
      screen.getByTestId("settings-save-persona").props.accessibilityState
        .disabled,
    ).toBe(true);

    expect(
      screen.getByTestId("settings-comfort-neutral_supportive").props
        .accessibilityState.disabled,
    ).toBe(false);
    expect(
      screen.getByTestId("settings-sound").props.accessibilityState.disabled,
    ).toBe(false);
    expect(
      screen.getByTestId("settings-animation-reduced").props.accessibilityState
        .disabled,
    ).toBe(false);
  });

  it("keeps how much help in settings and applies it immediately", () => {
    const onChangeHandhold = jest.fn();
    renderSettings(makeSettings(), { handhold: "balanced", onChangeHandhold });
    expect(screen.getByTestId("settings-handhold-balanced").props.accessibilityState.checked).toBe(true);
    fireEvent.press(screen.getByTestId("settings-handhold-guided"));
    expect(onChangeHandhold).toHaveBeenCalledWith("guided");
    fireEvent.press(screen.getByTestId("settings-handhold-hands_off"));
    expect(onChangeHandhold).toHaveBeenCalledWith("hands_off");
  });

  it("applies comfort immediately through setComfort while locked", () => {
    const settings = makeSettings();
    renderSettings(settings);
    fireEvent.press(screen.getByTestId("settings-comfort-neutral_supportive"));
    expect(settings.setComfort).toHaveBeenCalledWith("neutral_supportive");
    expect(settings.changePair).not.toHaveBeenCalled();
  });

  it("exposes which comfort and animation choice is checked, one per group", () => {
    renderSettings(makeSettings());
    const comfort = screen.getByTestId("settings-comfort-group");
    expect(
      within(comfort).getAllByRole("radio", { checked: true }),
    ).toHaveLength(1);
    expect(within(comfort).getByRole("radio", { checked: true })).toBe(
      screen.getByTestId("settings-comfort-none"),
    );
    const motion = screen.getByTestId("settings-motion-group");
    expect(within(motion).getByRole("radio", { checked: true })).toBe(
      screen.getByTestId("settings-animation-system"),
    );
  });

  it("shows the current duck as checked even while locked", () => {
    renderSettings(makeSettings());
    expect(screen.queryByTestId("settings-appearance-animal")).toBeNull();
    expect(
      screen.getByTestId("settings-personality-zeeshan").props
        .accessibilityState.checked,
    ).toBe(true);
    expect(
      screen.getByTestId("settings-personality-janelle").props.accessibilityState
        .checked,
    ).toBe(false);
  });

  it("toggles sound, haptics, text-only and captions through the preferences route", () => {
    const settings = makeSettings();
    renderSettings(settings);
    fireEvent.press(screen.getByTestId("settings-sound"));
    expect(settings.patchAccessibility).toHaveBeenLastCalledWith({
      sound_enabled: false,
    });
    fireEvent.press(screen.getByTestId("settings-haptics"));
    expect(settings.patchAccessibility).toHaveBeenLastCalledWith({
      haptics_enabled: false,
    });
    fireEvent.press(screen.getByTestId("settings-text-only"));
    expect(settings.patchAccessibility).toHaveBeenLastCalledWith({
      text_only: true,
    });
    fireEvent.press(screen.getByTestId("settings-captions"));
    expect(settings.patchAccessibility).toHaveBeenLastCalledWith({
      captions_enabled: false,
    });
    fireEvent.press(screen.getByTestId("settings-animation-off"));
    expect(settings.patchAccessibility).toHaveBeenLastCalledWith({
      animation: "off",
    });
  });

  it("lets an unlocked learner pick a new duck and save it, only when it actually differs", () => {
    const settings = makeSettings({
      persona: personaStateSchema.parse(PERSONA_STATE_OPEN),
    });
    renderSettings(settings);
    expect(screen.getByTestId("persona-availability")).toHaveTextContent(
      /can change now/i,
    );
    expect(
      screen.getByTestId("settings-save-persona").props.accessibilityState
        .disabled,
    ).toBe(true);
    fireEvent.press(screen.getByTestId("settings-personality-janelle"));
    expect(
      screen.getByTestId("settings-save-persona").props.accessibilityState
        .disabled,
    ).toBe(false);
    fireEvent.press(screen.getByTestId("settings-save-persona"));
    expect(settings.changePair).toHaveBeenCalledWith("animal", "janelle");
  });

  it("shows load and save problems in words", () => {
    renderSettings(
      makeSettings({
        persona: null,
        loadError: "Your saved settings could not be loaded.",
        accessibilityError: "That setting could not be saved: down",
        comfortError: "Comfort could not be changed: down",
      }),
    );
    expect(screen.getByText(/could not be loaded/)).toBeTruthy();
    expect(screen.getByText(/That setting could not be saved/)).toBeTruthy();
    expect(screen.getByText(/Comfort could not be changed/)).toBeTruthy();
  });

  it("offers the private memory view and a named way back", () => {
    const onOpenMemory = jest.fn();
    const onClose = jest.fn();
    renderSettings(makeSettings(), { onOpenMemory, onClose });
    fireEvent.press(
      screen.getByRole("button", { name: "Open private memory" }),
    );
    expect(onOpenMemory).toHaveBeenCalled();
    fireEvent.press(screen.getByRole("button", { name: "Back to board" }));
    expect(onClose).toHaveBeenCalled();
  });
});
