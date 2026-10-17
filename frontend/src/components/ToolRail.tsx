/**
 * The compact board tool rail: erase, student undo/redo, grouped tutor-move undo and the
 * theme toggle. There is deliberately no brush-size or color picker — the session palette
 * and pen width are fixed. All targets are at least 44pt for comfortable touch.
 */

import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import type { BoardTheme, BoardThemeName } from "../board/palette";
import { font } from "../theme/tokens";

import type { BoardInputMode } from "./BoardInputLayer";

export type ToolRailProps = {
  theme: BoardTheme;
  themeName: BoardThemeName;
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
  onToggleTheme: () => void;
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
              : "transparent",
          borderColor: active ? theme.controlBackground : "transparent",
          opacity: disabled ? 0.45 : 1,
        },
      ]}
    >
      <View accessible={false} importantForAccessibility="no-hide-descendants">
        {icon}
      </View>
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
    </Pressable>
  );
}

export function ToolRail({
  theme,
  themeName,
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
  onToggleTheme,
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
        icon={<ToolIcon color={theme.labelText} d="M3 3 H10 V6 H13 V13 H6 V10 H3 Z" />}
        onPress={onUndoTutorMove}
      />
      <ToolButton
        testID="tool-theme"
        label={themeName === "paper" ? "Dark mode" : "Light mode"}
        hint="Switch the board theme; your colors stay distinct"
        theme={theme}
        column={column}
        icon={
          themeName === "paper" ? (
            <ToolIcon
              color={theme.labelText}
              filled
              d="M14 1.6 C6.2 2.6 2 5.8 2 8 C2 12.2 6.4 14.8 14 15.2 C9.4 13.4 7.2 10.8 7.2 8 C7.2 5.2 9.6 3.2 14 1.6 Z"
            />
          ) : (
            <ToolIcon
              color={theme.labelText}
              d="M8 1.6 V3.4 M8 12.6 V14.4 M1.6 8 H3.4 M12.6 8 H14.4 M3.5 3.5 L4.8 4.8 M11.2 11.2 L12.5 12.5 M12.5 3.5 L11.2 4.8 M4.8 11.2 L3.5 12.5 M8 5.2 A2.8 2.8 0 1 0 8 10.8 A2.8 2.8 0 1 0 8 5.2"
            />
          )
        }
        onPress={onToggleTheme}
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
    width: 84,
    gap: 2,
    alignItems: "stretch",
    paddingVertical: 8,
    borderLeftWidth: StyleSheet.hairlineWidth,
  },
  button: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 10,
    paddingVertical: 6,
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
