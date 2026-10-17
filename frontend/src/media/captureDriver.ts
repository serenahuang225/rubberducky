/**
 * Native capture driver: expo-camera for the camera, expo-audio for microphone permission.
 *
 * The microphone is opened only as a foreground input. No sample is read, stored or sent,
 * and no transcription is configured, so "on" means the device input is available to the
 * app and nothing more.
 */

import { requestRecordingPermissionsAsync, setAudioModeAsync } from "expo-audio";

import { deviceCamera } from "./cameraDriver";
import type { CaptureDriver, PermissionResult } from "./captureTypes";

export const deviceCaptureDriver: CaptureDriver = {
  microphone: {
    request: async (): Promise<PermissionResult> => {
      try {
        const response = await requestRecordingPermissionsAsync();
        return response.granted ? "granted" : "denied";
      } catch {
        return "unavailable";
      }
    },
    open: () => setAudioModeAsync({ allowsRecording: true }),
    close: () => setAudioModeAsync({ allowsRecording: false }),
  },
  camera: deviceCamera,
};
