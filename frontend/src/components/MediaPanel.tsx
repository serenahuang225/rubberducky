/**
 * Optional voice and camera controls.
 *
 * Everything here starts off. A permission is requested only by pressing one of the start
 * buttons, every open capture shows a labeled indicator with a reachable Stop, and denial,
 * a missing device or text-only mode leave typing and drawing untouched. Recognition and
 * transcription are shown as unavailable unless the server says otherwise; the simulated
 * controls are labeled as fixtures and never presented as live results.
 */

import React, { useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { Mic } from "lucide-react-native";

import type { BoardTheme } from "../board/palette";
import { radius } from "../theme/tokens";

import { HoldPressable } from "./HoldPressable";
import { nextScriptStep } from "../media/voiceSession";
import type { MediaController, VoiceMode } from "../media/useMedia";

const ORIENTATION_LABEL = {
  student_facing: "facing you",
  work_facing: "facing your work",
} as const;

export type MediaPanelProps = {
  theme: BoardTheme;
  media: MediaController;
  soundAllowed: boolean;
  textOnly: boolean;
  captionsOn: boolean;
  /** Puts text into the typed-step box. It is never submitted automatically. */
  onUseText: (text: string) => void;
  /** Hold-to-talk through the server. Absent when that path is off. */
  talk?: {
    available: boolean;
    recording: boolean;
    disabled: boolean;
    note: string | null;
    onPressIn: () => void;
    onPressOut: () => void;
  };
};

function Button({
  theme,
  testID,
  label,
  onPress,
  disabled = false,
  selected,
  hint,
}: {
  theme: BoardTheme;
  testID: string;
  label: string;
  onPress: () => void;
  disabled?: boolean;
  selected?: boolean;
  hint?: string;
}) {
  return (
    <HoldPressable
      testID={testID}
      overview={hint ?? label}
      theme={theme}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      accessibilityState={{
        disabled,
        ...(selected === undefined ? {} : { selected }),
      }}
      disabled={disabled}
      onPress={onPress}
      style={[
        styles.button,
        {
          backgroundColor: selected ? theme.controlBackground : theme.surface,
          borderColor: selected ? theme.controlBackground : theme.controlEdge,
          opacity: disabled ? 0.55 : 1,
        },
      ]}
    >
      <Text
        style={[
          styles.buttonText,
          { color: selected ? theme.controlText : theme.labelText },
        ]}
      >
        {label}
      </Text>
    </HoldPressable>
  );
}

function EditableOffer({
  theme,
  testID,
  label,
  initial,
  onUse,
}: {
  theme: BoardTheme;
  testID: string;
  label: string;
  initial: string;
  onUse: (text: string) => void;
}) {
  const [text, setText] = useState(initial);
  return (
    <View style={styles.offer}>
      <Text style={[styles.small, { color: theme.labelMuted }]}>{label}</Text>
      <TextInput
        testID={`${testID}-input`}
        accessibilityLabel={label}
        value={text}
        onChangeText={setText}
        style={[
          styles.input,
          {
            backgroundColor: theme.surface,
            borderColor: theme.controlEdge,
            color: theme.labelText,
          },
        ]}
      />
      <Button
        theme={theme}
        testID={`${testID}-use`}
        label="Use as my typed step"
        hint="Copies this text into the typed step box; you still press Submit"
        disabled={text.trim().length === 0}
        onPress={() => onUse(text.trim())}
      />
    </View>
  );
}

const VOICE_OPTIONS: { mode: VoiceMode; label: string }[] = [
  { mode: "off", label: "Text only replies" },
  { mode: "device", label: "Read replies aloud" },
  { mode: "simulated", label: "Simulated voice (test)" },
];

export function MediaIndicators({
  theme,
  media,
}: {
  theme: BoardTheme;
  media: MediaController;
}) {
  const { microphone, camera } = media.capture;
  const speaking =
    media.speech.phase === "starting" || media.speech.phase === "speaking";
  const items: {
    key: string;
    text: string;
    onStop: () => void;
    stopLabel: string;
  }[] = [];
  if (microphone.status === "on" || microphone.status === "requesting") {
    items.push({
      key: "microphone",
      text:
        microphone.status === "requesting"
          ? "Microphone: waiting for permission"
          : "Microphone is on",
      onStop: () => media.stopCapture("microphone"),
      stopLabel: "Turn microphone off",
    });
  }
  if (camera.status === "on" || camera.status === "requesting") {
    items.push({
      key: "camera",
      text:
        camera.status === "requesting"
          ? "Camera: waiting for permission"
          : `Camera is on, ${ORIENTATION_LABEL[camera.orientation ?? "work_facing"]}`,
      onStop: () => media.stopCapture("camera"),
      stopLabel: "Turn camera off",
    });
  }
  if (speaking) {
    items.push({
      key: "speech",
      text: media.speech.simulated
        ? "Simulated voice is speaking"
        : "Reading the reply aloud",
      onStop: () => media.cancelSpeech("user_stop"),
      stopLabel: "Stop speaking",
    });
  }
  if (items.length === 0) return null;
  return (
    <View
      testID="media-indicators"
      accessibilityLiveRegion="polite"
      style={styles.indicators}
    >
      {items.map((item) => (
        <View
          key={item.key}
          testID={`indicator-${item.key}`}
          style={[
            styles.chip,
            { backgroundColor: theme.surface, borderColor: theme.danger },
          ]}
        >
          <View style={[styles.dot, { backgroundColor: theme.danger }]} />
          <Text style={[styles.chipText, { color: theme.labelText }]}>
            {item.text}
          </Text>
          <HoldPressable
            testID={`stop-${item.key}`}
            overview={item.stopLabel}
            theme={theme}
            accessibilityRole="button"
            accessibilityLabel={item.stopLabel}
            onPress={item.onStop}
            style={[styles.stop, { backgroundColor: theme.controlBackground }]}
          >
            <Text style={[styles.stopText, { color: theme.controlText }]}>
              Stop
            </Text>
          </HoldPressable>
        </View>
      ))}
    </View>
  );
}

export function MediaPanel({
  theme,
  media,
  soundAllowed,
  textOnly,
  captionsOn,
  onUseText,
  talk,
}: MediaPanelProps) {
  const [open, setOpen] = useState(false);
  const muted = { color: theme.labelMuted };
  const text = { color: theme.labelText };
  const { microphone, camera } = media.capture;
  const speaking =
    media.speech.phase === "starting" || media.speech.phase === "speaking";
  const caps = media.capabilities;
  const nextStep = nextScriptStep(media.voice);
  const notes = [microphone.note, camera.note].filter(
    (note): note is string => note !== null,
  );

  return (
    <View style={styles.wrapper}>
      <MediaIndicators theme={theme} media={media} />
      {captionsOn && speaking && media.speech.text !== null ? (
        <View
          testID="speech-caption"
          accessibilityLabel={`Caption: ${media.speech.text}`}
          style={[
            styles.caption,
            { backgroundColor: theme.surface, borderColor: theme.surfaceEdge },
          ]}
        >
          <Text style={[styles.small, muted]}>
            {media.speech.simulated ? "Caption (simulated voice)" : "Caption"}
          </Text>
          <Text style={[styles.body, text]}>{media.speech.text}</Text>
        </View>
      ) : null}
      {media.speech.note !== null && !speaking ? (
        <Text
          testID="speech-note"
          accessibilityLiveRegion="polite"
          style={[styles.small, muted]}
        >
          {media.speech.note}
        </Text>
      ) : null}

      <HoldPressable
        testID="media-toggle"
        overview="Opens the microphone. Replies can be read aloud from here."
        theme={theme}
        accessibilityRole="button"
        accessibilityLabel="Voice"
        accessibilityState={{ expanded: open }}
        onPress={() => {
          if (!open) media.loadCapabilities();
          setOpen((value) => !value);
        }}
        style={[
          styles.toggle,
          { backgroundColor: theme.surface, borderColor: theme.surfaceEdge },
        ]}
      >
        <Mic color={theme.labelText} size={18} strokeWidth={2.4} />
      </HoldPressable>

      {open ? (
        <ScrollView
          testID="media-panel"
          style={[
            styles.panelScroll,
            { backgroundColor: theme.surface, borderColor: theme.surfaceEdge },
          ]}
          contentContainerStyle={styles.panel}
        >
          <Text style={[styles.body, text]}>
            Typing and drawing are all you need. Nothing here is on until you
            turn it on.
          </Text>
          <View testID="media-disclosure">
            <Text style={[styles.small, muted]}>
              {caps !== null
                ? caps.disclosures.local.join(" ")
                : "The microphone stays on this device. No audio is saved or sent."}
            </Text>
            <Text style={[styles.small, muted]}>
              {caps !== null
                ? caps.disclosures.transmitted.join(" ")
                : "No outside service is configured to receive anything."}
            </Text>
          </View>
          {caps !== null ? (
            <View testID="media-status">
              <Text style={[styles.small, muted]}>
                {`Photo reading: ${caps.perception.status}. ${caps.perception.detail}`}
              </Text>
              <Text style={[styles.small, muted]}>
                {`Voice transcription: ${caps.transcription.status}. ${caps.transcription.detail}`}
              </Text>
              <Text style={[styles.small, muted]}>
                {caps.speech_interruption.detail}
              </Text>
            </View>
          ) : media.capabilitiesError !== null ? (
            <Text
              testID="media-capabilities-error"
              style={[styles.small, { color: theme.danger }]}
            >
              {media.capabilitiesError}
            </Text>
          ) : null}

          {caps?.spoken_reply !== undefined ? (
            <Text testID="spoken-reply-status" style={[styles.small, muted]}>
              {`Hold to talk: ${caps.spoken_reply.status}. ${caps.spoken_reply.detail}`}
            </Text>
          ) : null}
          {talk?.available ? (
            <Pressable
              testID="hold-to-talk"
              accessibilityRole="button"
              accessibilityLabel={talk.recording ? "Release to send" : "Hold to talk"}
              accessibilityHint="Records while held, then sends the recording to the tutor"
              accessibilityState={{ disabled: talk.disabled, selected: talk.recording }}
              disabled={talk.disabled}
              onPressIn={talk.onPressIn}
              onPressOut={talk.onPressOut}
              style={[
                styles.button,
                {
                  backgroundColor: talk.recording ? theme.controlBackground : theme.surface,
                  borderColor: theme.controlEdge,
                  opacity: talk.disabled ? 0.55 : 1,
                },
              ]}
            >
              <Text
                style={[
                  styles.buttonText,
                  { color: talk.recording ? theme.controlText : theme.labelText },
                ]}
              >
                {talk.recording ? "Release to send" : "Hold to talk"}
              </Text>
            </Pressable>
          ) : null}
          {talk?.note !== null && talk?.note !== undefined ? (
            <Text testID="talk-note" accessibilityLiveRegion="polite" style={[styles.small, text]}>
              {talk.note}
            </Text>
          ) : null}

          {textOnly ? (
            <Text testID="media-text-only" style={[styles.small, muted]}>
              Text-only mode is on, so the microphone stays off.
            </Text>
          ) : null}

          <View style={styles.row}>
            <Button
              theme={theme}
              testID="mic-start"
              label="Turn on microphone"
              hint="Asks the device for microphone permission"
              disabled={
                textOnly ||
                microphone.status === "on" ||
                microphone.status === "requesting"
              }
              onPress={media.startMicrophone}
            />
          </View>
          {notes.map((note) => (
            <Text
              key={note}
              testID="capture-note"
              accessibilityLiveRegion="polite"
              style={[styles.small, text]}
            >
              {note}
            </Text>
          ))}
          {microphone.status === "on" ? (
            <Text testID="mic-note" style={[styles.small, muted]}>
              {media.transcriptionAvailable
                ? "Listening. Words appear below for you to check. They are not a submitted step until you use them."
                : "The microphone is open, but voice transcription is not configured: nothing is recorded or turned into text."}
            </Text>
          ) : null}
          {media.voice.source === "device" &&
          (media.voice.provisional !== null || media.voice.final !== null) ? (
            <View testID="live-transcript">
              {media.voice.provisional !== null ? (
                <Text testID="live-provisional" style={[styles.body, text]}>
                  {`Hearing: ${media.voice.provisional}`}
                </Text>
              ) : null}
              {media.voice.final !== null ? (
                <EditableOffer
                  key={media.voice.final}
                  theme={theme}
                  testID="live-final"
                  label="Transcribed text. Check and edit before using it."
                  initial={media.voice.final}
                  onUse={onUseText}
                />
              ) : null}
              {media.voice.note !== null ? (
                <Text testID="live-note" style={[styles.small, muted]}>
                  {media.voice.note}
                </Text>
              ) : null}
            </View>
          ) : null}
          <Text style={[styles.small, muted]}>Tutor replies</Text>
          <View style={styles.row}>
            {VOICE_OPTIONS.filter(
              (option) => option.mode !== "simulated" || media.fixturesEnabled,
            ).map((option) => (
              <Button
                key={option.mode}
                theme={theme}
                testID={`voice-${option.mode}`}
                label={option.label}
                selected={media.voiceMode === option.mode}
                onPress={() => media.setVoiceMode(option.mode)}
              />
            ))}
          </View>
          {media.voiceMode !== "off" && !soundAllowed ? (
            <Text testID="voice-muted-note" style={[styles.small, muted]}>
              Sound is off in settings, so replies are shown as text only.
            </Text>
          ) : null}

          {media.outcome !== null ? (
            <View
              testID="media-outcome"
              accessibilityLiveRegion="polite"
              style={[styles.outcome, { borderColor: theme.surfaceEdge }]}
            >
              <Text style={[styles.small, muted]}>
                {media.outcome.simulated
                  ? "Simulated, synthetic result for testing"
                  : "Result"}
                {` · ${media.outcome.status.replace(/_/g, " ")}`}
              </Text>
              <Text style={[styles.body, text]}>{media.outcome.message}</Text>
              {media.outcome.candidates.map((candidate, index) => (
                <EditableOffer
                  key={`${media.outcome?.status}-${index}-${candidate.text}`}
                  theme={theme}
                  testID={`candidate-${index}`}
                  label={`Uncertain reading, ${Math.round(candidate.confidence * 100)}% sure. Check and edit before using it.`}
                  initial={candidate.text}
                  onUse={onUseText}
                />
              ))}
              <Button
                theme={theme}
                testID="outcome-dismiss"
                label="Dismiss"
                onPress={media.dismissOutcome}
              />
            </View>
          ) : null}

          {media.fixturesEnabled ? (
            <View
              testID="media-fixtures"
              style={[styles.outcome, { borderColor: theme.surfaceEdge }]}
            >
              <Text style={[styles.body, text]}>
                Simulated events (testing only, not live transcription or
                recognition)
              </Text>
              <View style={styles.row}>
                <Button
                  theme={theme}
                  testID="sim-voice-next"
                  label={
                    nextStep === null
                      ? "Simulated voice finished"
                      : `Play simulated voice: ${nextStep.label}`
                  }
                  disabled={nextStep === null || media.voiceBusy}
                  onPress={media.nextVoiceEvent}
                />
                <Button
                  theme={theme}
                  testID="sim-voice-reset"
                  label="Restart simulated voice"
                  onPress={media.resetVoice}
                />
                <Button
                  theme={theme}
                  testID="sim-photo"
                  label="Simulate photo reading"
                  onPress={media.simulatePhoto}
                />
                <Button
                  theme={theme}
                  testID="sim-cue"
                  label="Simulate a quiet moment"
                  onPress={media.simulateWeakCue}
                />
              </View>
              {media.voice.provisional !== null ? (
                <Text testID="voice-provisional" style={[styles.body, text]}>
                  {`Provisional (not final): ${media.voice.provisional}`}
                </Text>
              ) : null}
              {media.voice.final !== null ? (
                <EditableOffer
                  key={media.voice.final}
                  theme={theme}
                  testID="voice-final"
                  label="Simulated final text. Check and edit before using it."
                  initial={media.voice.final}
                  onUse={onUseText}
                />
              ) : null}
              {media.voice.note !== null ? (
                <Text
                  testID="voice-note"
                  accessibilityLiveRegion="polite"
                  style={[styles.small, muted]}
                >
                  {media.voice.note}
                </Text>
              ) : null}
            </View>
          ) : null}

          {media.notice !== null ? (
            <Text
              testID="media-notice"
              accessibilityLiveRegion="polite"
              style={[styles.small, { color: theme.danger }]}
            >
              {media.notice}
            </Text>
          ) : null}
        </ScrollView>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { gap: 6 },
  indicators: { gap: 6 },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingLeft: 12,
    paddingRight: 6,
    paddingVertical: 4,
    borderRadius: radius.lg,
    borderWidth: 1,
    alignSelf: "flex-start",
  },
  dot: { width: 10, height: 10, borderRadius: radius.pill },
  chipText: { fontSize: 14, fontWeight: "600" },
  stop: {
    minHeight: 44,
    minWidth: 56,
    paddingHorizontal: 12,
    borderRadius: radius.lg,
    alignItems: "center",
    justifyContent: "center",
  },
  stopText: { fontSize: 14, fontWeight: "700" },
  caption: { padding: 16, borderRadius: radius.lg, borderWidth: 1, gap: 2 },
  toggle: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 10,
    borderWidth: 2,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "flex-start",
  },
  panelScroll: { overflow: "hidden", maxHeight: 300, borderRadius: radius.lg, borderWidth: 1 },
  panel: { gap: 12, padding: 16 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  cameraRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    flexWrap: "wrap",
  },
  button: {
    minHeight: 44,
    paddingHorizontal: 12,
    borderRadius: radius.lg,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonText: { fontSize: 14, fontWeight: "600" },
  body: { fontSize: 15, lineHeight: 21 },
  small: { fontSize: 13, lineHeight: 18 },
  outcome: { gap: 12, padding: 16, borderRadius: radius.lg, borderWidth: 1 },
  offer: { gap: 6 },
  input: {
    minHeight: 44,
    borderWidth: 1,
    borderRadius: radius.lg,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 16,
    fontFamily: "monospace",
  },
});
