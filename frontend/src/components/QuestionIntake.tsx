/**
 * Opening question: type it, upload a file, or paste/choose a screenshot.
 * Claude reads that and the reply is shown on the board and in the prompt.
 */

import React, { createElement, useCallback, useEffect, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import type { CheckInInput } from "../api/client";
import type { BoardTheme } from "../board/palette";
import { QuestionCamera } from "../media/QuestionCamera";
import { readQuestionFile, type QuestionImagePayload } from "../media/questionFile";
import { WebQuestionCamera } from "../media/WebQuestionCamera";
import { radius, type } from "../theme/tokens";

const ENERGY_OPTIONS = [
  { value: "ready" as const, label: "Ready to go" },
  { value: "a_bit_tired" as const, label: "A bit tired" },
  { value: "tired" as const, label: "Really tired" },
];

function iosBrowser(): boolean {
  if (typeof navigator === "undefined") return false;
  const agent = navigator.userAgent;
  return (
    /iPad|iPhone|iPod/.test(agent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

function fileLabel(
  testID: string,
  label: string,
  accept: string,
  onPicked: (event: Event) => void,
  busy: boolean,
  theme: BoardTheme,
  capture?: "environment" | "user",
) {
  return createElement(
    "label",
    {
      "data-testid": testID,
      style: {
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        overflow: "hidden",
        minHeight: 44,
        padding: "10px 16px",
        border: `1px solid ${theme.controlEdge}`,
        borderRadius: radius.pill,
        background: theme.board,
        color: theme.labelText,
        fontFamily: type.control.fontFamily,
        fontSize: type.control.fontSize,
        cursor: busy ? "default" : "pointer",
        opacity: busy ? 0.5 : 1,
      },
    },
    createElement("input", {
      type: "file",
      accept,
      capture,
      disabled: busy,
      onChange: onPicked,
      // iPad Safari ignores a file input that is display:none, so the control stays
      // in the label and is only visually hidden.
      style: {
        position: "absolute",
        top: 0,
        left: 0,
        width: "100%",
        height: "100%",
        opacity: 0,
        fontSize: 16,
        cursor: busy ? "default" : "pointer",
      },
    }),
    label,
  );
}

export type QuestionIntakeProps = {
  theme: BoardTheme;
  busy: boolean;
  onStart: (input: CheckInInput) => void;
};

export function QuestionIntake({ theme, busy, onStart }: QuestionIntakeProps) {
  const [text, setText] = useState("");
  const [image, setImage] = useState<QuestionImagePayload | null>(null);
  const [imageLabel, setImageLabel] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [energy, setEnergy] = useState<CheckInInput["energy"]>(null);

  const canStart = text.trim().length > 0 || image !== null;

  const acceptFile = useCallback(async (file: File) => {
    setFileError(null);
    try {
      const read = await readQuestionFile(file);
      if (read.kind === "text") {
        setText((current) =>
          current.trim().length > 0 ? `${current.trim()}\n${read.text}` : read.text,
        );
        return;
      }
      setImage(read.image);
      setImageLabel(file.name || "Screenshot");
    } catch (error) {
      setFileError(error instanceof Error ? error.message : "Could not read that file.");
    }
  }, []);

  useEffect(() => {
    if (Platform.OS !== "web" || busy) return;
    const listener = (event: ClipboardEvent) => {
      const items = event.clipboardData?.items;
      if (items === undefined) return;
      for (const item of items) {
        if (!item.type.startsWith("image/")) continue;
        const file = item.getAsFile();
        if (file === null) continue;
        event.preventDefault();
        void acceptFile(file);
        return;
      }
    };
    window.addEventListener("paste", listener);
    return () => window.removeEventListener("paste", listener);
  }, [acceptFile, busy]);

  function onPicked(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (file !== undefined) void acceptFile(file);
  }

  return (
    <View
      testID="question-intake"
      style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.surfaceEdge }]}
    >
      <Text style={[styles.title, { color: theme.labelText }]}>What are we working on?</Text>
      <Text style={[styles.sub, { color: theme.labelMuted }]}>
        {Platform.OS === "web"
          ? "Type the question, take a photo, upload a file, or paste a screenshot. Your tutor reads it and shows the explanation here."
          : "Type the question, or take a photo of it. Your tutor reads it and shows the explanation here."}
      </Text>
      <TextInput
        testID="question-input"
        value={text}
        onChangeText={setText}
        editable={!busy}
        multiline
        placeholder="Type the question"
        placeholderTextColor={theme.labelMuted}
        accessibilityLabel="Question you are working on"
        style={[
          styles.input,
          { color: theme.labelText, borderColor: theme.controlEdge, backgroundColor: theme.board },
        ]}
      />
      {imageLabel !== null ? (
        <View style={styles.attachedRow}>
          <Text style={[styles.sub, { color: theme.labelText }]}>Attached: {imageLabel}</Text>
          <Pressable
            testID="question-clear-image"
            accessibilityRole="button"
            accessibilityLabel="Remove attached picture"
            disabled={busy}
            onPress={() => {
              setImage(null);
              setImageLabel(null);
            }}
          >
            <Text style={[styles.link, { color: theme.labelText }]}>Remove</Text>
          </Pressable>
        </View>
      ) : null}
      {Platform.OS === "web" ? (
        <View style={styles.row}>
          {fileLabel("question-upload", "Upload a file", "image/png,image/jpeg,image/webp,text/plain,.txt", onPicked, busy, theme)}
          {iosBrowser() ? (
            fileLabel(
              "question-photo",
              "Take a photo",
              "image/*",
              onPicked,
              busy,
              theme,
              "environment",
            )
          ) : (
            <WebQuestionCamera
              theme={theme}
              busy={busy}
              onCaptured={(captured) => {
                setFileError(null);
                setImage(captured);
                setImageLabel("Photo");
              }}
              onError={setFileError}
            />
          )}
        </View>
      ) : (
        <QuestionCamera
          theme={theme}
          busy={busy}
          onCaptured={(captured) => {
            setFileError(null);
            setImage(captured);
            setImageLabel("Photo");
          }}
          onError={setFileError}
        />
      )}
      {fileError !== null ? (
        <Text testID="question-file-error" style={[styles.sub, { color: theme.danger }]}>
          {fileError}
        </Text>
      ) : null}
      <Text style={[styles.sub, { color: theme.labelMuted }]}>
        How are you feeling? Optional. It only shapes today’s pace.
      </Text>
      <View style={styles.row}>
        {ENERGY_OPTIONS.map((option) => {
          const selected = energy === option.value;
          return (
            <Pressable
              key={option.value}
              testID={`checkin-${option.value}`}
              accessibilityRole="button"
              accessibilityLabel={option.label}
              accessibilityState={{ selected }}
              disabled={busy}
              onPress={() => setEnergy(selected ? null : option.value)}
              style={[
                styles.button,
                {
                  backgroundColor: selected ? theme.controlBackground : theme.board,
                  borderColor: theme.controlEdge,
                },
              ]}
            >
              <Text
                style={[
                  styles.buttonText,
                  { color: selected ? theme.controlText : theme.labelText },
                ]}
              >
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
      <View style={styles.row}>
        <Pressable
          testID="question-start"
          accessibilityRole="button"
          accessibilityLabel="Start with this question"
          disabled={busy || !canStart}
          onPress={() =>
            onStart({
              energy,
              questionText: text.trim(),
              image,
              practice: false,
            })
          }
          style={[
            styles.primary,
            {
              backgroundColor: theme.controlBackground,
              opacity: busy || !canStart ? 0.5 : 1,
            },
          ]}
        >
          <Text style={[styles.buttonText, { color: theme.controlText }]}>
            Start with this question
          </Text>
        </Pressable>
        <Pressable
          testID="question-practice"
          accessibilityRole="button"
          accessibilityLabel="Use a practice problem"
          disabled={busy}
          onPress={() => onStart({ energy, practice: true })}
          style={[styles.button, { backgroundColor: theme.board, borderColor: theme.controlEdge }]}
        >
          <Text style={[styles.buttonText, { color: theme.labelText }]}>
            Use a practice problem
          </Text>
        </Pressable>
        <Pressable
          testID="question-calculus"
          accessibilityRole="button"
          accessibilityLabel="Practice derivatives, integrals, and a gradient"
          disabled={busy}
          onPress={() => onStart({ energy, calculus: true })}
          style={[styles.button, { backgroundColor: theme.board, borderColor: theme.controlEdge }]}
        >
          <Text style={[styles.buttonText, { color: theme.labelText }]}>
            Practice calculus
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { width: "100%", maxWidth: 640, borderWidth: 1, borderRadius: radius.lg, padding: 28, gap: 16 },
  title: type.heading,
  sub: type.small,
  input: {
    ...type.body,
    borderWidth: 1,
    borderRadius: radius.md,
    minHeight: 120,
    paddingHorizontal: 16,
    paddingVertical: 14,
    textAlignVertical: "top",
  },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  attachedRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  button: {
    borderWidth: 1,
    borderRadius: radius.pill,
    minHeight: 44,
    paddingHorizontal: 16,
    paddingVertical: 10,
    justifyContent: "center",
  },
  primary: { borderRadius: radius.pill, minHeight: 48, paddingHorizontal: 20, paddingVertical: 12, justifyContent: "center" },
  buttonText: type.control,
  link: type.small,
});
