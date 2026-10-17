/**
 * Choice controls with programmatically exposed state.
 *
 * React Native Web does not translate `accessibilityState.checked` into `aria-checked`, so
 * assistive technology saw `role=radio` without a state. These controls set `aria-checked`
 * (and `aria-disabled`) explicitly alongside `accessibilityState`, so selection can be read
 * from the accessibility tree on web and native. Selection is also shown in words and with a
 * marker, never by color alone.
 */

import React from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import type { BoardTheme } from "../board/palette";

type KeyEventLike = { key?: string; preventDefault?: () => void };

/**
 * React Native Web activates a pressable on Enter, but only treats Space as a press for the
 * button role. Radios and switches are Space-operated, so Space is wired here. `onKeyDown`
 * is a web-only prop that native views never emit.
 */
function spaceActivates(onActivate: () => void, disabled: boolean) {
  return {
    onKeyDown: (event: KeyEventLike) => {
      if (event.key !== " " || disabled) return;
      event.preventDefault?.();
      onActivate();
    },
  };
}

export type RadioCardProps = {
  testID?: string;
  label: string;
  selected: boolean;
  disabled?: boolean;
  theme: BoardTheme;
  onPress: () => void;
  style?: StyleProp<ViewStyle>;
  children: React.ReactNode;
};

export function RadioCard({
  testID,
  label,
  selected,
  disabled = false,
  theme,
  onPress,
  style,
  children,
}: RadioCardProps) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="radio"
      accessibilityLabel={label}
      accessibilityState={{ selected, checked: selected, disabled }}
      aria-checked={selected}
      aria-disabled={disabled}
      disabled={disabled}
      onPress={onPress}
      {...spaceActivates(onPress, disabled)}
      style={[
        styles.card,
        {
          borderColor: selected ? theme.controlBackground : theme.controlEdge,
          backgroundColor: selected ? theme.boardGrain : theme.surface,
          opacity: disabled ? 0.8 : 1,
        },
        style,
      ]}
    >
      {children}
      <Text
        style={[
          styles.marker,
          { color: selected ? theme.labelText : theme.labelMuted },
        ]}
      >
        {selected ? "● Selected" : "○ Not selected"}
      </Text>
    </Pressable>
  );
}

export type ToggleRowProps = {
  testID?: string;
  label: string;
  description: string;
  value: boolean;
  disabled?: boolean;
  theme: BoardTheme;
  onChange: (next: boolean) => void;
};

export function ToggleRow({
  testID,
  label,
  description,
  value,
  disabled = false,
  theme,
  onChange,
}: ToggleRowProps) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="switch"
      accessibilityLabel={label}
      accessibilityHint={description}
      accessibilityState={{ checked: value, disabled }}
      aria-checked={value}
      aria-disabled={disabled}
      disabled={disabled}
      onPress={() => onChange(!value)}
      {...spaceActivates(() => onChange(!value), disabled)}
      style={[
        styles.toggle,
        { backgroundColor: theme.surface, borderColor: theme.controlEdge },
      ]}
    >
      <View style={styles.toggleText}>
        <Text style={[styles.toggleLabel, { color: theme.labelText }]}>
          {label}
        </Text>
        <Text style={[styles.toggleDescription, { color: theme.labelMuted }]}>
          {description}
        </Text>
      </View>
      <Text
        style={[
          styles.toggleState,
          { color: value ? theme.controlText : theme.labelText },
          value
            ? {
                backgroundColor: theme.controlBackground,
                borderColor: theme.controlBackground,
              }
            : { borderColor: theme.labelMuted },
        ]}
      >
        {value ? "On" : "Off"}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    minHeight: 44,
    padding: 14,
    gap: 8,
    borderRadius: 14,
    borderWidth: 2,
  },
  marker: { fontSize: 13, fontWeight: "600" },
  toggle: {
    minHeight: 52,
    paddingHorizontal: 14,
    paddingVertical: 8,
    gap: 12,
    flexDirection: "row",
    alignItems: "center",
    borderRadius: 12,
    borderWidth: 1,
  },
  toggleText: { flex: 1, gap: 2 },
  toggleLabel: { fontSize: 16, fontWeight: "700" },
  toggleDescription: { fontSize: 14, lineHeight: 19 },
  toggleState: {
    minWidth: 52,
    textAlign: "center",
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 10,
    borderWidth: 2,
    fontSize: 15,
    fontWeight: "700",
    overflow: "hidden",
  },
});
