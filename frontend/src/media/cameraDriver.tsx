/**
 * Camera capture through expo-camera, shared by native and web.
 *
 * The preview component owns the actual device: it opens when it mounts and releases when it
 * unmounts, so closing capture means no longer rendering it. A still is taken in memory only
 * (a picture reference, never a file path or encoded bytes) and only the image size leaves
 * this module.
 */

import { Camera, CameraView } from "expo-camera";
import React, { useEffect, useRef } from "react";
import { StyleSheet, View } from "react-native";

import { BRAND } from "../board/palette";

import type {
  CameraOrientation,
  CaptureDriver,
  FrameInfo,
  PermissionResult,
} from "./captureTypes";

type CameraRegistry = {
  takePicture: (() => Promise<FrameInfo | null>) | null;
};

// The driver is plain async code with no view; the mounted preview registers its capability.
const registry: CameraRegistry = { takePicture: null };

export function facingFor(orientation: CameraOrientation): "front" | "back" {
  return orientation === "student_facing" ? "front" : "back";
}

export const deviceCamera: CaptureDriver["camera"] = {
  available: async () => {
    try {
      return await CameraView.isAvailableAsync();
    } catch {
      return false;
    }
  },
  request: async (): Promise<PermissionResult> => {
    try {
      const response = await Camera.requestCameraPermissionsAsync();
      return response.granted ? "granted" : "denied";
    } catch {
      return "unavailable";
    }
  },
  open: async () => undefined,
  close: async () => {
    registry.takePicture = null;
  },
  snapshot: async () => (registry.takePicture ? registry.takePicture() : null),
};

export type CameraPreviewProps = {
  orientation: CameraOrientation;
  label: string;
  onFault: () => void;
};

export function CameraPreview({
  orientation,
  label,
  onFault,
}: CameraPreviewProps) {
  const ref = useRef<CameraView>(null);
  const readyRef = useRef(false);

  useEffect(() => {
    registry.takePicture = async () => {
      const view = ref.current;
      if (view === null || !readyRef.current) return null;
      const picture = (await view.takePictureAsync({
        pictureRef: true,
        skipProcessing: true,
        shutterSound: false,
      })) as { width?: number; height?: number };
      if (
        typeof picture.width !== "number" ||
        typeof picture.height !== "number" ||
        picture.width < 1 ||
        picture.height < 1
      ) {
        return null;
      }
      return { width: picture.width, height: picture.height, mime: "image/jpeg" };
    };
    return () => {
      registry.takePicture = null;
      readyRef.current = false;
    };
  }, []);

  return (
    <View
      testID="camera-preview"
      accessible
      accessibilityLabel={label}
      style={styles.frame}
    >
      <CameraView
        ref={ref}
        style={styles.view}
        facing={facingFor(orientation)}
        onCameraReady={() => {
          readyRef.current = true;
        }}
        onMountError={onFault}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    width: 160,
    height: 120,
    borderRadius: 20,
    overflow: "hidden",
    backgroundColor: BRAND.blue,
  },
  view: { flex: 1 },
});
