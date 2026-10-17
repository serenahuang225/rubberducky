/**
 * Owns microphone and camera capture state.
 *
 * Each modality has a run token: stopping (or a newer start) invalidates a start that is
 * still awaiting a permission answer, so a late grant cannot open a capture the learner
 * already cancelled. Closing is always paired with opening, so foreground release on
 * background/unfocus/text-only/unmount leaves no capture behind. Denial, a missing device or
 * a driver failure only change this state; they never touch typed work or the board.
 */

import {
  CAPTURE_OFF,
  describeStop,
  type CameraOrientation,
  type CaptureDriver,
  type CaptureKind,
  type CaptureState,
  type CaptureStopReason,
  type FrameInfo,
} from "./captureTypes";

export type CaptureSnapshot = Record<CaptureKind, CaptureState>;

const DENIED_NOTE: Record<CaptureKind, string> = {
  microphone:
    "Microphone permission was not granted. You can keep typing and drawing; nothing is listening.",
  camera:
    "Camera permission was not granted. You can keep typing and drawing; nothing is being captured.",
};
const UNAVAILABLE_NOTE: Record<CaptureKind, string> = {
  microphone:
    "No microphone is available here. You can keep typing and drawing.",
  camera: "No camera is available here. You can keep typing and drawing.",
};
const ERROR_NOTE: Record<CaptureKind, string> = {
  microphone: "The microphone could not be opened. Typing and drawing still work.",
  camera: "The camera could not be opened. Typing and drawing still work.",
};

export class CaptureController {
  private snapshot: CaptureSnapshot = {
    microphone: CAPTURE_OFF,
    camera: CAPTURE_OFF,
  };
  private readonly runs: Record<CaptureKind, number> = {
    microphone: 0,
    camera: 0,
  };
  private readonly listeners = new Set<() => void>();
  private blocked = false;

  constructor(private readonly driver: CaptureDriver) {}

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): CaptureSnapshot => this.snapshot;

  /** Text-only mode blocks capture entirely; turning it on releases anything open. */
  async setBlocked(blocked: boolean): Promise<void> {
    this.blocked = blocked;
    if (blocked) await this.stopAll("text_only");
  }

  private set(kind: CaptureKind, state: CaptureState): void {
    this.snapshot = { ...this.snapshot, [kind]: state };
    this.listeners.forEach((listener) => listener());
  }

  async startMicrophone(): Promise<void> {
    await this.start("microphone", null);
  }

  async startCamera(orientation: CameraOrientation): Promise<void> {
    await this.start("camera", orientation);
  }

  private async start(
    kind: CaptureKind,
    orientation: CameraOrientation | null,
  ): Promise<void> {
    if (this.blocked) {
      this.set(kind, {
        ...CAPTURE_OFF,
        note: "Text-only mode is on, so the microphone and camera stay off.",
      });
      return;
    }
    // Switching the camera facing replaces the previous capture instead of stacking.
    if (this.snapshot[kind].status === "on") await this.release(kind);
    const run = ++this.runs[kind];
    const current = () => run === this.runs[kind];
    this.set(kind, { status: "requesting", orientation, note: null });
    try {
      if (kind === "camera" && !(await this.driver.camera.available())) {
        if (current()) {
          this.set(kind, {
            status: "unavailable",
            orientation: null,
            note: UNAVAILABLE_NOTE.camera,
          });
        }
        return;
      }
      const permission = await (kind === "microphone"
        ? this.driver.microphone.request()
        : this.driver.camera.request());
      if (!current()) return;
      if (permission !== "granted") {
        this.set(kind, {
          status: permission === "denied" ? "denied" : "unavailable",
          orientation: null,
          note:
            permission === "denied"
              ? DENIED_NOTE[kind]
              : UNAVAILABLE_NOTE[kind],
        });
        return;
      }
      if (kind === "microphone") await this.driver.microphone.open();
      else await this.driver.camera.open(orientation ?? "student_facing");
      if (!current()) {
        await this.closeDriver(kind);
        return;
      }
      this.set(kind, { status: "on", orientation, note: null });
    } catch {
      if (current()) {
        await this.closeDriver(kind);
        this.set(kind, {
          status: "error",
          orientation: null,
          note: ERROR_NOTE[kind],
        });
      }
    }
  }

  private async closeDriver(kind: CaptureKind): Promise<void> {
    try {
      if (kind === "microphone") await this.driver.microphone.close();
      else await this.driver.camera.close();
    } catch {
      // Releasing is best effort; the state below already reports it as off.
    }
  }

  private async release(kind: CaptureKind): Promise<void> {
    this.runs[kind] += 1;
    await this.closeDriver(kind);
  }

  async stop(kind: CaptureKind, reason: CaptureStopReason): Promise<void> {
    const status = this.snapshot[kind].status;
    // A pending start is invalidated; a driver is closed only if it may have been opened.
    this.runs[kind] += 1;
    if (status === "on" || status === "requesting") {
      await this.closeDriver(kind);
    }
    if (status === "off" && reason !== "user") return;
    this.set(kind, { ...CAPTURE_OFF, note: describeStop(kind, reason) });
  }

  /** A preview that failed after it looked open (mount error) is released and reported. */
  async fail(kind: CaptureKind): Promise<void> {
    if (this.snapshot[kind].status !== "on") return;
    this.runs[kind] += 1;
    await this.closeDriver(kind);
    this.set(kind, { status: "error", orientation: null, note: ERROR_NOTE[kind] });
  }

  /** One explicit still. Only possible while the camera is on; never reads pixel data. */
  async takeSnapshot(): Promise<FrameInfo | null> {
    if (this.snapshot.camera.status !== "on") return null;
    try {
      return await this.driver.camera.snapshot();
    } catch {
      return null;
    }
  }

  async stopAll(reason: CaptureStopReason): Promise<void> {
    await Promise.all([this.stop("microphone", reason), this.stop("camera", reason)]);
  }
}
