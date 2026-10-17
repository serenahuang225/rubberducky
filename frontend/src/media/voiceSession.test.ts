import { mediaEventResultSchema } from "../api/contracts";

import {
  applyTranscriptResult,
  buildTranscriptEvent,
  SIMULATED_VOICE_SCRIPT,
  VOICE_IDLE,
  type VoiceState,
} from "./voiceSession";

function resultFor(status: string, kind = "transcript") {
  return mediaEventResultSchema.parse({
    schema_version: "media-event-result.v1",
    event_id: "e1",
    kind,
    status,
    simulated: true,
    session_id: "s1",
    session_revision: 1,
    cancellation_epoch: 0,
    message: "m",
    assessment_effect: "none",
    evidence_recorded: false,
    raw_media_retained: false,
  });
}

function play(state: VoiceState, status: string): VoiceState {
  const built = buildTranscriptEvent(state);
  if (built === null) throw new Error("script finished");
  return applyTranscriptResult(state, built.request, resultFor(status));
}

describe("simulated voice script", () => {
  it("uses one utterance with increasing sequence numbers and unique event ids", () => {
    let state = VOICE_IDLE;
    const requests = [];
    for (let i = 0; i < SIMULATED_VOICE_SCRIPT.length; i += 1) {
      const built = buildTranscriptEvent(state);
      expect(built).not.toBeNull();
      requests.push(built!.request);
      state = applyTranscriptResult(
        state,
        built!.request,
        resultFor("provisional"),
      );
    }
    expect(new Set(requests.map((r) => r.utterance_id)).size).toBe(1);
    expect(requests.map((r) => r.sequence)).toEqual([1, 2, 3, 4, 5]);
    expect(new Set(requests.map((r) => r.event_id)).size).toBe(5);
    expect(requests.every((r) => r.source === "simulated")).toBe(true);
    expect(buildTranscriptEvent(state)).toBeNull();
  });
});

describe("transcript state", () => {
  it("keeps interim text provisional and replaces it with each revision", () => {
    let state = play(VOICE_IDLE, "provisional");
    expect(state).toMatchObject({
      provisional: "2x plus 3",
      final: null,
      active: true,
    });
    state = play(state, "provisional");
    expect(state.provisional).toBe("2x plus 3 equals 1");
    expect(state.final).toBeNull();
  });

  it("final replaces the provisional text and ends the utterance", () => {
    let state = play(VOICE_IDLE, "provisional");
    state = play(state, "provisional");
    state = play(state, "final_accepted");
    expect(state).toMatchObject({
      provisional: null,
      final: "2x + 3 = 14",
      active: false,
    });
    expect(state.note).toMatch(/nothing was submitted/i);
  });

  it("a duplicate final and a late interim change no text", () => {
    let state = VOICE_IDLE;
    state = play(state, "provisional");
    state = play(state, "provisional");
    state = play(state, "final_accepted");
    const finalState = state;
    state = play(state, "duplicate_final");
    expect(state.final).toBe(finalState.final);
    expect(state.note).toMatch(/not counted twice/i);
    state = play(state, "ignored_late");
    expect(state.final).toBe(finalState.final);
    expect(state.provisional).toBeNull();
    expect(state.active).toBe(false);
    expect(state.note).toMatch(/late/i);
  });

  it("an unexpected status leaves the transcript as it was and shows the server message", () => {
    const before = play(VOICE_IDLE, "provisional");
    const built = buildTranscriptEvent(before)!;
    const after = applyTranscriptResult(
      before,
      built.request,
      resultFor("perception_unavailable"),
    );
    expect(after.provisional).toBe(before.provisional);
    expect(after.step).toBe(before.step);
    expect(after.note).toBe("m");
  });
});
