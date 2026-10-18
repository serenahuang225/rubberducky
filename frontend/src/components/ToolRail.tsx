/**
 * The compact board tool rail: pen, erase, student undo/redo, and grouped tutor-move undo.
 * There is deliberately no brush-size or color picker — the session palette
 * and pen width are fixed. All targets are at least 44pt for comfortable touch.
 */

import React from "react";
import { StyleSheet, Text, View } from "react-native";
import { Eraser, Pencil, Redo2, RotateCcw, Undo2 } from "lucide-react-native";

import type { BoardTheme } from "../board/palette";
import { font, radius } from "../theme/tokens";

import type { BoardInputMode } from "./BoardInputLayer";
import { HoldPressable } from "./HoldPressable";

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
    <HoldPressable
      testID={testID}
      overview={hint ?? label}
      theme={theme}
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
    </HoldPressable>
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
        icon={<Pencil color={ink(mode === "draw")} size={22} strokeWidth={2.4} />}
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
        icon={<Eraser color={ink(mode === "erase")} size={22} strokeWidth={2.4} />}
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
        icon={<Undo2 color={theme.labelText} size={22} strokeWidth={2.4} />}
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
        icon={<Redo2 color={theme.labelText} size={22} strokeWidth={2.4} />}
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
        icon={<RotateCcw color={theme.labelText} size={22} strokeWidth={2.4} />}
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
  },
  button: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderWidth: 2,
    borderRadius: radius.pill,
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
