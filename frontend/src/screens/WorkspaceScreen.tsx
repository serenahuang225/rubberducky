/**
 * The primary workspace screen. The board holds the question and the figure, the chat
 * holds the conversation and the typed reply, and the header keeps the next step.
 * Drawing stays on the pen. All work goes through the real API via useWorkspace; waiting
 * (Still thinking, the quiet hint and the wait preference) goes through useWaitAgency and
 * never submits work or speaks on a timer.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import {
  Bookmark,
  CircleHelp,
  Flag,
  Hourglass,
  Moon,
  Settings,
  Sun,
} from "lucide-react-native";

import type { ApiClient } from "../api/client";
import type {
  AccessibilityPreferences,
  HandholdMode,
  LearnerControl,
  TutorConfiguration,
  TutorTurnResult,
} from "../api/contracts";
import { getTheme, type BoardTheme, type BoardThemeName } from "../board/palette";
import { loadThemeName, saveThemeName } from "../storage/credentials";
import type { BoardInputMode } from "../components/BoardInputLayer";
import { MediaPanel } from "../components/MediaPanel";
import { PromptBar } from "../components/PromptBar";
import { TutorChat } from "../components/TutorChat";
import { messagesFromTurns } from "../components/chatMessages";
import { QuestionIntake } from "../components/QuestionIntake";
import { SquareButton } from "../components/SquareButton";
import { TeachingContext } from "../components/TeachingContext";
import { TutorAvatar } from "../components/TutorAvatar";
import { ToolRail } from "../components/ToolRail";
import { WaitControls } from "../components/WaitControls";
import { WhiteboardCanvas } from "../components/WhiteboardCanvas";
import { pulseHaptic } from "../feedback/haptics";
import { defaultMediaServices } from "../media/defaultMediaServices";
import type { MediaServices } from "../media/mediaServices";
import { useMedia } from "../media/useMedia";
import { resolveFeedback, resolveMotion } from "../feedback/preferences";
import { useSystemReducedMotion } from "../feedback/useSystemReducedMotion";
import { deriveAvatarStatus } from "../state/avatarStatus";
import { DEFAULT_ACCESSIBILITY } from "../state/useLearnerSettings";
import { useProgressiveReveal } from "../state/useProgressiveReveal";
import { useWaitAgency } from "../state/useWaitAgency";
import { useWorkspace } from "../state/useWorkspace";
import { radius, type } from "../theme/tokens";

import { APPEARANCE_INFO, PERSONALITY_INFO } from "./OnboardingScreen";

export type WorkspaceScreenProps = {
  client: ApiClient;
  sessionId: string;
  persona: TutorConfiguration;
  displayName: string;
  /** Called after the current session was durably ended, so the app can start fresh. */
  onSessionEnded: () => void;
  /** The learner's motion, haptics and text-only choices; defaults apply until loaded. */
  accessibility?: AccessibilityPreferences;
  /** Settings or memory is covering the board: marks stop animating and show in full. */
  boardHidden?: boolean;
  onOpenSettings?: () => void;
  onOpenMemory?: () => void;
  /** Lets the app shell match the canvas color, including the safe area. */
  onThemeChange?: (theme: BoardTheme) => void;
  /** Platform capture and speech drivers; the real device drivers unless a test supplies fakes. */
  media?: MediaServices;
  /** How much help the tutor gives. Chosen in Settings; balanced when unset. */
  handhold?: HandholdMode;
};

function stillThinkingStatusText(
  status: "idle" | "sent" | "failed",
): string | null {
  if (status === "sent") return "Take your time — your tutor will wait.";
  if (status === "failed") {
    return "Could not tell your tutor you are still thinking, but nothing changed. Take your time.";
  }
  return null;
}

export function WorkspaceScreen({
  client,
  sessionId,
  persona,
  displayName,
  onSessionEnded,
  accessibility = DEFAULT_ACCESSIBILITY,
  boardHidden = false,
  onOpenSettings,
  onOpenMemory,
  onThemeChange,
  media: mediaServices,
  handhold = "balanced",
}: WorkspaceScreenProps) {
  const workspace = useWorkspace(client, sessionId);
  const systemReducedMotion = useSystemReducedMotion();
  const motion = resolveMotion(accessibility.animation, systemReducedMotion);
  const feedback = resolveFeedback(accessibility);
  const sceneObjects = workspace.scene?.objects;
  const presentIds = useMemo(
    () => new Set((sceneObjects ?? []).map((object) => object.id)),
    [sceneObjects],
  );
  const hiddenIds = useProgressiveReveal({
    sessionId,
    turn: workspace.lastTurn,
    generation: workspace.turnGeneration,
    epoch: workspace.state?.session.cancellation_epoch ?? null,
    attemptId: workspace.state?.current_problem?.attempt_id ?? null,
    presentIds,
    motion,
    suspended: boardHidden,
  });
  const lastTurnId = workspace.lastTurn?.turn_id ?? null;
  const hapticsRef = React.useRef(feedback.haptics);
  React.useEffect(() => {
    hapticsRef.current = feedback.haptics;
  }, [feedback.haptics]);
  React.useEffect(() => {
    // One quiet pulse per newly committed reply, judged by the choice in force right then.
    if (lastTurnId !== null) {
      void pulseHaptic({ haptics_enabled: hapticsRef.current }, "tutor_reply");
    }
  }, [lastTurnId]);
  const wait = useWaitAgency(client, sessionId, {
    enabled:
      workspace.phase === "ready" &&
      workspace.state !== null &&
      workspace.state.current_problem !== null,
    // Real activity (a turn or a stroke) moves these revisions; typing and idling do not.
    activityKey: `${workspace.state?.session.revision ?? "none"}:${workspace.scene?.scene_revision ?? "none"}`,
  });
  const turn = workspace.lastTurn;
  const media = useMedia({
    client,
    sessionId,
    services: mediaServices ?? defaultMediaServices(),
    generation: workspace.turnGeneration,
    epoch: workspace.state?.session.cancellation_epoch ?? null,
    revision: workspace.state?.session.revision ?? null,
    attemptId: workspace.state?.current_problem?.attempt_id ?? null,
    reply:
      turn !== null &&
      turn.status === "committed" &&
      turn.session_id === sessionId &&
      (turn.utterance ?? "").trim().length > 0
        ? {
            turnId: turn.turn_id,
            text: turn.utterance ?? "",
            epoch: turn.cancellation_epoch,
          }
        : null,
    busy: workspace.busyLabel !== null,
    soundAllowed: feedback.sound,
    textOnly: feedback.textOnly,
    boardHidden,
  });
  const [themeName, setThemeName] = useState<BoardThemeName>("paper");
  const [mode, setMode] = useState<BoardInputMode>("draw");
  const [draft, setDraft] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [noted, setNoted] = useState(false);
  const [ending, setEnding] = useState(false);
  const [endError, setEndError] = useState<string | null>(null);
  const [chatTurns, setChatTurns] = useState<TutorTurnResult[]>([]);
  const chatKey = workspace.lastTurn?.turn_id ?? "none";

  useEffect(() => {
    let active = true;
    client
      .turnEvents(sessionId)
      .then((events) => {
        if (active) setChatTurns(events);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [client, sessionId, chatKey]);

  React.useEffect(() => {
    let active = true;
    loadThemeName().then((name) => {
      if (active && (name === "paper" || name === "slate")) {
        setThemeName(name);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const theme = useMemo(() => getTheme(themeName), [themeName]);
  const notedTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  React.useEffect(
    () => () => {
      if (notedTimer.current !== null) clearTimeout(notedTimer.current);
    },
    [],
  );
  React.useEffect(() => {
    onThemeChange?.(theme);
  }, [onThemeChange, theme]);
  React.useEffect(() => {
    if (Platform.OS !== "web" || typeof window === "undefined" || boardHidden) {
      return;
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) {
        return;
      }
      const meta = event.metaKey || event.ctrlKey;
      if (!meta || event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        void workspace.undo();
      } else if ((key === "z" && event.shiftKey) || key === "y") {
        event.preventDefault();
        void workspace.redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [boardHidden, workspace]);
  const toggleTheme = useCallback(() => {
    setThemeName((current) => {
      const next = current === "paper" ? "slate" : "paper";
      void saveThemeName(next);
      return next;
    });
  }, []);

  const submitDraft = useCallback(() => {
    const text = draft.trim();
    if (text.length === 0) return;
    wait.clearStillThinkingNote();
    media.cancelSpeech("new_work");
    void workspace.submitWork(text, handhold).then((outcome) => {
      // Only an authoritative answer for exactly this text removes it; a failed or uncertain
      // send keeps it for retry, and anything the learner typed since stays untouched.
      if (outcome === "resolved") {
        setDraft((current) => (current.trim() === text ? "" : current));
        setNoted(true);
        if (notedTimer.current !== null) clearTimeout(notedTimer.current);
        notedTimer.current = setTimeout(
          () => setNoted(false),
          motion === "reduced" ? 900 : 1600,
        );
      }
    });
  }, [draft, handhold, media, motion, wait, workspace]);

  const askHelp = useCallback(() => {
    wait.clearStillThinkingNote();
    media.cancelSpeech("new_work");
    void workspace.requestHelp();
  }, [media, wait, workspace]);

  const askControl = useCallback(
    (control: LearnerControl) => {
      wait.clearStillThinkingNote();
      media.cancelSpeech("new_work");
      void workspace.requestHelp("hint", { handhold, learnerControl: control });
    },
    [handhold, media, wait, workspace],
  );

  const useMediaText = useCallback(
    (text: string) => {
      // Offered text only fills the typed-step box; the learner still reviews and submits it.
      setDraft(text);
      wait.clearStillThinkingNote();
    },
    [wait],
  );

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
          : "The session could not be ended. Your work is saved; try again.",
      );
    } finally {
      setEnding(false);
    }
  }, [client, ending, onSessionEnded, sessionId]);

  if (workspace.phase === "loading") {
    return (
      <View style={[styles.centered, { backgroundColor: theme.board }]}>
        <ActivityIndicator color={theme.studentInk} />
        <Text style={[styles.loadingText, { color: theme.labelMuted }]}>
          Setting up your board…
        </Text>
      </View>
    );
  }

  if (
    workspace.phase === "failed" ||
    workspace.state === null ||
    workspace.scene === null
  ) {
    return (
      <View style={[styles.centered, { backgroundColor: theme.board }]}>
        <Text style={[styles.errorTitle, { color: theme.labelText }]}>
          The board could not load.
        </Text>
        <Text style={[styles.loadingText, { color: theme.labelMuted }]}>
          {workspace.errorMessage ?? "Something went wrong. Your work is safe."}
        </Text>
        <Pressable
          testID="workspace-retry"
          accessibilityRole="button"
          accessibilityLabel="Try again"
          onPress={workspace.retry}
          style={[
            styles.retryButton,
            { backgroundColor: theme.controlBackground },
          ]}
        >
          <Text style={[styles.retryText, { color: theme.controlText }]}>
            Try again
          </Text>
        </Pressable>
      </View>
    );
  }

  const personaInfo = APPEARANCE_INFO[persona.appearance];
  const styleInfo = PERSONALITY_INFO[persona.personality];
  const scene = workspace.scene;
  const visibleObjects =
    hiddenIds.size === 0
      ? scene.objects
      : scene.objects.filter((object) => !hiddenIds.has(object.id));
  const avatarStatus = deriveAvatarStatus({
    busy: workspace.busyLabel !== null,
    connectionLost: workspace.connectionLost,
    unsavedChanges: workspace.pendingCount,
    failed: workspace.commandFailed,
    waiting: wait.stillThinkingStatus === "sent",
    media: media.activity,
    mediaAllowed: { listening: !feedback.textOnly, speaking: feedback.sound },
  });

  return (
    <KeyboardAvoidingView
      style={[styles.page, { backgroundColor: theme.board }]}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View style={styles.header}>
        <TutorAvatar
          personality={persona.personality}
          theme={theme}
          tutorName={`${personaInfo.name}, ${styleInfo.name}`}
          status={avatarStatus}
        />
        <View style={styles.headerText}>
          <Text
            numberOfLines={1}
            style={[styles.tutorName, { color: theme.labelText }]}
          >
            {personaInfo.name} · {styleInfo.name}
          </Text>
          <View style={styles.headerMeta}>
            <Text
              numberOfLines={1}
              style={[styles.headerSub, { color: theme.labelMuted }]}
            >
              {workspace.state.pace === "lighter"
                ? "Taking it gently today"
                : "Working with"}{" "}
              {displayName}
            </Text>
          </View>
        </View>
        <PromptBar
          theme={theme}
          expectedAction={workspace.lastExpectedAction}
          status={
            workspace.busyLabel ??
            stillThinkingStatusText(wait.stillThinkingStatus)
          }
        />
        <Pressable
          testID="workspace-menu"
          accessibilityRole="button"
          accessibilityLabel={menuOpen ? "Close more" : "More"}
          accessibilityState={{ expanded: menuOpen }}
          onPress={() => setMenuOpen((open) => !open)}
          style={[styles.more, { borderColor: theme.controlEdge }]}
        >
          <Text style={[styles.moreText, { color: theme.labelText }]}>
            {menuOpen ? "Close" : "More"}
          </Text>
        </Pressable>
      </View>
      <View
        style={[styles.menu, !menuOpen && styles.menuClosed]}
      >
        {workspace.providerLabel !== null ? (
          <Text
            testID="provider-label"
            numberOfLines={1}
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
        <SquareButton
          testID="help-me"
          theme={theme}
          label="Help me"
          hint={
            wait.hintAvailable
              ? "A hint is ready when you want it"
              : "Asks for a hint right now"
          }
          disabled={workspace.needsCheckIn || workspace.busyLabel !== null}
          onPress={askHelp}
          icon={<CircleHelp color={theme.labelText} size={18} strokeWidth={2.4} />}
        />
        <SquareButton
          testID="still-thinking"
          theme={theme}
          label="Still thinking"
          disabled={workspace.needsCheckIn}
          onPress={markStillThinking}
          icon={<Hourglass color={theme.labelText} size={18} strokeWidth={2.4} />}
        />
        <SquareButton
          testID="tool-theme"
          theme={theme}
          label={themeName === "paper" ? "Dark mode" : "Light mode"}
          hint="Switch the board theme; your colors stay distinct"
          onPress={toggleTheme}
          icon={
            themeName === "paper" ? (
              <Moon color={theme.labelText} size={18} strokeWidth={2.4} />
            ) : (
              <Sun color={theme.labelText} size={18} strokeWidth={2.4} />
            )
          }
        />
        {onOpenMemory !== undefined ? (
          <SquareButton
            testID="open-memory"
            theme={theme}
            label="Open private memory"
            onPress={onOpenMemory}
            icon={<Bookmark color={theme.labelText} size={18} strokeWidth={2.4} />}
          />
        ) : null}
        {onOpenSettings !== undefined ? (
          <SquareButton
            testID="open-settings"
            theme={theme}
            label="Open settings"
            onPress={onOpenSettings}
            icon={<Settings color={theme.labelText} size={18} strokeWidth={2.4} />}
          />
        ) : null}
        <SquareButton
          testID="finish-session"
          theme={theme}
          label="Finish for today"
          hint="Ends this session and returns to the welcome screen"
          disabled={ending || workspace.busyLabel !== null}
          onPress={() => void finishSession()}
          icon={<Flag color={theme.labelText} size={18} strokeWidth={2.4} />}
        />
        <MediaPanel
          theme={theme}
          media={media}
          soundAllowed={feedback.sound}
          textOnly={feedback.textOnly}
          captionsOn={feedback.captions}
          onUseText={useMediaText}
        />
        <WaitControls
          theme={theme}
          hintAvailable={wait.hintAvailable}
          preference={wait.preference}
          preferenceError={wait.preferenceError}
          onChangeSeconds={(seconds) => void wait.setWaitSeconds(seconds)}
        />
      </View>

      {endError !== null ? (
        <Text
          testID="finish-error"
          style={[styles.errorText, { color: theme.danger }]}
        >
          {endError}
        </Text>
      ) : null}

      <TeachingContext theme={theme} turn={workspace.lastTurn} />

      {workspace.errorMessage !== null ? (
        <Text
          testID="workspace-error"
          style={[styles.errorText, { color: theme.danger }]}
        >
          {workspace.errorMessage}
        </Text>
      ) : null}

      {workspace.pendingCount > 0 ? (
        <View
          testID="save-notice"
          accessibilityLiveRegion="polite"
          style={[
            styles.saveNotice,
            { backgroundColor: theme.surface, borderColor: theme.surfaceEdge },
          ]}
        >
          <Text style={[styles.saveNoticeText, { color: theme.labelText }]}>
            {workspace.memoryOnlyCount > 0
              ? "Some of your ink is not saved and could not be kept on this device. It is held only in memory while this screen stays open. Use Retry now once the tutor is reachable."
              : workspace.pendingCount === 1
                ? "One change is not saved yet. It is kept on this device and will save itself when the tutor is reachable."
                : `${workspace.pendingCount} changes are not saved yet. They are kept on this device and will save when the tutor is reachable.`}
          </Text>
          <Pressable
            testID="save-retry"
            accessibilityRole="button"
            accessibilityLabel="Retry saving now"
            disabled={workspace.busyLabel !== null}
            onPress={() => void workspace.retryPending()}
            style={[
              styles.saveRetryButton,
              { backgroundColor: theme.controlBackground },
            ]}
          >
            <Text style={[styles.saveRetryText, { color: theme.controlText }]}>
              Retry now
            </Text>
          </Pressable>
        </View>
      ) : null}

      {workspace.needsCheckIn ? (
        <QuestionIntake
          theme={theme}
          busy={workspace.busyLabel !== null}
          onStart={(input) => void workspace.checkIn({ ...input, handhold })}
        />
      ) : null}

      <View style={styles.stage}>
      <View style={styles.boardArea}>
        {workspace.state.current_problem?.statement ? (
          <Text testID="prompt-problem" style={styles.srOnly}>
            {workspace.state.current_problem.statement}
          </Text>
        ) : null}
        {workspace.canInterrupt ? (
          <SquareButton
            testID="stop-reply"
            theme={theme}
            label="Stop reply"
            hint="Stops the tutor's reply; your work stays saved"
            onPress={() => {
              media.cancelSpeech("interrupt");
              void workspace.interrupt();
            }}
            style={styles.stopFloat}
          >
            Stop
          </SquareButton>
        ) : null}
        <WhiteboardCanvas
          testID="whiteboard"
          objects={visibleObjects}
          currentStatementId={
            workspace.state.current_problem?.statement_object_id ?? null
          }
          pendingStrokes={workspace.pendingStrokes}
          settlingStrokes={workspace.settlingStrokes}
          animateTutorMarks={motion === "full" && !boardHidden}
          theme={theme}
          mode={mode}
          inputDisabled={workspace.penLocked}
          onStroke={(points) => void workspace.commitStroke(points)}
          onDoubleTap={() => {
            if (scene.student_undo_available) {
              void workspace.undo();
            }
          }}
          onEraseAt={(objectId) => {
            setMode("draw");
            void workspace.eraseObject(objectId);
          }}
        />
      </View>
      <TutorChat
        theme={theme}
        messages={messagesFromTurns(
          chatTurns.length > 0
            ? chatTurns
            : workspace.lastTurn !== null
              ? [workspace.lastTurn]
              : [],
        )}
        draft={draft}
        busy={workspace.busyLabel !== null}
        canReply={!workspace.needsCheckIn}
        thinking={workspace.busyLabel}
        onStillExploring={() => askControl("still_exploring")}
        onAskQuestion={() => askControl("ask_question")}
        onGiveHint={() => askControl("give_hint")}
        onChangeDraft={(text) => {
          setDraft(text);
          wait.clearStillThinkingNote();
        }}
        onSend={submitDraft}
        noted={noted}
      />
      <ToolRail
        theme={theme}
        mode={mode}
        layout="column"
        undoAvailable={scene.student_undo_available}
        redoAvailable={scene.student_redo_available}
        tutorUndoAvailable={scene.tutor_move_undo_available}
        busy={false}
        onModeChange={setMode}
        onUndo={() => void workspace.undo()}
        onRedo={() => void workspace.redo()}
        onUndoTutorMove={() => void workspace.undoTutorMove()}
      />
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    width: "100%",
    height: "100%",
    minHeight: 0,
    paddingHorizontal: 20,
  },
  centered: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    padding: 24,
  },
  loadingText: type.body,
  errorTitle: type.heading,
  errorText: type.small,
  saveNotice: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginHorizontal: 16,
    marginBottom: 6,
    paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  saveNoticeText: { ...type.small, flex: 1 },
  saveRetryButton: {
    minHeight: 44,
    paddingHorizontal: 16,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
  },
  saveRetryText: type.control,
  retryButton: {
    minHeight: 44,
    paddingHorizontal: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  retryText: type.control,
  header: {
    flexDirection: "row",
    flexWrap: "nowrap",
    alignItems: "center",
    gap: 8,
    paddingTop: 8,
    paddingBottom: 4,
  },
  headerText: { maxWidth: 280, flexShrink: 1 },
  headerMeta: { flexDirection: "row", alignItems: "center", gap: 8 },
  tutorName: type.name,
  headerSub: type.small,
  more: {
    minHeight: 44,
    paddingHorizontal: 12,
    borderWidth: 2,
    borderRadius: radius.pill,
    justifyContent: "center",
  },
  moreText: type.control,
  menu: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8,
    paddingBottom: 8,
  },
  menuClosed: {
    height: 0,
    paddingBottom: 0,
    overflow: "hidden",
  },
  providerLabel: { ...type.meta, fontWeight: "400", flexShrink: 1 },
  stage: {
    flex: 1,
    minHeight: 0,
    flexDirection: "row",
    alignItems: "stretch",
  },
  boardArea: { flex: 1, minHeight: 0, position: "relative" },
  srOnly: {
    position: "absolute",
    width: 1,
    height: 1,
    overflow: "hidden",
  },
  stopFloat: {
    position: "absolute",
    top: 8,
    right: 8,
    zIndex: 2,
  },
});
