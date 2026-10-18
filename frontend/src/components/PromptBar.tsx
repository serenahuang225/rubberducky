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
  /** What the tutor expects the learner to do next. */
  expectedAction: string | null;
  /** Short truthful status, e.g. "Thinking…" or "Reconnecting…". */
  status: string | null;
};

export function PromptBar({ theme, expectedAction, status }: PromptBarProps) {
  if (status === null && expectedAction === null) return null;
  return (
    <View style={styles.bar} accessibilityLiveRegion="polite">
      {status !== null ? (
        <Text
          testID="prompt-status"
          numberOfLines={2}
          style={[styles.status, { color: theme.labelText }]}
        >
          {status}
        </Text>
      ) : null}
      {expectedAction !== null ? (
        <Text
          testID="prompt-expected"
          numberOfLines={2}
          style={[styles.expected, { color: theme.labelText }]}
        >
          Next: {expectedAction}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flex: 1,
    minWidth: 120,
    justifyContent: "center",
    gap: 2,
  },
  status: type.small,
  expected: type.body,
});
