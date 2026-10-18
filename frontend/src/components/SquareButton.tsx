/**
 * The one workspace button: a square, the same surface and edge as Memory.
 * The accessible name carries the meaning; the mark is only a picture of it.
 */

import React from "react";
import { Pressable, StyleSheet, Text, type StyleProp, type ViewStyle } from "react-native";
import Svg, { Path } from "react-native-svg";

import type { BoardTheme } from "../board/palette";
import { type } from "../theme/tokens";

export function MarkIcon({
  color,
  d,
  filled = false,
}: {
  color: string;
  d: string;
  filled?: boolean;
}) {
  return (
    <Svg width={18} height={18} viewBox="0 0 16 16">
      <Path
        d={d}
        fill={filled ? color : "none"}
        stroke={filled ? "none" : color}
        strokeWidth={1.5}
        strokeLinejoin="miter"
        strokeLinecap="square"
      />
    </Svg>
  );
}

export const marks = {
  help: "M6 6.2 C6 4.4 7 3.2 8 3.2 C9.3 3.2 10.4 4.3 10.4 5.4 C10.4 6.8 8 7.1 8 8.6 M8 11.4 V11.6",
  memory: "M4 2 H12 V14 L8 11 L4 14 Z",
  settings: "M3 4 H13 M3 8 H13 M3 12 H13 M6 4 V2 M10 8 V6 M7 12 V10",
  finish: "M3 3 H7 V13 H3 Z M9 8 H14 M11.5 5.5 L14 8 L11.5 10.5",
  type: "M3 3 H13 M8 3 V13 M5 13 H11",
  wait: "M8 2.2 A5.8 5.8 0 1 0 8 13.8 A5.8 5.8 0 1 0 8 2.2 M8 5 V8 H10.5",
  voice: "M6 2.5 H10 V8 A2 2 0 0 1 6 8 Z M4 7.5 A4 4 0 0 0 12 7.5 M8 11.5 V14",
  moon: "M14 1.6 C6.2 2.6 2 5.8 2 8 C2 12.2 6.4 14.8 14 15.2 C9.4 13.4 7.2 10.8 7.2 8 C7.2 5.2 9.6 3.2 14 1.6 Z",
  sun: "M8 1.6 V3.4 M8 12.6 V14.4 M1.6 8 H3.4 M12.6 8 H14.4 M3.5 3.5 L4.8 4.8 M11.2 11.2 L12.5 12.5 M12.5 3.5 L11.2 4.8 M4.8 11.2 L3.5 12.5 M8 5.2 A2.8 2.8 0 1 0 8 10.8 A2.8 2.8 0 1 0 8 5.2",
} as const;

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
    <Pressable
      testID={testID}
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
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 10,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 6,
  },
  label: type.meta,
});
