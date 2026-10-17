/**
 * Spoken replies through expo-speech (the platform text-to-speech voice) and a deterministic
 * simulated driver for tests and the labeled fixture journey.
 *
 * The device driver is output only. It makes no claim about being heard and gives no way to
 * detect the learner's voice, so it provides no acoustic barge-in.
 */

import * as Speech from "expo-speech";
import { Platform } from "react-native";

import type {
  SpeechDriver,
  SpeechHandlers,
} from "./speechController";

export const deviceSpeechDriver: SpeechDriver = {
  simulated: false,
  available: () =>
    Platform.OS !== "web" ||
    typeof (globalThis as { speechSynthesis?: unknown }).speechSynthesis !==
      "undefined",
  speak: (text, handlers) => {
    Speech.speak(text, {
      onStart: handlers.onStart,
      onDone: handlers.onDone,
      onStopped: handlers.onStopped,
      onError: () => handlers.onError(),
    });
  },
  stop: () => {
    void Speech.stop();
  },
};

export type SimulatedTimers = {
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
};

/**
 * Starts after a beat and finishes after `durationMs`, which leaves a visible window to stop
 * it. Stopping clears the timers, so a stopped utterance never reports done.
 */
export function createSimulatedSpeechDriver(
  durationMs = 6000,
  timers: SimulatedTimers = {
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
  },
): SpeechDriver {
  let pending: unknown[] = [];
  return {
    simulated: true,
    available: () => true,
    speak: (_text: string, handlers: SpeechHandlers) => {
      pending.forEach((handle) => timers.clearTimeout(handle));
      pending = [
        timers.setTimeout(handlers.onStart, 0),
        timers.setTimeout(handlers.onDone, durationMs),
      ];
    },
    stop: () => {
      pending.forEach((handle) => timers.clearTimeout(handle));
      pending = [];
    },
  };
}
