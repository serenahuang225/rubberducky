/**
 * A quiet conversation beside the board. The latest tutor note stays on the board;
 * this panel keeps the thread, including a "Good job!" when the question is solved.
 */

import React, { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import type { BoardTheme } from "../board/palette";
import { radius, type } from "../theme/tokens";

import { isGoodJob, type ChatMessage } from "./chatMessages";
import { HoldPressable } from "./HoldPressable";

export type TutorChatProps = {
  theme: BoardTheme;
  partnerName?: string;
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
  partnerName = "Your thinking partner",
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
  const [moreAbove, setMoreAbove] = useState(false);
  const canSend = canReply && !busy && draft.trim().length > 0;
  const controlsReady = canReply && !busy;



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
      {moreAbove ? (
        <View pointerEvents="none" style={[styles.moreAbove, { backgroundColor: theme.surface }]} />
      ) : null}
      <ScrollView
        testID="tutor-chat-log"
        style={styles.log}
        contentContainerStyle={styles.logContent}
        scrollEventThrottle={16}
        onScroll={(event) => setMoreAbove(event.nativeEvent.contentOffset.y > 12)}
      >
        {messages.length === 0 ? (
          <Text style={[styles.empty, { color: theme.labelMuted }]}>
            Your question and {partnerName}’s replies will show up here.
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
                style={[
                  message.role === "tutor" ? [styles.tutorMessage, { borderLeftColor: theme.tutorInk }] : undefined,
                  praise ? [styles.praise, { borderLeftColor: theme.tutorInk }] : undefined,
                ]}
              >
                <Text
                  style={[
                    styles.who,
                    { color: message.role === "tutor" ? theme.tutorInk : theme.studentInk },
                  ]}
                >
                  {message.role === "you" ? "You" : partnerName}
                </Text>
                <Text
                  testID={lastTutor ? "prompt-tutor" : undefined}
                  style={[
                    styles.text,
                    { color: message.role === "tutor" ? theme.tutorInk : theme.studentInk },
                  ]}
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
          accessibilityLabel={`Reply to ${partnerName}`}
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
    width: 400,
    minWidth: 220,
    flexShrink: 1,
    minHeight: 0,
    overflow: "hidden",
    borderWidth: 1,
    borderRadius: radius.lg,
    borderTopLeftRadius: radius.lg,
    borderBottomLeftRadius: radius.lg,
    paddingTop: 16,
  },
  titleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 28,
    marginBottom: 8,
    gap: 8,
  },
  title: type.name,
  hide: {
    minHeight: 44,
    paddingHorizontal: 12,
    borderWidth: 2,
    borderRadius: radius.pill,
    justifyContent: "center",
  },
  hideText: type.small,
  logWrap: { flex: 1, minHeight: 0 },
  moreAbove: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    height: 28,
    zIndex: 2,
    shadowColor: "#1985d0",
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.35,
    shadowRadius: 8,
    elevation: 6,
  },
  controls: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    paddingHorizontal: 28,
    paddingBottom: 16,
  },
  controlButton: {
    flexGrow: 1,
    minWidth: 96,
    borderWidth: 2,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    minHeight: 44,
    justifyContent: "center",
    alignItems: "center",
  },
  control: { ...type.small, fontSize: 12, lineHeight: 16, textAlign: "center" },
  log: { flex: 1, minHeight: 0 },
  logContent: { paddingHorizontal: 28, paddingBottom: 12, gap: 16 },
  empty: type.small,
  who: { ...type.meta, marginBottom: 2 },
  text: type.body,
  tutorMessage: { paddingLeft: 14, borderLeftWidth: 3 },
  praise: { borderLeftWidth: 3, paddingLeft: 14 },
  thinking: type.small,
  noted: type.meta,
  composer: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 24,
    paddingVertical: 12,
    minHeight: 72,
  },
  input: { ...type.body, flex: 1, minHeight: 44, paddingVertical: 8 },
  send: type.control,
});
