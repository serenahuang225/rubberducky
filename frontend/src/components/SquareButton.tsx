/**
 * The workspace button. The accessible name carries the meaning; the icon is only a picture of it.
 */

import React from "react";
import { StyleSheet, Text, type StyleProp, type ViewStyle } from "react-native";

import type { BoardTheme } from "../board/palette";
import { radius, type } from "../theme/tokens";

import { HoldPressable } from "./HoldPressable";

export function SquareButton({
  theme,
  label,
  hint,
  testID,
  disabled,
  selected,
  onPress,
  icon,
  children,
  style,
}: {
  theme: BoardTheme;
  label: string;
  hint?: string;
  testID?: string;
  disabled?: boolean;
  selected?: boolean;
  onPress: () => void;
  icon?: React.ReactNode;
  children?: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <HoldPressable
      testID={testID}
      overview={hint ?? label}
      theme={theme}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      accessibilityState={{ disabled: disabled ?? false, selected }}
      disabled={disabled}
      onPress={onPress}
      style={[
        styles.button,
        {
          backgroundColor: theme.surface,
          borderColor: theme.surfaceEdge,
          opacity: disabled ? 0.45 : 1,
        },
        style,
      ]}
    >
      {icon}
      {typeof children === "string" ? (
        <Text style={[styles.label, { color: theme.labelText }]}>{children}</Text>
      ) : (
        children
      )}
    </HoldPressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 14,
    borderWidth: 2,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 6,
  },
  label: type.meta,
});
