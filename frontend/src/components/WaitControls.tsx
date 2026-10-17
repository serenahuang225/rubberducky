/**
 * Quiet waiting row: an optional "hint is ready" note and the bounded waiting-time setting.
 * The note is deliberately not a live region and never speaks or prompts; it only says that
 * a hint can be asked for. Help me works whether or not it is shown.
 */

import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { WaitPreference } from '../api/contracts';
import type { BoardTheme } from '../board/palette';

export const WAIT_STEP_SECONDS = 15;

export type WaitControlsProps = {
  theme: BoardTheme;
  hintAvailable: boolean;
  preference: WaitPreference | null;
  preferenceError: string | null;
  onChangeSeconds: (seconds: number) => void;
};

export function WaitControls({
  theme,
  hintAvailable,
  preference,
  preferenceError,
  onChangeSeconds,
}: WaitControlsProps) {
  const [open, setOpen] = useState(false);
  const text = { color: theme.labelText };
  const muted = { color: theme.labelMuted };
  const stepButton = [styles.stepButton, { backgroundColor: theme.controlBackground }];

  return (
    <View style={styles.wrapper}>
      <View style={styles.row}>
        {hintAvailable ? (
          <Text testID="quiet-hint" style={[styles.hintNote, muted]}>
            A hint is ready whenever you want it.
          </Text>
        ) : null}
        <Pressable
          testID="wait-settings-toggle"
          accessibilityRole="button"
          accessibilityLabel="Waiting time"
          accessibilityState={{ expanded: open, disabled: preference === null }}
          disabled={preference === null}
          onPress={() => setOpen((value) => !value)}
          style={[styles.toggle, { borderColor: theme.surfaceEdge }]}
        >
          <Text style={[styles.toggleText, text]}>Waiting time</Text>
        </Pressable>
      </View>
      {open && preference !== null ? (
        <View
          testID="wait-settings"
          style={[styles.panel, { backgroundColor: theme.surface, borderColor: theme.surfaceEdge }]}
        >
          <Text style={[styles.explain, muted]}>
            How long the board stays quiet before a hint is offered. Help me always works right away.
          </Text>
          <View style={styles.stepper}>
            <Pressable
              testID="wait-decrease"
              accessibilityRole="button"
              accessibilityLabel={`Wait ${WAIT_STEP_SECONDS} seconds less`}
              accessibilityState={{ disabled: preference.wait_seconds <= preference.min_seconds }}
              disabled={preference.wait_seconds <= preference.min_seconds}
              onPress={() => onChangeSeconds(preference.wait_seconds - WAIT_STEP_SECONDS)}
              style={stepButton}
            >
              <Text style={[styles.stepText, { color: theme.controlText }]}>−{WAIT_STEP_SECONDS}s</Text>
            </Pressable>
            <Text
              testID="wait-value"
              accessibilityLabel={`Waiting time ${preference.wait_seconds} seconds`}
              style={[styles.value, text]}
            >
              {`${preference.wait_seconds} seconds${preference.source === 'default' ? ' (default)' : ''}`}
            </Text>
            <Pressable
              testID="wait-increase"
              accessibilityRole="button"
              accessibilityLabel={`Wait ${WAIT_STEP_SECONDS} seconds more`}
              accessibilityState={{ disabled: preference.wait_seconds >= preference.max_seconds }}
              disabled={preference.wait_seconds >= preference.max_seconds}
              onPress={() => onChangeSeconds(preference.wait_seconds + WAIT_STEP_SECONDS)}
              style={stepButton}
            >
              <Text style={[styles.stepText, { color: theme.controlText }]}>+{WAIT_STEP_SECONDS}s</Text>
            </Pressable>
          </View>
          <Text style={[styles.explain, muted]}>
            {`Allowed range: ${preference.min_seconds}–${preference.max_seconds} seconds.`}
          </Text>
          {preferenceError !== null ? (
            <Text testID="wait-error" style={[styles.explain, { color: theme.danger }]}>
              {preferenceError}
            </Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { gap: 6 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  hintNote: { flex: 1, fontSize: 13, fontStyle: 'italic' },
  toggle: {
    minHeight: 44,
    paddingHorizontal: 12,
    borderRadius: 10,
    borderWidth: 1,
    justifyContent: 'center',
    marginLeft: 'auto',
  },
  toggleText: { fontSize: 13, fontWeight: '600' },
  panel: { gap: 8, padding: 12, borderRadius: 12, borderWidth: 1 },
  explain: { fontSize: 13, lineHeight: 18 },
  stepper: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  stepButton: {
    minHeight: 44,
    minWidth: 64,
    paddingHorizontal: 12,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepText: { fontSize: 15, fontWeight: '600' },
  value: { fontSize: 16, fontWeight: '600', minWidth: 130, textAlign: 'center' },
});
