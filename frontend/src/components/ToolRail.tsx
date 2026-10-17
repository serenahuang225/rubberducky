/**
 * The compact board tool rail: erase, student undo/redo, grouped tutor-move undo and the
 * theme toggle. There is deliberately no brush-size or color picker — the session palette
 * and pen width are fixed. All targets are at least 44pt for comfortable touch.
 */

import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { BoardTheme, BoardThemeName } from "../board/palette";

import type { BoardInputMode } from "./BoardInputLayer";

export type ToolRailProps = {
  theme: BoardTheme;
  themeName: BoardThemeName;
  mode: BoardInputMode;
  undoAvailable: boolean;
  redoAvailable: boolean;
  tutorUndoAvailable: boolean;
  busy: boolean;
  onModeChange: (mode: BoardInputMode) => void;
  onUndo: () => void;
  onRedo: () => void;
  onUndoTutorMove: () => void;
  onToggleTheme: () => void;
};

type ToolButtonProps = {
  label: string;
  hint?: string;
  active?: boolean;
  disabled?: boolean;
  theme: BoardTheme;
  onPress: () => void;
  testID?: string;
};

function ToolButton({
  label,
  hint,
  active,
  disabled,
  theme,
  onPress,
  testID,
}: ToolButtonProps) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      accessibilityState={{
        disabled: disabled ?? false,
        selected: active ?? false,
      }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: active
            ? theme.controlBackground
            : pressed
              ? theme.boardGrain
              : theme.surface,
          borderColor: theme.surfaceEdge,
          opacity: disabled ? 0.5 : 1,
        },
      ]}
    >
      <Text
        style={[
          styles.buttonText,
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
  onModeChange,
  onUndo,
  onRedo,
  onUndoTutorMove,
  onToggleTheme,
}: ToolRailProps) {
  return (
    <View
      style={[
        styles.rail,
        { backgroundColor: theme.surface, borderColor: theme.surfaceEdge },
      ]}
      accessibilityLabel="Board tools"
    >
      <ToolButton
        testID="tool-pen"
        label="Pen"
        hint="Draw with the one student pen"
        active={mode === "draw"}
        theme={theme}
        onPress={() => onModeChange("draw")}
      />
      <ToolButton
        testID="tool-erase"
        label="Erase"
        hint="Tap one of your marks to erase it"
        active={mode === "erase"}
        theme={theme}
        onPress={() => onModeChange("erase")}
      />
      <ToolButton
        testID="tool-undo"
        label="Undo"
        disabled={!undoAvailable || busy}
        theme={theme}
        onPress={onUndo}
      />
      <ToolButton
        testID="tool-redo"
        label="Redo"
        disabled={!redoAvailable || busy}
        theme={theme}
        onPress={onRedo}
      />
      <ToolButton
        testID="tool-undo-tutor"
        label="Undo tutor marks"
        hint="Remove the tutor's latest marks as a group"
        disabled={!tutorUndoAvailable || busy}
        theme={theme}
        onPress={onUndoTutorMove}
      />
      <ToolButton
        testID="tool-theme"
        label={themeName === "paper" ? "Chalkboard" : "Paper"}
        hint="Switch the board theme; your colors stay distinct"
        theme={theme}
        onPress={onToggleTheme}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  rail: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    padding: 8,
    borderRadius: 12,
    borderWidth: 1,
    alignItems: "center",
  },
  button: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 14,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonText: {
    fontSize: 15,
    fontWeight: "600",
  },
});
