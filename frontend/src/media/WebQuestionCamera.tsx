/**
 * Browser camera for the opening question.
 * A still is scaled down in the page and sent with check-in. It is not saved.
 */

import React, { createElement, useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { BRAND, type BoardTheme } from "../board/palette";
import { type } from "../theme/tokens";

import type { QuestionImagePayload } from "./questionFile";

const MAX_EDGE = 1600;

export type WebQuestionCameraProps = {
  theme: BoardTheme;
  busy: boolean;
  onCaptured: (image: QuestionImagePayload) => void;
  onError: (message: string | null) => void;
};

export function WebQuestionCamera({ theme, busy, onCaptured, onError }: WebQuestionCameraProps) {
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  function stop() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setOpen(false);
  }

  useEffect(() => () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);

  useEffect(() => {
    if (!open) return;
    const video = document.getElementById("question-camera-video");
    const stream = streamRef.current;
    if (!(video instanceof HTMLVideoElement) || stream === null) return;
    video.srcObject = stream;
    void video.play().catch(() => undefined);
  }, [open]);

  async function openCamera() {
    onError(null);
    setNotice(null);
    if (typeof navigator === "undefined" || navigator.mediaDevices?.getUserMedia === undefined) {
      onError("This browser cannot open the camera. Upload a picture instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: "environment" } },
      });
      streamRef.current = stream;
      setOpen(true);
    } catch {
      onError("The camera could not be opened. Allow the camera, or upload a picture.");
    }
  }

  function shoot() {
    const video = document.getElementById("question-camera-video");
    if (!(video instanceof HTMLVideoElement) || video.videoWidth < 1) {
      setNotice("The camera is not ready yet.");
      return;
    }
    const scale = Math.min(1, MAX_EDGE / Math.max(video.videoWidth, video.videoHeight));
    const width = Math.max(1, Math.round(video.videoWidth * scale));
    const height = Math.max(1, Math.round(video.videoHeight * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (context === null) {
      onError("Could not read that photo.");
      return;
    }
    context.drawImage(video, 0, 0, width, height);
    const encoded = (canvas.toDataURL("image/jpeg", 0.82).split(",")[1] ?? "").replace(/\s/g, "");
    if (encoded.length === 0) {
      onError("Could not read that photo.");
      return;
    }
    stop();
    onCaptured({ mediaType: "image/jpeg", base64: encoded });
  }

  return (
    <>
      <Pressable
        testID="question-photo"
        accessibilityRole="button"
        accessibilityLabel="Take a photo of the question"
        disabled={busy}
        onPress={() => void openCamera()}
        style={[
          styles.open,
          {
            backgroundColor: theme.board,
            borderColor: theme.controlEdge,
            opacity: busy ? 0.5 : 1,
          },
        ]}
      >
        <Text style={[styles.openText, { color: theme.labelText }]}>Take a photo</Text>
      </Pressable>
      {open
        ? createElement(
            "div",
            {
              style: {
                position: "fixed",
                inset: 0,
                zIndex: 50,
                background: BRAND.blue,
                display: "flex",
                flexDirection: "column",
              },
            },
            createElement("video", {
              id: "question-camera-video",
              autoPlay: true,
              playsInline: true,
              muted: true,
              style: {
                flex: 1,
                width: "100%",
                minHeight: 0,
                objectFit: "cover",
                background: BRAND.blue,
              },
            }),
            <View style={styles.bar}>
              {notice !== null ? <Text style={styles.notice}>{notice}</Text> : null}
              <Pressable
                testID="question-photo-cancel"
                accessibilityRole="button"
                accessibilityLabel="Cancel photo"
                onPress={stop}
                style={styles.barButton}
              >
                <Text style={styles.barText}>Cancel</Text>
              </Pressable>
              <Pressable
                testID="question-photo-shutter"
                accessibilityRole="button"
                accessibilityLabel="Capture the question"
                onPress={shoot}
                style={styles.barButton}
              >
                <Text style={styles.barText}>Use this photo</Text>
              </Pressable>
            </View>,
          )
        : null}
    </>
  );
}

const styles = StyleSheet.create({
  open: {
    borderWidth: 2,
    borderRadius: 999,
    minHeight: 44,
    paddingHorizontal: 16,
    justifyContent: "center",
  },
  openText: type.control,
  bar: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 20,
    paddingVertical: 16,
  },
  notice: { ...type.small, color: BRAND.white, flexBasis: "100%" },
  barButton: { minHeight: 44, justifyContent: "center", paddingHorizontal: 8 },
  barText: { ...type.control, color: BRAND.white },
});
