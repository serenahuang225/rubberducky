/**
 * Compact current-prompt bar: the tutor's latest words and what to do next.
 * The board, not a transcript, stays the primary surface.
 */

import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { BoardTheme } from '../board/palette';

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

export function PromptBar({ theme, problemStatement, tutorMessage, expectedAction, status }: PromptBarProps) {
  return (
    <View
      style={[styles.bar, { backgroundColor: theme.surface, borderColor: theme.surfaceEdge }]}
      accessibilityLiveRegion="polite"
    >
      {status !== null ? (
        <Text testID="prompt-status" style={[styles.status, { color: theme.labelMuted }]}>
          {status}
        </Text>
      ) : null}
      {problemStatement !== null ? (
        <Text testID="prompt-problem" style={[styles.problem, { color: theme.labelText }]}>
          {problemStatement}
        </Text>
      ) : null}
      {tutorMessage !== null ? (
        <Text testID="prompt-tutor" style={[styles.message, { color: theme.labelText }]}>
          {tutorMessage}
        </Text>
      ) : null}
      {expectedAction !== null ? (
        <Text testID="prompt-expected" style={[styles.expected, { color: theme.labelMuted }]}>
          Next: {expectedAction}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    gap: 4,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 12,
    borderWidth: 1,
  },
  status: { fontSize: 13, fontStyle: 'italic' },
  problem: { fontSize: 18, fontWeight: '700', fontFamily: 'monospace' },
  message: { fontSize: 16, lineHeight: 22 },
  expected: { fontSize: 14 },
});
