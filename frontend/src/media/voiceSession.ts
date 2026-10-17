/**
 * Transcript text as the learner sees it: provisional until the server accepts a final.
 *
 * Real transcription is not configured, so every transcript here comes from the labeled
 * simulated script below. The server decides what each event means (provisional, final,
 * duplicate, late); this reducer only mirrors that answer, so interim text can never become
 * final work, a duplicate final changes nothing and a late interim cannot reopen an utterance.
 * Final text is an offer: it reaches the tutor only when the learner sends it as typed work.
 */

import type { MediaEventRequest, MediaEventResult } from "../api/contracts";
import { newId } from "../api/ids";

export type VoiceState = {
  utteranceId: string | null;
  /** Latest interim text, replaced by each revision; never treated as final. */
  provisional: string | null;
  /** The accepted final text, offered for the learner to confirm or edit. */
  final: string | null;
  /** Plain explanation of the last event, including ignored duplicates and late updates. */
  note: string | null;
  /** True between the first interim and the final of one simulated utterance. */
  active: boolean;
  step: number;
};

export const VOICE_IDLE: VoiceState = {
  utteranceId: null,
  provisional: null,
  final: null,
  note: null,
  active: false,
  step: 0,
};

type TranscriptRequest = Extract<MediaEventRequest, { kind: "transcript" }>;

type ScriptStep = {
  phase: "interim" | "final";
  text: string;
  /** Short label for the control that plays this step. */
  label: string;
};

/** One deterministic utterance: revised interim, final, duplicate final, then a late interim. */
export const SIMULATED_VOICE_SCRIPT: readonly ScriptStep[] = [
  { phase: "interim", text: "2x plus 3", label: "interim" },
  { phase: "interim", text: "2x plus 3 equals 1", label: "revised interim" },
  { phase: "final", text: "2x + 3 = 14", label: "final" },
  { phase: "final", text: "2x + 3 = 14", label: "duplicate final" },
  { phase: "interim", text: "2x plus 3 equals 14 and", label: "late interim" },
];

export function nextScriptStep(state: VoiceState): ScriptStep | null {
  return SIMULATED_VOICE_SCRIPT[state.step] ?? null;
}

export function buildTranscriptEvent(state: VoiceState): {
  request: TranscriptRequest;
  utteranceId: string;
} | null {
  const step = nextScriptStep(state);
  if (step === null) return null;
  const utteranceId = state.utteranceId ?? `utt-${newId()}`;
  return {
    utteranceId,
    request: {
      kind: "transcript",
      event_id: `mev-${newId()}`,
      source: "simulated",
      utterance_id: utteranceId,
      sequence: state.step + 1,
      phase: step.phase,
      text: step.text,
    },
  };
}

export function applyTranscriptResult(
  state: VoiceState,
  request: TranscriptRequest,
  result: MediaEventResult,
): VoiceState {
  const base = { ...state, utteranceId: request.utterance_id, step: state.step + 1 };
  switch (result.status) {
    case "provisional":
      return {
        ...base,
        provisional: request.text,
        final: null,
        active: true,
        note: "Simulated interim text. It is provisional and has not been checked.",
      };
    case "final_accepted":
      return {
        ...base,
        provisional: null,
        final: request.text,
        active: false,
        note: "Simulated final text. Confirm or edit it before sending; nothing was submitted.",
      };
    case "duplicate_final":
      return { ...base, note: "A repeated final was ignored. It was not counted twice." };
    case "ignored_late":
      return { ...base, note: "A late update after the final was ignored." };
    default:
      return { ...state, note: result.message };
  }
}
