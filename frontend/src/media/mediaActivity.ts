/**
 * What the avatar may say about media, from real facts only.
 *
 * Speaking comes from the speech driver's own start callback. Listening is live only when a
 * microphone the learner opened is feeding a transcriber that is actually available; with no
 * transcription configured an open microphone is shown as open, never as the tutor listening.
 * Deterministic voice events are returned as simulated.
 */

import type { MediaActivity } from "../state/avatarStatus";

import type { CaptureSnapshot } from "./captureController";
import type { SpeechSnapshot } from "./speechController";
import type { VoiceState } from "./voiceSession";

export type MediaFacts = {
  capture: CaptureSnapshot;
  speech: SpeechSnapshot;
  voice: VoiceState;
  transcriptionAvailable: boolean;
};

export function deriveMediaActivity(facts: MediaFacts): MediaActivity | null {
  if (facts.speech.phase === "speaking") {
    return {
      kind: "speaking",
      source: facts.speech.simulated ? "simulated" : "live",
    };
  }
  if (facts.voice.active) {
    return { kind: "listening", source: "simulated" };
  }
  if (facts.capture.microphone.status === "on" && facts.transcriptionAvailable) {
    return { kind: "listening", source: "live" };
  }
  return null;
}
