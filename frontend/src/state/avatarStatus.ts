/**
 * The tiny avatar's status, derived only from real application lifecycle facts.
 *
 * "Listening" and "speaking" exist only when a media source reports them (live or labeled
 * simulated) and the learner's text-only/mute choices allow that channel. Nothing is inferred
 * from silence, and no state claims the tutor understands or is competent.
 */

export type AvatarState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "waiting"
  | "reconnecting"
  | "error";

export type MediaActivity = {
  kind: "listening" | "speaking";
  /** Deterministic fixture events are labeled simulated and prove nothing about live media. */
  source: "live" | "simulated";
};

export type AvatarInputs = {
  /** A tutor command (turn, check-in, help) is running. */
  busy: boolean;
  /** The last request never reached the tutor service. */
  connectionLost: boolean;
  unsavedChanges: number;
  /** The last command was rejected or failed definitively. */
  failed: boolean;
  /** The learner explicitly said they are still thinking. */
  waiting: boolean;
  media: MediaActivity | null;
  mediaAllowed: { listening: boolean; speaking: boolean };
};

export type AvatarStatus = {
  state: AvatarState;
  /** Short visible text, also the accessible name of the status. */
  label: string;
  description: string;
  simulated: boolean;
};

function status(
  state: AvatarState,
  label: string,
  description: string,
  simulated = false,
): AvatarStatus {
  return { state, label, description, simulated };
}

export function deriveAvatarStatus(inputs: AvatarInputs): AvatarStatus {
  if (inputs.connectionLost || inputs.unsavedChanges > 0) {
    return status(
      "reconnecting",
      "Reconnecting",
      "The tutor cannot be reached right now. Your work is kept and will save when it is back.",
    );
  }
  if (inputs.failed) {
    return status(
      "error",
      "Something went wrong",
      "The last request could not be completed. Your work is unchanged.",
    );
  }
  if (inputs.busy) {
    return status(
      "thinking",
      "Thinking",
      "The tutor is preparing a reply to your last action.",
    );
  }
  const media = inputs.media;
  if (media !== null) {
    const allowed =
      media.kind === "listening"
        ? inputs.mediaAllowed.listening
        : inputs.mediaAllowed.speaking;
    if (allowed) {
      const simulated = media.source === "simulated";
      const verb = media.kind === "listening" ? "Listening" : "Speaking";
      return status(
        media.kind,
        simulated ? `${verb} (simulated)` : verb,
        simulated
          ? `Simulated ${media.kind} event for testing; this is not live audio.`
          : media.kind === "listening"
            ? "The microphone you turned on is open."
            : "The tutor is reading its reply aloud.",
        simulated,
      );
    }
  }
  if (inputs.waiting) {
    return status(
      "waiting",
      "Waiting for you",
      "You said you are still thinking, so the tutor waits.",
    );
  }
  return status(
    "idle",
    "Ready",
    "Nothing is running. Type or draw your next step whenever you are ready.",
  );
}
