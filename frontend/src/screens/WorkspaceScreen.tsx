/**
 * The primary workspace screen: the shared whiteboard is the main surface, with a small
 * avatar/status chip, a compact prompt bar, the tool rail and a typed-step row. Check-in
 * is a short card, not a chat. All work goes through the real API via useWorkspace; waiting
 * (Still thinking, the quiet hint and the wait preference) goes through useWaitAgency and
 * never submits work or speaks on a timer.
 */

import React, { useCallback, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import type { ApiClient } from '../api/client';
import type { TutorConfiguration } from '../api/contracts';
import { getTheme, type BoardThemeName } from '../board/palette';
import { loadThemeName, saveThemeName } from '../storage/credentials';
import type { BoardInputMode } from '../components/BoardInputLayer';
import { AvatarFigure } from '../components/AvatarFigure';
import { PromptBar } from '../components/PromptBar';
import { TeachingContext } from '../components/TeachingContext';
import { ToolRail } from '../components/ToolRail';
import { WaitControls } from '../components/WaitControls';
import { WhiteboardCanvas } from '../components/WhiteboardCanvas';
import { useWaitAgency } from '../state/useWaitAgency';
import { useWorkspace } from '../state/useWorkspace';

import { APPEARANCE_INFO, PERSONALITY_INFO } from './OnboardingScreen';

export type WorkspaceScreenProps = {
  client: ApiClient;
  sessionId: string;
  persona: TutorConfiguration;
  displayName: string;
  /** Called after the current session was durably ended, so the app can start fresh. */
  onSessionEnded: () => void;
};

const ENERGY_OPTIONS = [
  { value: 'ready' as const, label: 'Ready to go' },
  { value: 'a_bit_tired' as const, label: 'A bit tired' },
  { value: 'tired' as const, label: 'Really tired' },
];

function stillThinkingStatusText(status: 'idle' | 'sent' | 'failed'): string | null {
  if (status === 'sent') return 'Take your time — your tutor will wait.';
  if (status === 'failed') {
    return 'Could not tell your tutor you are still thinking, but nothing changed. Take your time.';
  }
  return null;
}

export function WorkspaceScreen({ client, sessionId, persona, displayName, onSessionEnded }: WorkspaceScreenProps) {
  const workspace = useWorkspace(client, sessionId);
  const wait = useWaitAgency(client, sessionId, {
    enabled: workspace.phase === 'ready' && workspace.state !== null && workspace.state.current_problem !== null,
    // Real activity (a turn or a stroke) moves these revisions; typing and idling do not.
    activityKey: `${workspace.state?.session.revision ?? 'none'}:${workspace.scene?.scene_revision ?? 'none'}`,
  });
  const [themeName, setThemeName] = useState<BoardThemeName>('paper');
  const [mode, setMode] = useState<BoardInputMode>('draw');
  const [draft, setDraft] = useState('');
  const [ending, setEnding] = useState(false);
  const [endError, setEndError] = useState<string | null>(null);

  React.useEffect(() => {
    let active = true;
    loadThemeName().then((name) => {
      if (active && (name === 'paper' || name === 'slate')) {
        setThemeName(name);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const theme = useMemo(() => getTheme(themeName), [themeName]);
  const toggleTheme = useCallback(() => {
    setThemeName((current) => {
      const next = current === 'paper' ? 'slate' : 'paper';
      void saveThemeName(next);
      return next;
    });
  }, []);

  const submitDraft = useCallback(() => {
    const text = draft.trim();
    if (text.length === 0) return;
    setDraft('');
    wait.clearStillThinkingNote();
    void workspace.submitWork(text);
  }, [draft, wait, workspace]);

  const askHelp = useCallback(() => {
    wait.clearStillThinkingNote();
    void workspace.requestHelp();
  }, [wait, workspace]);

  const markStillThinking = useCallback(() => {
    // Explicit wait metadata only: no work, check-in, help, scene or evidence effect.
    void wait.stillThinking();
  }, [wait]);

  const finishSession = useCallback(async () => {
    if (ending) return;
    setEnding(true);
    setEndError(null);
    try {
      await client.endSession(sessionId);
      onSessionEnded();
    } catch (error) {
      setEndError(
        error instanceof Error
          ? `The session could not be ended: ${error.message}`
          : 'The session could not be ended. Your work is saved; try again.',
      );
    } finally {
      setEnding(false);
    }
  }, [client, ending, onSessionEnded, sessionId]);

  if (workspace.phase === 'loading') {
    return (
      <View style={[styles.centered, { backgroundColor: theme.board }]}>
        <ActivityIndicator color={theme.studentInk} />
        <Text style={[styles.loadingText, { color: theme.labelMuted }]}>Setting up your board…</Text>
      </View>
    );
  }

  if (workspace.phase === 'failed' || workspace.state === null || workspace.scene === null) {
    return (
      <View style={[styles.centered, { backgroundColor: theme.board }]}>
        <Text style={[styles.errorTitle, { color: theme.labelText }]}>The board could not load.</Text>
        <Text style={[styles.loadingText, { color: theme.labelMuted }]}>
          {workspace.errorMessage ?? 'Something went wrong. Your work is safe.'}
        </Text>
        <Pressable
          testID="workspace-retry"
          accessibilityRole="button"
          accessibilityLabel="Try again"
          onPress={workspace.retry}
          style={[styles.retryButton, { backgroundColor: theme.controlBackground }]}
        >
          <Text style={[styles.retryText, { color: theme.controlText }]}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  const personaInfo = APPEARANCE_INFO[persona.appearance];
  const styleInfo = PERSONALITY_INFO[persona.personality];
  const scene = workspace.scene;

  return (
    <KeyboardAvoidingView
      style={[styles.page, { backgroundColor: theme.boardGrain }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.header}>
        <AvatarFigure
          appearance={persona.appearance}
          size={44}
          label={`Your tutor ${personaInfo.name}, ${styleInfo.name} style`}
        />
        <View style={styles.headerText}>
          <Text style={[styles.tutorName, { color: theme.labelText }]}>
            {personaInfo.name} · {styleInfo.name}
          </Text>
          <Text style={[styles.headerSub, { color: theme.labelMuted }]}>
            {workspace.state.pace === 'lighter' ? 'Taking it gently today' : 'Working with'} {displayName}
          </Text>
          {workspace.providerLabel !== null ? (
            <Text
              testID="provider-label"
              accessibilityLabel={
                workspace.providerIsMock
                  ? `Demo mode: ${workspace.providerLabel}`
                  : `Tutor provider: ${workspace.providerLabel}`
              }
              style={[styles.providerLabel, { color: theme.labelMuted }]}
            >
              {workspace.providerIsMock
                ? `Demo mode: ${workspace.providerLabel}`
                : workspace.providerLabel}
            </Text>
          ) : null}
        </View>
        <Pressable
          testID="finish-session"
          accessibilityRole="button"
          accessibilityLabel="Finish for today"
          accessibilityHint="Ends this session; a fresh session starts next time"
          accessibilityState={{ disabled: ending || workspace.busyLabel !== null }}
          disabled={ending || workspace.busyLabel !== null}
          onPress={() => void finishSession()}
          style={[
            styles.finishButton,
            { backgroundColor: theme.surface, borderColor: theme.surfaceEdge },
          ]}
        >
          <Text style={[styles.finishText, { color: theme.labelText }]}>
            {ending ? 'Ending…' : 'Finish for today'}
          </Text>
        </Pressable>
      </View>

      {endError !== null ? (
        <Text testID="finish-error" style={[styles.errorText, { color: theme.danger }]}>
          {endError}
        </Text>
      ) : null}

      <PromptBar
        theme={theme}
        problemStatement={workspace.state.current_problem?.statement ?? null}
        tutorMessage={workspace.lastUtterance}
        expectedAction={workspace.lastExpectedAction}
        status={workspace.busyLabel ?? stillThinkingStatusText(wait.stillThinkingStatus)}
      />

      {workspace.canInterrupt ? (
        <Pressable
          testID="stop-reply"
          accessibilityRole="button"
          accessibilityLabel="Stop reply"
          accessibilityHint="Stops the tutor's reply; your work stays saved"
          onPress={() => void workspace.interrupt()}
          style={[
            styles.stopButton,
            { backgroundColor: theme.surface, borderColor: theme.surfaceEdge },
          ]}
        >
          <Text style={[styles.actionText, { color: theme.labelText }]}>Stop reply</Text>
        </Pressable>
      ) : null}

      <TeachingContext theme={theme} turn={workspace.lastTurn} />

      {workspace.errorMessage !== null ? (
        <Text testID="workspace-error" style={[styles.errorText, { color: theme.danger }]}>
          {workspace.errorMessage}
        </Text>
      ) : null}

      {workspace.pendingCount > 0 ? (
        <View
          testID="save-notice"
          accessibilityLiveRegion="polite"
          style={[styles.saveNotice, { backgroundColor: theme.surface, borderColor: theme.surfaceEdge }]}
        >
          <Text style={[styles.saveNoticeText, { color: theme.labelText }]}>
            {workspace.memoryOnlyCount > 0
              ? 'Some of your ink is not saved and could not be kept on this device. It is held only in memory while this screen stays open. Use Retry now once the tutor is reachable.'
              : workspace.pendingCount === 1
                ? 'One change is not saved yet. It is kept on this device and will save itself when the tutor is reachable.'
                : `${workspace.pendingCount} changes are not saved yet. They are kept on this device and will save when the tutor is reachable.`}
          </Text>
          <Pressable
            testID="save-retry"
            accessibilityRole="button"
            accessibilityLabel="Retry saving now"
            disabled={workspace.busyLabel !== null}
            onPress={() => void workspace.retryPending()}
            style={[styles.saveRetryButton, { backgroundColor: theme.controlBackground }]}
          >
            <Text style={[styles.saveRetryText, { color: theme.controlText }]}>Retry now</Text>
          </Pressable>
        </View>
      ) : null}

      {workspace.needsCheckIn ? (
        <View
          style={[styles.checkInCard, { backgroundColor: theme.surface, borderColor: theme.surfaceEdge }]}
        >
          <Text style={[styles.checkInTitle, { color: theme.labelText }]}>
            Quick check-in before we start
          </Text>
          <Text style={[styles.checkInSub, { color: theme.labelMuted }]}>
            How are you feeling? This only shapes today’s pace.
          </Text>
          <View style={styles.checkInRow}>
            {ENERGY_OPTIONS.map((option) => (
              <Pressable
                key={option.value}
                testID={`checkin-${option.value}`}
                accessibilityRole="button"
                accessibilityLabel={option.label}
                disabled={workspace.busyLabel !== null}
                onPress={() => void workspace.checkIn(option.value)}
                style={[styles.checkInButton, { backgroundColor: theme.controlBackground }]}
              >
                <Text style={[styles.checkInButtonText, { color: theme.controlText }]}>
                  {option.label}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>
      ) : null}

      <View style={styles.boardArea}>
        <WhiteboardCanvas
          testID="whiteboard"
          objects={scene.objects}
          currentStatementId={workspace.state.current_problem?.statement_object_id ?? null}
          pendingStrokes={workspace.pendingStrokes}
          theme={theme}
          mode={mode}
          inputDisabled={workspace.busyLabel !== null}
          onStroke={(points) => void workspace.commitStroke(points)}
          onEraseAt={(objectId) => {
            setMode('draw');
            void workspace.eraseObject(objectId);
          }}
        />
      </View>

      <ToolRail
        theme={theme}
        themeName={themeName}
        mode={mode}
        undoAvailable={scene.student_undo_available}
        redoAvailable={scene.student_redo_available}
        tutorUndoAvailable={scene.tutor_move_undo_available}
        busy={workspace.busyLabel !== null}
        onModeChange={setMode}
        onUndo={() => void workspace.undo()}
        onRedo={() => void workspace.redo()}
        onUndoTutorMove={() => void workspace.undoTutorMove()}
        onToggleTheme={toggleTheme}
      />

      <View style={styles.inputRow}>
        <TextInput
          testID="typed-step-input"
          accessibilityLabel="Type your next step"
          placeholder="Type your next step, e.g. 2x + 6 = 14"
          placeholderTextColor={theme.labelMuted}
          value={draft}
          onChangeText={(text) => {
            setDraft(text);
            wait.clearStillThinkingNote();
          }}
          onSubmitEditing={submitDraft}
          editable={!workspace.needsCheckIn && workspace.busyLabel === null}
          style={[
            styles.stepInput,
            {
              backgroundColor: theme.surface,
              borderColor: theme.surfaceEdge,
              color: theme.labelText,
            },
          ]}
        />
        <Pressable
          testID="submit-step"
          accessibilityRole="button"
          accessibilityLabel="Submit step"
          accessibilityState={{ disabled: workspace.busyLabel !== null }}
          disabled={workspace.needsCheckIn || workspace.busyLabel !== null}
          onPress={submitDraft}
          style={[styles.actionButton, { backgroundColor: theme.controlBackground }]}
        >
          <Text style={[styles.actionText, { color: theme.controlText }]}>Submit</Text>
        </Pressable>
        <Pressable
          testID="help-me"
          accessibilityRole="button"
          accessibilityLabel="Help me"
          accessibilityHint={wait.hintAvailable ? 'A hint is ready when you want it' : 'Asks for a hint right now'}
          disabled={workspace.needsCheckIn || workspace.busyLabel !== null}
          onPress={askHelp}
          style={[styles.actionButton, { backgroundColor: theme.surface, borderColor: theme.surfaceEdge, borderWidth: 1 }]}
        >
          <Text style={[styles.actionText, { color: theme.labelText }]}>Help me</Text>
        </Pressable>
        <Pressable
          testID="still-thinking"
          accessibilityRole="button"
          accessibilityLabel="Still thinking"
          disabled={workspace.needsCheckIn}
          onPress={markStillThinking}
          style={[styles.actionButton, { backgroundColor: theme.surface, borderColor: theme.surfaceEdge, borderWidth: 1 }]}
        >
          <Text style={[styles.actionText, { color: theme.labelText }]}>Still thinking</Text>
        </Pressable>
      </View>

      <WaitControls
        theme={theme}
        hintAvailable={wait.hintAvailable}
        preference={wait.preference}
        preferenceError={wait.preferenceError}
        onChangeSeconds={(seconds) => void wait.setWaitSeconds(seconds)}
      />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, padding: 12, gap: 10 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 },
  loadingText: { fontSize: 16 },
  errorTitle: { fontSize: 20, fontWeight: '700' },
  errorText: { fontSize: 14 },
  saveNotice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 12,
    borderWidth: 1,
  },
  saveNoticeText: { flex: 1, fontSize: 14, lineHeight: 20 },
  saveRetryButton: {
    minHeight: 44,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveRetryText: { fontSize: 15, fontWeight: '600' },
  retryButton: {
    minHeight: 44,
    paddingHorizontal: 20,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  retryText: { fontSize: 16, fontWeight: '600' },
  header: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  headerText: { flex: 1 },
  tutorName: { fontSize: 16, fontWeight: '700' },
  headerSub: { fontSize: 13 },
  providerLabel: { fontSize: 12, fontStyle: 'italic', marginTop: 2 },
  finishButton: {
    minHeight: 44,
    paddingHorizontal: 14,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  finishText: { fontSize: 14, fontWeight: '600' },
  checkInCard: { padding: 16, borderRadius: 14, borderWidth: 1, gap: 8 },
  checkInTitle: { fontSize: 18, fontWeight: '700' },
  checkInSub: { fontSize: 14 },
  checkInRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  checkInButton: {
    minHeight: 44,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkInButtonText: { fontSize: 15, fontWeight: '600' },
  boardArea: { flex: 1, minHeight: 240 },
  inputRow: { flexDirection: 'row', gap: 8, alignItems: 'center', flexWrap: 'wrap' },
  stepInput: {
    flexGrow: 1,
    minWidth: 220,
    minHeight: 48,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    fontSize: 16,
    fontFamily: 'monospace',
  },
  stopButton: {
    alignSelf: 'flex-start',
    minHeight: 44,
    paddingHorizontal: 16,
    justifyContent: 'center',
    borderRadius: 12,
    borderWidth: 1,
  },
  actionButton: {
    minHeight: 48,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionText: { fontSize: 15, fontWeight: '600' },
});
