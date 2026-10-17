/**
 * Compact, read-only context for the tutor's current move: which approach it used, whether
 * an answer was disclosed, whether support was reduced, the separate math and reasoning
 * judgments, and an optional "Why this move?" inspector for the tentative hypothesis, its
 * alternatives and the actual sources. It never edits anything; the board stays primary.
 */

import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { TutorTurnResult } from '../api/contracts';
import type { BoardTheme } from '../board/palette';
import { describeTurn, type DiagnosticView } from '../state/turnInsight';
import { font, type } from '../theme/tokens';

export type TeachingContextProps = {
  theme: BoardTheme;
  turn: TutorTurnResult | null;
};

const MAX_SOURCES_SHOWN = 6;

/** Short, traceable form of a stored source id; the full id stays in the accessible label. */
function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

function sourceList(ids: readonly string[]): string {
  if (ids.length === 0) return 'none';
  const shown = ids.slice(0, MAX_SOURCES_SHOWN).map(shortId).join(', ');
  return ids.length > MAX_SOURCES_SHOWN ? `${shown} +${ids.length - MAX_SOURCES_SHOWN} more` : shown;
}

function DiagnosticPanel({ theme, diagnostic }: { theme: BoardTheme; diagnostic: DiagnosticView }) {
  const muted = { color: theme.labelMuted };
  const text = { color: theme.labelText };
  return (
    <View
      testID="diagnostic-panel"
      style={[styles.panel, { borderColor: theme.surfaceEdge }]}
      accessibilityLabel="Why this move, read-only"
    >
      {diagnostic.hypothesisLabel !== null ? (
        <>
          <Text testID="diagnostic-hypothesis" style={[styles.panelLine, text]}>
            {`Tentative reading: ${diagnostic.hypothesisLabel}`}
          </Text>
          <Text testID="diagnostic-confidence" style={[styles.panelLine, muted]}>
            {`Confidence about ${diagnostic.confidencePercent}% (${diagnostic.status ?? 'tentative'})`}
          </Text>
          {diagnostic.alternatives.length > 0 ? (
            <View testID="diagnostic-alternatives">
              <Text style={[styles.panelLine, muted]}>Other possibilities:</Text>
              {diagnostic.alternatives.map((alternative) => (
                <Text key={alternative} style={[styles.panelLine, text]}>
                  {`• ${alternative}`}
                </Text>
              ))}
            </View>
          ) : null}
          <Text
            testID="diagnostic-sources"
            accessibilityLabel={`Supporting sources: ${diagnostic.supportingSourceIds.join(', ') || 'none'}`}
            style={[styles.panelLine, styles.mono, muted]}
          >
            {`Supporting sources (${diagnostic.supportingSourceIds.length}): ${sourceList(diagnostic.supportingSourceIds)}`}
          </Text>
          <Text
            testID="diagnostic-counter-sources"
            accessibilityLabel={`Counter-evidence sources: ${diagnostic.contradictingSourceIds.join(', ') || 'none'}`}
            style={[styles.panelLine, styles.mono, muted]}
          >
            {`Counter-evidence sources (${diagnostic.contradictingSourceIds.length}): ${sourceList(diagnostic.contradictingSourceIds)}`}
          </Text>
          {diagnostic.substantiveCounterevidence ? (
            <Text testID="diagnostic-counterevidence" style={[styles.panelLine, text]}>
              Independent work argued against this reading, so it is held more loosely now.
            </Text>
          ) : null}
        </>
      ) : (
        <Text style={[styles.panelLine, muted]}>No hypothesis was formed for this move.</Text>
      )}
      {diagnostic.justification !== null ? (
        <Text testID="diagnostic-justification" style={[styles.panelLine, text]}>
          {`Why this move: ${diagnostic.justification}`}
        </Text>
      ) : null}
      {diagnostic.eligibilityNotes.map((note) => (
        <Text key={note} style={[styles.panelLine, muted]}>
          {note}
        </Text>
      ))}
      <Text style={[styles.footnote, muted]}>
        Read-only. These are tentative readings of this session’s work, not facts about you.
      </Text>
    </View>
  );
}

export function TeachingContext({ theme, turn }: TeachingContextProps) {
  // Open state belongs to one turn, so a newer turn starts collapsed again.
  const [openFor, setOpenFor] = useState<string | null>(null);
  const turnId = turn?.turn_id ?? null;
  const open = turnId !== null && openFor === turnId;

  if (turn === null) return null;
  const insight = describeTurn(turn);
  const hasChips =
    insight.representation !== null ||
    insight.hintLevel !== null ||
    insight.disclosure !== null ||
    insight.supportChange !== null;
  const hasJudgments =
    insight.mathJudgment !== null ||
    insight.reasoningJudgment !== null ||
    insight.independence !== null;
  if (!hasChips && !hasJudgments && insight.diagnostic === null) return null;

  const text = { color: theme.labelText };
  const muted = { color: theme.labelMuted };
  return (
    <View
      testID="teaching-context"
      style={[styles.box, { borderTopColor: theme.surfaceEdge }]}
    >
      {hasChips ? (
        <View style={styles.chips}>
          {insight.representation !== null ? (
            <Text
              testID="teaching-representation"
              style={[styles.chip, { borderColor: theme.surfaceEdge }, text]}
            >
              {`Approach: ${insight.representation}`}
            </Text>
          ) : null}
          {insight.hintLevel !== null ? (
            <Text testID="teaching-hint-level" style={[styles.chip, { borderColor: theme.surfaceEdge }, muted]}>
              {insight.hintLevel}
            </Text>
          ) : null}
          {insight.supportChange !== null ? (
            <Text testID="teaching-support" style={[styles.chip, { borderColor: theme.surfaceEdge }, text]}>
              {insight.supportChange}
            </Text>
          ) : null}
        </View>
      ) : null}
      {insight.disclosure !== null ? (
        <Text testID="teaching-disclosure" style={[styles.line, text]}>
          {insight.disclosure}
        </Text>
      ) : null}
      {insight.mathJudgment !== null ? (
        <Text testID="teaching-math" style={[styles.line, text]}>
          {insight.mathJudgment}
        </Text>
      ) : null}
      {insight.reasoningJudgment !== null ? (
        <Text testID="teaching-reasoning" style={[styles.line, text]}>
          {insight.reasoningJudgment}
        </Text>
      ) : null}
      {insight.independence !== null ? (
        <Text testID="teaching-independence" style={[styles.line, muted]}>
          {insight.independence}
        </Text>
      ) : null}
      {insight.diagnostic !== null ? (
        <>
          <Pressable
            testID="diagnostic-toggle"
            accessibilityRole="button"
            accessibilityLabel={open ? 'Hide why this move' : 'Why this move?'}
            accessibilityState={{ expanded: open }}
            onPress={() => setOpenFor(open ? null : turnId)}
            style={[styles.toggle, { borderColor: theme.controlEdge }]}
          >
            <Text style={[styles.toggleText, text]}>{open ? 'Hide details' : 'Why this move?'}</Text>
          </Pressable>
          {open ? <DiagnosticPanel theme={theme} diagnostic={insight.diagnostic} /> : null}
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: 6, paddingTop: 8, borderTopWidth: StyleSheet.hairlineWidth },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { ...type.meta, paddingVertical: 2 },
  line: type.small,
  toggle: {
    alignSelf: 'flex-start',
    minHeight: 44,
    paddingHorizontal: 12,
    borderWidth: 1,
    justifyContent: 'center',
  },
  toggleText: type.meta,
  panel: { gap: 4, paddingTop: 6, borderTopWidth: StyleSheet.hairlineWidth },
  panelLine: type.small,
  mono: { fontFamily: font.sans, fontSize: 12, lineHeight: 16 },
  footnote: { ...type.meta, fontWeight: '400', marginTop: 2 },
});
