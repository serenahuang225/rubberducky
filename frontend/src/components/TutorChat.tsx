/**
 * A quiet conversation beside the board. The latest tutor note stays on the board;
 * this panel keeps the thread, including a "Good job!" when the question is solved.
 */

import React, { useEffect, useRef } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import type { BoardTheme } from "../board/palette";
import { radius, type } from "../theme/tokens";

import { isGoodJob, type ChatMessage } from "./chatMessages";
import { HoldPressable } from "./HoldPressable";

export type TutorChatProps = {
  theme: BoardTheme;
  messages: readonly ChatMessage[];
  draft: string;
  busy: boolean;
  canReply: boolean;
  thinking: string | null;
  onStillExploring: () => void;
  onAskQuestion: () => void;
  onGiveHint: () => void;
  onChangeDraft: (text: string) => void;
  onSend: () => void;
  onHide?: () => void;
  noted?: boolean;
};

export function TutorChat({
  theme,
  messages,
  draft,
  busy,
  canReply,
  thinking,
  onStillExploring,
  onAskQuestion,
  onGiveHint,
  onChangeDraft,
  onSend,
  onHide,
  noted = false,
}: TutorChatProps) {
  const scrollRef = useRef<ScrollView>(null);
  const canSend = canReply && !busy && draft.trim().length > 0;
  const controlsReady = canReply && !busy;

  useEffect(() => {
    scrollRef.current?.scrollToEnd({ animated: false });
  }, [messages, thinking]);

  return (
    <View
      testID="tutor-chat"
      style={[styles.panel, { backgroundColor: theme.surface, borderColor: theme.surfaceEdge }]}
    >
      <View style={styles.titleRow}>
        <Text style={[styles.title, { color: theme.labelText }]}>Chat</Text>
        {onHide !== undefined ? (
          <HoldPressable
            testID="hide-chat"
            overview="Closes the chat. Your messages stay, and you can open it again."
            theme={theme}
            accessibilityRole="button"
            accessibilityLabel="Hide chat"
            onPress={onHide}
            style={[styles.hide, { borderColor: theme.surfaceEdge }]}
          >
            <Text style={[styles.hideText, { color: theme.labelText }]}>Hide</Text>
          </HoldPressable>
        ) : null}
      </View>
      <View style={styles.logWrap}>
      <ScrollView
        ref={scrollRef}
        testID="tutor-chat-log"
        style={styles.log}
        contentContainerStyle={styles.logContent}
      >
        {messages.length === 0 ? (
          <Text style={[styles.empty, { color: theme.labelMuted }]}>
            Your question and the tutor’s replies will show up here.
          </Text>
        ) : (
          messages.map((message, index) => {
            const praise = message.role === "tutor" && isGoodJob(message.text);
            const lastTutor =
              message.role === "tutor" &&
              messages.slice(index + 1).every((later) => later.role !== "tutor");
            return (
              <View
                key={message.id}
                testID={praise ? "chat-good-job" : `chat-${message.role}`}
                style={
                  praise
                    ? [styles.praise, { borderLeftColor: theme.tutorInk }]
                    : undefined
                }
              >
                <Text style={[styles.who, { color: theme.labelMuted }]}>
                  {message.role === "you" ? "You" : "Tutor"}
                </Text>
                <Text
                  testID={lastTutor ? "prompt-tutor" : undefined}
                  style={[styles.text, { color: theme.labelText }]}
                >
                  {message.text}
                </Text>
              </View>
            );
          })
        )}
        {thinking !== null ? (
          <Text testID="chat-thinking" style={[styles.thinking, { color: theme.labelMuted }]}>
            {thinking}
          </Text>
        ) : null}
      </ScrollView>
      </View>
      <View style={styles.controls}>
        <HoldPressable
          testID="handhold-still-exploring"
          overview="Tells your tutor you are still exploring this idea, without asking for the answer."
          theme={theme}
          accessibilityRole="button"
          accessibilityLabel="Still exploring"
          disabled={!controlsReady}
          onPress={onStillExploring}
          style={[styles.controlButton, { borderColor: theme.surfaceEdge, opacity: controlsReady ? 1 : 0.4 }]}
        >
          <Text numberOfLines={1} style={[styles.control, { color: theme.labelText }]}>
            Still exploring
          </Text>
        </HoldPressable>
        <HoldPressable
          testID="handhold-ask-question"
          overview="Asks your tutor to pose a question, instead of telling you the next step."
          theme={theme}
          accessibilityRole="button"
          accessibilityLabel="Ask me a question"
          disabled={!controlsReady}
          onPress={onAskQuestion}
          style={[styles.controlButton, { borderColor: theme.surfaceEdge, opacity: controlsReady ? 1 : 0.4 }]}
        >
          <Text numberOfLines={1} adjustsFontSizeToFit style={[styles.control, { color: theme.labelText }]}>
            Ask me a question
          </Text>
        </HoldPressable>
        <HoldPressable
          testID="handhold-give-hint"
          overview="Asks for one hint. It does not give the answer."
          theme={theme}
          accessibilityRole="button"
          accessibilityLabel="Give me a hint"
          disabled={!controlsReady}
          onPress={onGiveHint}
          style={[styles.controlButton, { borderColor: theme.surfaceEdge, opacity: controlsReady ? 1 : 0.4 }]}
        >
          <Text numberOfLines={1} style={[styles.control, { color: theme.labelText }]}>
            Give me a hint
          </Text>
        </HoldPressable>
      </View>
      <View style={[styles.composer, { borderTopColor: theme.surfaceEdge }]}>
        <TextInput
          testID="chat-input"
          value={draft}
          onChangeText={onChangeDraft}
          editable={canReply && !busy}
          placeholder={canReply ? "Write your step" : "Start with a question first"}
          placeholderTextColor={theme.labelMuted}
          accessibilityLabel="Reply to the tutor"
          onSubmitEditing={() => {
            if (canSend) onSend();
          }}
          style={[styles.input, { color: theme.labelText }]}
        />
        <Pressable
          testID="chat-send"
          accessibilityRole="button"
          accessibilityLabel="Send reply"
          disabled={!canSend}
          onPress={onSend}
          style={{ opacity: canSend ? 1 : 0.4 }}
        >
          <Text style={[styles.send, { color: theme.controlBackground }]}>Send</Text>
        </Pressable>
        {noted ? (
          <Text testID="step-noted" style={[styles.noted, { color: theme.labelMuted }]}>
            Noted
          </Text>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    width: 360,
    minWidth: 220,
    flexShrink: 1,
    minHeight: 0,
    overflow: "hidden",
    borderLeftWidth: 2,
    borderTopLeftRadius: radius.lg,
    borderBottomLeftRadius: radius.lg,
    paddingTop: 16,
  },
  titleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    marginBottom: 8,
    gap: 8,
  },
  title: type.name,
  hide: {
    minHeight: 36,
    paddingHorizontal: 12,
    borderWidth: 2,
    borderRadius: radius.pill,
    justifyContent: "center",
  },
  hideText: type.small,
  logWrap: { flex: 1, minHeight: 0 },
  controls: {
    flexDirection: "row",
    flexWrap: "nowrap",
    gap: 6,
    paddingHorizontal: 12,
    paddingBottom: 8,
  },
  controlButton: {
    flex: 1,
    minWidth: 0,
    borderWidth: 2,
    borderRadius: 999,
    paddingHorizontal: 6,
    minHeight: 44,
    justifyContent: "center",
    alignItems: "center",
  },
  control: { ...type.small, fontSize: 12, lineHeight: 16, textAlign: "center" },
  log: { flex: 1, minHeight: 0 },
  logContent: { paddingHorizontal: 16, paddingBottom: 12, gap: 16 },
  empty: type.small,
  who: { ...type.meta, marginBottom: 2 },
  text: type.body,
  praise: { borderLeftWidth: 3, paddingLeft: 8 },
  thinking: type.small,
  noted: type.meta,
  composer: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 16,
    minHeight: 52,
  },
  input: { ...type.body, flex: 1, minHeight: 44, paddingVertical: 8 },
  send: type.control,
});
