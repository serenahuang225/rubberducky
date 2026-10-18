/**
 * Quiet waiting row: an optional "hint is ready" note and the bounded waiting-time setting.
 * The note is deliberately not a live region and never speaks or prompts; it only says that
 * a hint can be asked for. Help me works whether or not it is shown.
 */

import React, { useEffect, useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { Timer } from 'lucide-react-native';

import type { WaitPreference, WaitState } from '../api/contracts';
import type { BoardTheme } from '../board/palette';
import { radius, type } from '../theme/tokens';

import { HoldPressable } from './HoldPressable';

export const WAIT_STEP_SECONDS = 15;

export type WaitControlsProps = {
  theme: BoardTheme;
  hintAvailable: boolean;
  waitState?: WaitState | null;
  partnerName?: string;
  preference: WaitPreference | null;
  preferenceError: string | null;
  onChangeSeconds: (seconds: number) => void;
};

export function WaitControls({
  theme,
  hintAvailable,
  waitState = null,
  partnerName = "Your thinking partner",
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
            {`${partnerName}: Want a hint? It’s ready whenever you are.`}
          </Text>
        ) : waitState !== null ? (
          <WaitCountdown
            key={`${waitState.session_id}:${waitState.now}:${waitState.quiet_hint_at}`}
            theme={theme}
            state={waitState}
            partnerName={partnerName}
          />
        ) : null}
        <HoldPressable
          testID="wait-settings-toggle"
          overview="Sets how long the board stays quiet before a hint is offered. Help me still works right away."
          theme={theme}
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
          <Timer color={theme.labelText} size={18} strokeWidth={2.4} />
        </HoldPressable>
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

function WaitCountdown({ theme, state, partnerName }: { theme: BoardTheme; state: WaitState; partnerName: string }) {
  // Use the server's time difference, rather than comparing against the device clock.
  const duration = Date.parse(state.quiet_hint_at) - Date.parse(state.now);
  const initialMs = Number.isFinite(duration) ? Math.max(0, duration) : 0;
  const [remainingMs, setRemainingMs] = useState(initialMs);
  useEffect(() => {
    if (initialMs === 0) return;
    const started = Date.now();
    const timer = setInterval(() => {
      const next = Math.max(0, initialMs - (Date.now() - started));
      setRemainingMs(next);
      if (next === 0) clearInterval(timer);
    }, 1000);
    return () => clearInterval(timer);
  }, [initialMs]);
  const seconds = Math.ceil(remainingMs / 1000);
  const fraction = Math.min(1, Math.max(0, 1 - remainingMs / Math.max(1000, state.wait_seconds * 1000)));
  return (
    <View testID="wait-countdown" style={styles.countdown}>
      <Text style={[styles.hintNote, { color: theme.labelMuted }]}>
        {seconds > 0
          ? `Hint offer in ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
          : `${partnerName}: Want a hint?`}
      </Text>
      <View
        accessible
        accessibilityRole="progressbar"
        accessibilityLabel={`${partnerName}'s next hint offer`}
        accessibilityValue={{ min: 0, max: 100, now: Math.round(fraction * 100), text: `${seconds} seconds remaining` }}
        style={[styles.progressTrack, { backgroundColor: theme.surfaceEdge }]}
      >
        <View style={{ width: `${fraction * 100}%`, height: '100%', borderRadius: 3, backgroundColor: theme.tutorInk }} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { gap: 6 },
  countdown: { flex: 1, maxWidth: 230, gap: 5 },
  progressTrack: { height: 4, borderRadius: 3, overflow: "hidden" },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  hintNote: { ...type.small, flex: 1 },
  toggle: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 10,
    borderWidth: 2,
    borderRadius: radius.pill,
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
  backdropHit: { ...StyleSheet.absoluteFill },
  dialog: {
    width: '100%',
    maxWidth: 420,
    gap: 12,
    padding: 24,
    borderRadius: radius.lg,
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
    borderRadius: radius.pill,
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
    borderRadius: radius.pill,
    paddingHorizontal: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepText: type.control,
  value: { ...type.control, minWidth: 130, textAlign: 'center' },
});
