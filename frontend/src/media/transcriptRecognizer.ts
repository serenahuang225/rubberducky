/**
 * Turns microphone audio into text on the device that has a speech recognizer.
 *
 * The native Expo Go build has no speech engine, so this file reports unavailable and
 * never opens a socket. The web build replaces it with the browser recognizer. Audio is
 * not uploaded to the tutor; only text the learner later confirms can become a step.
 */

export type TranscriptPhase = "interim" | "final";

export type TranscriptChunk = {
  phase: TranscriptPhase;
  text: string;
};

export type TranscriptHandlers = {
  onResult: (chunk: TranscriptChunk) => void;
  onError: () => void;
};

export type TranscriptRecognizer = {
  /** True only when this process can actually transcribe. */
  available: () => boolean;
  /**
   * `browser_speech_service` means the browser may send audio to its own vendor
   * (Chrome sends it to Google). `none` means this build does not transcribe.
   */
  transmission: "browser_speech_service" | "none";
  start: (handlers: TranscriptHandlers) => void;
  stop: () => void;
};

export const deviceTranscriptRecognizer: TranscriptRecognizer = {
  available: () => false,
  transmission: "none",
  start: () => undefined,
  stop: () => undefined,
};
