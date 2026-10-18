/**
 * Compact current-prompt bar: the tutor's latest words and what to do next.
 * The board, not a transcript, stays the primary surface.
 */

import React from "react";
import { StyleSheet, Text, View } from "react-native";

import type { BoardTheme } from "../board/palette";
import { type } from "../theme/tokens";

export type PromptBarProps = {
  theme: BoardTheme;
  /** Current problem statement, when one is posed. */
  problemStatement: string | null;
  /** Latest committed tutor utterance. */
  tutorMessage: string | null;
  /** What the tutor expects the learner to do next. */
  expectedAction: string | null;
  /** Short truthful status, e.g. "Thinking…" or "Reconnecting…". */
  status: string | null;
};

export function PromptBar({
  theme,
  problemStatement,
  tutorMessage,
  expectedAction,
  status,
}: PromptBarProps) {
  return (
    <View style={styles.bar} accessibilityLiveRegion="polite">
      {status !== null ? (
        <Text
          testID="prompt-status"
          numberOfLines={1}
          style={[styles.status, { color: theme.labelMuted }]}
        >
          {status}
        </Text>
      ) : null}
      {problemStatement !== null ? (
        <Text
          testID="prompt-problem"
          numberOfLines={1}
          style={[styles.problem, { color: theme.labelText }]}
        >
          {problemStatement}
        </Text>
      ) : null}
      {tutorMessage !== null ? (
        <Text
          testID="prompt-tutor"
          numberOfLines={1}
          style={[styles.message, { color: theme.labelText }]}
        >
          {tutorMessage}
        </Text>
      ) : null}
      {expectedAction !== null ? (
        <Text
          testID="prompt-expected"
          numberOfLines={1}
          style={[styles.expected, { color: theme.labelMuted }]}
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
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    minWidth: 160,
  },
  status: type.small,
  problem: { ...type.prompt, flexShrink: 1 },
  message: { ...type.body, flexShrink: 2 },
  expected: { ...type.small, flexShrink: 1 },
});
