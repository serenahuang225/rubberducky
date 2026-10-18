/**
 * Quiet waiting row: an optional "hint is ready" note and the bounded waiting-time setting.
 * The note is deliberately not a live region and never speaks or prompts; it only says that
 * a hint can be asked for. Help me works whether or not it is shown.
 */

import React, { useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import type { WaitPreference } from '../api/contracts';
import type { BoardTheme } from '../board/palette';
import { type } from '../theme/tokens';

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
          style={[
            styles.toggle,
            { backgroundColor: theme.surface, borderColor: theme.surfaceEdge },
          ]}
        >
          <Svg width={18} height={18} viewBox="0 0 16 16">
            <Path
              d="M8 2.2 A5.8 5.8 0 1 0 8 13.8 A5.8 5.8 0 1 0 8 2.2 M8 5 V8 H10.5"
              fill="none"
              stroke={theme.labelText}
              strokeWidth={1.5}
              strokeLinejoin="miter"
              strokeLinecap="square"
            />
          </Svg>
        </Pressable>
      </View>
      <Modal
        visible={open && preference !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setOpen(false)}
      >
        {preference !== null ? (
          <View style={styles.backdrop}>
            <Pressable
              accessible={false}
              importantForAccessibility="no"
              onPress={() => setOpen(false)}
              style={styles.backdropHit}
            />
            <View
              testID="wait-settings"
              accessibilityViewIsModal
              style={[
                styles.dialog,
                { backgroundColor: theme.board, borderColor: theme.surfaceEdge },
              ]}
            >
              <View style={styles.dialogHeader}>
                <Text style={[styles.dialogTitle, text]}>Waiting time</Text>
                <Pressable
                  testID="wait-settings-close"
                  accessibilityRole="button"
                  accessibilityLabel="Close waiting time"
                  onPress={() => setOpen(false)}
                  style={[styles.close, { borderColor: theme.controlEdge }]}
                >
                  <Text style={[styles.closeText, text]}>Close</Text>
                </Pressable>
              </View>
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
          </View>
        ) : null}
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { gap: 6 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  hintNote: { ...type.small, flex: 1 },
  toggle: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 10,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backdrop: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20,
    backgroundColor: 'rgba(44, 40, 36, 0.45)',
  },
  backdropHit: { ...StyleSheet.absoluteFillObject },
  dialog: {
    width: '100%',
    maxWidth: 420,
    gap: 12,
    padding: 20,
    borderWidth: 1,
    zIndex: 1,
  },
  dialogHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  dialogTitle: type.heading,
  close: {
    minHeight: 44,
    paddingHorizontal: 16,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  closeText: type.control,
  explain: type.small,
  stepper: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  stepButton: {
    minHeight: 44,
    minWidth: 64,
    paddingHorizontal: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepText: type.control,
  value: { ...type.control, minWidth: 130, textAlign: 'center' },
});
