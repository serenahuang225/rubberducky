import { CAPTURE_OFF } from "./captureTypes";
import { deriveMediaActivity, type MediaFacts } from "./mediaActivity";
import type { SpeechSnapshot } from "./speechController";
import { VOICE_IDLE } from "./voiceSession";

const idleSpeech: SpeechSnapshot = {
  phase: "idle",
  text: null,
  turnId: null,
  simulated: false,
  note: null,
  events: [],
};

const base: MediaFacts = {
  capture: { microphone: CAPTURE_OFF, camera: CAPTURE_OFF },
  speech: idleSpeech,
  voice: VOICE_IDLE,
  transcriptionAvailable: false,
};

const micOn = {
  microphone: { status: "on" as const, orientation: null, note: null },
  camera: CAPTURE_OFF,
};

describe("deriveMediaActivity", () => {
  it("reports nothing when nothing is happening", () => {
    expect(deriveMediaActivity(base)).toBeNull();
  });

  it("speaking requires the driver to have started, and carries its simulated label", () => {
    expect(
      deriveMediaActivity({
        ...base,
        speech: { ...idleSpeech, phase: "starting" },
      }),
    ).toBeNull();
    expect(
      deriveMediaActivity({
        ...base,
        speech: { ...idleSpeech, phase: "speaking" },
      }),
    ).toEqual({ kind: "speaking", source: "live" });
    expect(
      deriveMediaActivity({
        ...base,
        speech: { ...idleSpeech, phase: "speaking", simulated: true },
      }),
    ).toEqual({ kind: "speaking", source: "simulated" });
  });

  it("an open microphone alone is not listening when no transcriber exists", () => {
    expect(deriveMediaActivity({ ...base, capture: micOn })).toBeNull();
  });

  it("an open microphone feeding an available transcriber is live listening", () => {
    expect(
      deriveMediaActivity({
        ...base,
        capture: micOn,
        transcriptionAvailable: true,
      }),
    ).toEqual({ kind: "listening", source: "live" });
  });

  it("a requesting or denied microphone is never listening", () => {
    for (const status of [
      "requesting",
      "denied",
      "unavailable",
      "error",
    ] as const) {
      expect(
        deriveMediaActivity({
          ...base,
          capture: {
            microphone: { status, orientation: null, note: null },
            camera: CAPTURE_OFF,
          },
          transcriptionAvailable: true,
        }),
      ).toBeNull();
    }
  });

  it("an active simulated utterance is listening, labeled simulated", () => {
    expect(
      deriveMediaActivity({ ...base, voice: { ...VOICE_IDLE, active: true } }),
    ).toEqual({ kind: "listening", source: "simulated" });
  });
});
