/**
 * The header shows only what to do next. The question lives on the board,
 * and the tutor's words live in the chat.
 */

import React from "react";
import { StyleSheet, Text, View } from "react-native";

import type { BoardTheme } from "../board/palette";
import { type } from "../theme/tokens";

export type PromptBarProps = {
  theme: BoardTheme;
  /** Short truthful status, e.g. "Thinking…" or "Reconnecting…". */
  status: string | null;
};

export function PromptBar({ theme, status }: PromptBarProps) {
  if (status === null) return null;
  return (
    <View style={styles.bar} accessibilityLiveRegion="polite">
      <Text testID="prompt-status" style={[styles.status, { color: theme.labelText }]}>
        {status}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { paddingBottom: 4 },
  status: type.body,
});
