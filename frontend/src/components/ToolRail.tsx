/**
 * The compact board tool rail: pen, erase, student undo/redo, and grouped tutor-move undo.
 * There is deliberately no brush-size or color picker — the session palette
 * and pen width are fixed. All targets are at least 44pt for comfortable touch.
 */

import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import type { BoardTheme } from "../board/palette";
import { font } from "../theme/tokens";

import type { BoardInputMode } from "./BoardInputLayer";

export type ToolRailProps = {
  theme: BoardTheme;
  mode: BoardInputMode;
  undoAvailable: boolean;
  redoAvailable: boolean;
  tutorUndoAvailable: boolean;
  busy: boolean;
  layout?: "row" | "column";
  onModeChange: (mode: BoardInputMode) => void;
  onUndo: () => void;
  onRedo: () => void;
  onUndoTutorMove: () => void;
};

type ToolButtonProps = {
  label: string;
  accessibilityLabel?: string;
  hint?: string;
  active?: boolean;
  disabled?: boolean;
  theme: BoardTheme;
  icon: React.ReactNode;
  column: boolean;
  iconsOnly?: boolean;
  onPress: () => void;
  testID?: string;
};

function ToolIcon({
  color,
  d,
  filled = false,
}: {
  color: string;
  d: string;
  filled?: boolean;
}) {
  return (
    <Svg width={24} height={24} viewBox="0 0 16 16">
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

function ToolButton({
  label,
  accessibilityLabel,
  hint,
  active,
  disabled,
  theme,
  icon,
  column,
  iconsOnly = false,
  onPress,
  testID,
}: ToolButtonProps) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityHint={hint}
      accessibilityState={{
        disabled: disabled ?? false,
        selected: active ?? false,
      }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        column ? styles.buttonColumn : null,
        {
          backgroundColor: active
            ? theme.controlBackground
            : pressed
              ? theme.boardGrain
              : theme.surface,
          borderColor: active ? theme.controlBackground : theme.surfaceEdge,
          opacity: disabled ? 0.45 : 1,
        },
      ]}
    >
      <View accessible={false} importantForAccessibility="no-hide-descendants">
        {icon}
      </View>
      {iconsOnly ? null : (
        <Text
          numberOfLines={column ? 2 : 1}
          style={[
            styles.buttonText,
            column ? styles.buttonTextColumn : null,
            { color: active ? theme.controlText : theme.labelText },
          ]}
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}

export function ToolRail({
  theme,
  mode,
  undoAvailable,
  redoAvailable,
  tutorUndoAvailable,
  busy,
  layout = "row",
  onModeChange,
  onUndo,
  onRedo,
  onUndoTutorMove,
}: ToolRailProps) {
  const column = layout === "column";
  const ink = (active: boolean) =>
    active ? theme.controlText : theme.labelText;
  return (
    <View
      style={[
        styles.rail,
        column ? styles.railColumn : styles.railRow,
        column ? { borderLeftColor: theme.surfaceEdge } : null,
      ]}
      accessibilityLabel="Board tools"
    >
      <ToolButton
        testID="tool-pen"
        label="Pen"
        hint="Draw with the pen. Double-tap the board to undo"
        active={mode === "draw"}
        theme={theme}
        column={column}
        iconsOnly={column}
        icon={<ToolIcon color={ink(mode === "draw")} d="M2 14 L5 8 L11 2 L14 5 L8 11 Z M5 8 L8 11" />}
        onPress={() => onModeChange("draw")}
      />
      <ToolButton
        testID="tool-erase"
        label="Erase"
        hint="Tap one of your marks to erase it"
        active={mode === "erase"}
        theme={theme}
        column={column}
        iconsOnly={column}
        icon={<ToolIcon color={ink(mode === "erase")} d="M3 3 H13 V13 H3 Z" />}
        onPress={() => onModeChange("erase")}
      />
      <ToolButton
        testID="tool-undo"
        label="Undo"
        hint="Undo the last stroke. Shortcut: Command Z or Control Z"
        disabled={!undoAvailable || busy}
        theme={theme}
        column={column}
        iconsOnly={column}
        icon={<ToolIcon color={theme.labelText} d="M7 3 H3 V7 M3 3 C6 8 8 12 13 12" />}
        onPress={onUndo}
      />
      <ToolButton
        testID="tool-redo"
        label="Redo"
        hint="Redo the last undone stroke. Shortcut: Shift Command Z or Control Y"
        disabled={!redoAvailable || busy}
        theme={theme}
        column={column}
        iconsOnly={column}
        icon={<ToolIcon color={theme.labelText} d="M9 3 H13 V7 M13 3 C10 8 8 12 3 12" />}
        onPress={onRedo}
      />
      <ToolButton
        testID="tool-undo-tutor"
        label="Tutor undo"
        accessibilityLabel="Undo tutor marks"
        hint="Remove the tutor's latest marks as a group"
        disabled={!tutorUndoAvailable || busy}
        theme={theme}
        column={column}
        iconsOnly={column}
        icon={<ToolIcon color={theme.labelText} d="M3 3 H10 V6 H13 V13 H6 V10 H3 Z" />}
        onPress={onUndoTutorMove}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  rail: {
    alignItems: "center",
  },
  railRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  railColumn: {
    width: 52,
    gap: 2,
    alignItems: "stretch",
    paddingVertical: 8,
    borderLeftWidth: StyleSheet.hairlineWidth,
  },
  button: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderWidth: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  buttonColumn: {
    flexDirection: "column",
    paddingHorizontal: 4,
    gap: 2,
  },
  buttonText: {
    fontFamily: font.sans,
    fontSize: 14,
    fontWeight: "500",
  },
  buttonTextColumn: {
    fontSize: 11,
    lineHeight: 13,
    textAlign: "center",
  },
});
