/**
 * Browser capture driver. The microphone holds a getUserMedia audio stream only so the
 * browser's own recording indicator is real while capture is on; no audio is read, stored or
 * sent, and closing stops every track. The camera is shared with native (expo-camera).
 */

import { deviceCamera } from "./cameraDriver";
import type { CaptureDriver, PermissionResult } from "./captureTypes";

type StreamLike = { getTracks: () => { stop: () => void }[] };

let held: StreamLike | null = null;

function mediaDevices(): {
  getUserMedia: (constraints: { audio: boolean }) => Promise<StreamLike>;
} | null {
  const nav = (globalThis as { navigator?: { mediaDevices?: unknown } }).navigator;
  const devices = nav?.mediaDevices as
    | { getUserMedia?: (constraints: { audio: boolean }) => Promise<StreamLike> }
    | undefined;
  return devices?.getUserMedia
    ? { getUserMedia: devices.getUserMedia.bind(devices) }
    : null;
}

export const deviceCaptureDriver: CaptureDriver = {
  microphone: {
    request: async (): Promise<PermissionResult> => {
      const devices = mediaDevices();
      if (devices === null) return "unavailable";
      try {
        const stream = await devices.getUserMedia({ audio: true });
        // Keep the grant's stream so open() does not prompt twice.
        held?.getTracks().forEach((track) => track.stop());
        held = stream;
        return "granted";
      } catch (error) {
        const name = (error as { name?: string }).name;
        return name === "NotFoundError" || name === "OverconstrainedError"
          ? "unavailable"
          : "denied";
      }
    },
    open: async () => {
      if (held === null) throw new Error("microphone stream missing");
    },
    close: async () => {
      held?.getTracks().forEach((track) => track.stop());
      held = null;
    },
  },
  camera: deviceCamera,
};
