/**
 * Vocabulary for explicit, foreground-only microphone and camera capture.
 *
 * Capture starts off. A permission is requested only by an explicit start call, never by
 * rendering, opening settings or mounting a screen.
 */

export type CaptureKind = "microphone" | "camera";
export type CameraOrientation = "student_facing" | "work_facing";
export type PermissionResult = "granted" | "denied" | "unavailable";

export type CaptureStopReason =
  | "user"
  | "background"
  | "unfocus"
  | "text_only"
  | "unmount";

export type CaptureState = {
  status: "off" | "requesting" | "on" | "denied" | "unavailable" | "error";
  /** Which way the camera faces; only present while a camera capture is on. */
  orientation: CameraOrientation | null;
  /** A plain-language reason for the current non-"on" state, shown to the learner. */
  note: string | null;
};

export const CAPTURE_OFF: CaptureState = {
  status: "off",
  orientation: null,
  note: null,
};

/** What an explicit capture produced. Pixels stay in device memory and are never read here. */
export type FrameInfo = {
  width: number;
  height: number;
  mime: "image/jpeg" | "image/png";
};

/** Platform adapter. Each method is called only in response to an explicit learner action. */
export type CaptureDriver = {
  microphone: {
    request: () => Promise<PermissionResult>;
    /** Open the foreground input. Nothing is recorded or kept. */
    open: () => Promise<void>;
    close: () => Promise<void>;
  };
  camera: {
    request: () => Promise<PermissionResult>;
    /** False when the device has no camera (or the browser exposes none). */
    available: () => Promise<boolean>;
    open: (orientation: CameraOrientation) => Promise<void>;
    close: () => Promise<void>;
    /** One explicit still from the open preview; null when the preview is not ready. */
    snapshot: () => Promise<FrameInfo | null>;
  };
};

export function describeStop(kind: CaptureKind, reason: CaptureStopReason): string {
  const name = kind === "microphone" ? "Microphone" : "Camera";
  switch (reason) {
    case "background":
      return `${name} turned off because the app left the foreground.`;
    case "unfocus":
      return `${name} turned off because you left the board.`;
    case "text_only":
      return `${name} turned off because text-only mode is on.`;
    case "unmount":
      return `${name} turned off.`;
    default:
      return `${name} turned off.`;
  }
}
