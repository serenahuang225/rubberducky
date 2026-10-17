import { fireEvent, render, screen } from "@testing-library/react-native";
import React from "react";
import { Text } from "react-native";

import { getTheme } from "../board/palette";

import { RadioCard, ToggleRow } from "./ChoiceControls";

const theme = getTheme("paper");

describe("RadioCard", () => {
  it("exposes checked state programmatically, not only through its style", () => {
    const onPress = jest.fn();
    render(
      <RadioCard
        testID="r1"
        label="Gentle"
        selected
        theme={theme}
        onPress={onPress}
      >
        <Text>Gentle</Text>
      </RadioCard>,
    );
    const radio = screen.getByTestId("r1");
    expect(radio.props.accessibilityState).toMatchObject({
      checked: true,
      selected: true,
    });
    expect(screen.getByRole("radio", { checked: true })).toBeTruthy();
    expect(screen.queryByRole("radio", { checked: false })).toBeNull();
  });

  it("reports unchecked and disabled accurately and does not fire when disabled", () => {
    const onPress = jest.fn();
    render(
      <RadioCard
        testID="r2"
        label="Playful"
        selected={false}
        disabled
        theme={theme}
        onPress={onPress}
      >
        <Text>Playful</Text>
      </RadioCard>,
    );
    const radio = screen.getByTestId("r2");
    expect(radio.props.accessibilityState).toMatchObject({
      checked: false,
      disabled: true,
    });
    expect(screen.getByRole("radio", { checked: false })).toBeTruthy();
    fireEvent.press(radio);
    expect(onPress).not.toHaveBeenCalled();
  });

  it("calls onPress when enabled", () => {
    const onPress = jest.fn();
    render(
      <RadioCard
        testID="r3"
        label="Kai"
        selected={false}
        theme={theme}
        onPress={onPress}
      >
        <Text>Kai</Text>
      </RadioCard>,
    );
    fireEvent.press(screen.getByTestId("r3"));
    expect(onPress).toHaveBeenCalledTimes(1);
  });
});

describe("ToggleRow", () => {
  it("is a named switch whose state is exposed and spelled out in words", () => {
    const onChange = jest.fn();
    render(
      <ToggleRow
        testID="t1"
        label="Sound"
        description="Tutor sounds"
        value
        theme={theme}
        onChange={onChange}
      />,
    );
    const toggle = screen.getByRole("switch", { name: "Sound" });
    expect(toggle.props.accessibilityState).toMatchObject({ checked: true });
    expect(screen.getByText("On")).toBeTruthy();
    fireEvent.press(toggle);
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it("says Off in words when off", () => {
    render(
      <ToggleRow
        testID="t2"
        label="Haptics"
        description="d"
        value={false}
        theme={theme}
        onChange={() => undefined}
      />,
    );
    expect(screen.getByText("Off")).toBeTruthy();
    expect(screen.getByRole("switch", { checked: false })).toBeTruthy();
  });
});

describe("Space key", () => {
  it("selects a radio and flips a switch, and ignores other keys", () => {
    const select = jest.fn();
    const flip = jest.fn();
    const preventDefault = jest.fn();
    render(
      <>
        <RadioCard
          testID="k-radio"
          label="Playful"
          selected={false}
          theme={theme}
          onPress={select}
        >
          <Text>Playful</Text>
        </RadioCard>
        <ToggleRow
          testID="k-switch"
          label="Sound"
          description="d"
          value={false}
          theme={theme}
          onChange={flip}
        />
      </>,
    );
    fireEvent(screen.getByTestId("k-radio"), "keyDown", {
      key: " ",
      preventDefault,
    });
    expect(select).toHaveBeenCalledTimes(1);
    expect(preventDefault).toHaveBeenCalled();
    fireEvent(screen.getByTestId("k-radio"), "keyDown", {
      key: "a",
      preventDefault,
    });
    expect(select).toHaveBeenCalledTimes(1);
    fireEvent(screen.getByTestId("k-switch"), "keyDown", {
      key: " ",
      preventDefault,
    });
    expect(flip).toHaveBeenCalledWith(true);
  });
});
