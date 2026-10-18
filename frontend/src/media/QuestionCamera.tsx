/**
 * iPad and phone camera for the opening question.
 * Uses the system camera, then hands back one JPEG. The picture is not saved.
 */

import * as ImagePicker from "expo-image-picker";
import React, { useState } from "react";
import { Pressable, StyleSheet, Text } from "react-native";

import type { BoardTheme } from "../board/palette";
import { type } from "../theme/tokens";

import type { QuestionImagePayload } from "./questionFile";
import { photoBase64 } from "./questionPhoto";

export type QuestionCameraProps = {
  theme: BoardTheme;
  busy: boolean;
  onCaptured: (image: QuestionImagePayload) => void;
  onError: (message: string | null) => void;
};

export function QuestionCamera({ theme, busy, onCaptured, onError }: QuestionCameraProps) {
  const [taking, setTaking] = useState(false);

  async function openCamera() {
    if (taking) return;
    onError(null);
    setTaking(true);
    try {
      const permission = await ImagePicker.requestCameraPermissionsAsync();
      if (!permission.granted) {
        onError("The camera is not allowed. Type the question, or allow the camera in Settings.");
        return;
      }
      const result = await ImagePicker.launchCameraAsync({
        mediaTypes: ["images"],
        quality: 0.4,
        base64: true,
        exif: false,
        cameraType: ImagePicker.CameraType.back,
      });
      if (result.canceled) return;
      const encoded = photoBase64(result.assets[0]?.base64 ?? undefined);
      onCaptured({ mediaType: "image/jpeg", base64: encoded });
    } catch (error) {
      onError(
        error instanceof Error
          ? error.message
          : "The camera could not take a photo. You can still type the question.",
      );
    } finally {
      setTaking(false);
    }
  }

  return (
    <Pressable
      testID="question-photo"
      accessibilityRole="button"
      accessibilityLabel="Take a photo of the question"
      disabled={busy || taking}
      onPress={() => void openCamera()}
      style={[
        styles.open,
        {
          backgroundColor: theme.board,
          borderColor: theme.controlEdge,
          opacity: busy || taking ? 0.5 : 1,
        },
      ]}
    >
      <Text style={[styles.openText, { color: theme.labelText }]}>
        {taking ? "Opening camera…" : "Take a photo"}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  open: {
    borderWidth: 1,
    minHeight: 44,
    paddingHorizontal: 12,
    justifyContent: "center",
  },
  openText: type.control,
});
