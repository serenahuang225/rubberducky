/**
 * A quiet conversation beside the board. The latest tutor note stays on the board;
 * this panel keeps the thread, including a "Good job!" when the question is solved.
 */

import React, { useEffect, useRef } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import type { BoardTheme } from "../board/palette";
import { type } from "../theme/tokens";

import { isGoodJob, type ChatMessage } from "./chatMessages";

export type TutorChatProps = {
  theme: BoardTheme;
  messages: readonly ChatMessage[];
  draft: string;
  busy: boolean;
  canReply: boolean;
  thinking: string | null;
  onChangeDraft: (text: string) => void;
  onSend: () => void;
};

export function TutorChat({
  theme,
  messages,
  draft,
  busy,
  canReply,
  thinking,
  onChangeDraft,
  onSend,
}: TutorChatProps) {
  const scrollRef = useRef<ScrollView>(null);
  const canSend = canReply && !busy && draft.trim().length > 0;

  useEffect(() => {
    scrollRef.current?.scrollToEnd({ animated: false });
  }, [messages, thinking]);

  return (
    <View
      testID="tutor-chat"
      style={[styles.panel, { backgroundColor: theme.surface, borderColor: theme.surfaceEdge }]}
    >
      <Text style={[styles.title, { color: theme.labelText }]}>Chat</Text>
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
          messages.map((message) => {
            const praise = message.role === "tutor" && isGoodJob(message.text);
            return (
              <View
                key={message.id}
                testID={praise ? "chat-good-job" : `chat-${message.role}`}
                style={praise ? [styles.praise, { borderColor: theme.tutorInk }] : undefined}
              >
                <Text style={[styles.who, { color: praise ? theme.tutorInk : theme.labelMuted }]}>
                  {message.role === "you" ? "You" : "Tutor"}
                </Text>
                <Text style={[styles.text, { color: theme.labelText }]}>{message.text}</Text>
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
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    width: 300,
    borderLeftWidth: StyleSheet.hairlineWidth,
    paddingTop: 16,
  },
  title: { ...type.name, paddingHorizontal: 16, marginBottom: 8 },
  log: { flex: 1 },
  logContent: { paddingHorizontal: 16, paddingBottom: 12, gap: 16 },
  empty: type.small,
  who: { ...type.meta, marginBottom: 2 },
  text: type.body,
  praise: { borderLeftWidth: 2, paddingLeft: 10 },
  thinking: type.small,
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
