/**
 * Owns spoken tutor replies and their captions.
 *
 * A reply is spoken only when the learner's policy allows sound; otherwise the driver is never
 * called at all (not even to stop). Every spoken reply belongs to one scope (session, turn
 * generation, server cancellation epoch, problem and turn). A different scope, Stop, new work,
 * muting, a new problem or unmount bumps the token and stops the driver, and any callback the
 * driver delivers afterwards is recorded as ignored: late audio can never restart speech,
 * re-show a caption or touch the board. Speech is output only; nothing here is transcription
 * or acoustic barge-in.
 */

export type SpeechHandlers = {
  onStart: () => void;
  onDone: () => void;
  /** The platform ended speech without being asked (for example another app took audio). */
  onStopped: () => void;
  onError: () => void;
};

export type SpeechDriver = {
  /** Deterministic fixture speech is labeled simulated and proves nothing about live audio. */
  simulated: boolean;
  available: () => boolean;
  speak: (text: string, handlers: SpeechHandlers) => void;
  stop: () => void;
};

export type SpeechPhase =
  | "idle"
  | "starting"
  | "speaking"
  | "finished"
  | "cancelled"
  | "failed"
  | "unavailable";

export type SpeechCancelReason =
  | "user_stop"
  | "new_work"
  | "interrupt"
  | "new_problem"
  | "scope_changed"
  | "muted"
  | "board_hidden"
  | "unmount";

export type SpeechEvent = {
  seq: number;
  type:
    | "start"
    | "end"
    | "cancel"
    | "error"
    | "suppressed"
    | "stale_request"
    | "ignored_late";
  detail: string;
};

export type SpeechSnapshot = {
  phase: SpeechPhase;
  /** The reply being or last spoken, shown as a caption while speaking. */
  text: string | null;
  turnId: string | null;
  simulated: boolean;
  note: string | null;
  /** Bounded, ordered lifecycle trace. */
  events: readonly SpeechEvent[];
};

export type SpeakRequest = {
  turnId: string;
  text: string;
  /** Must equal the scope in force when the callback arrives, or the reply is dropped. */
  scope: string;
};

export type SpeakOutcome = "started" | "suppressed" | "stale" | "unavailable";

const MAX_EVENTS = 24;
const MAX_SPOKEN_CHARS = 600;

const CANCEL_NOTE: Record<SpeechCancelReason, string> = {
  user_stop: "Speech stopped.",
  new_work: "Speech stopped because you sent new work.",
  interrupt: "Speech stopped because you stopped the reply.",
  new_problem: "Speech stopped because the problem changed.",
  scope_changed: "Speech stopped because the board moved on.",
  muted: "Speech stopped because sound is off.",
  board_hidden: "Speech stopped because you left the board.",
  unmount: "Speech stopped.",
};

const INITIAL: SpeechSnapshot = {
  phase: "idle",
  text: null,
  turnId: null,
  simulated: false,
  note: null,
  events: [],
};

export class SpeechController {
  private snapshot: SpeechSnapshot = INITIAL;
  private readonly listeners = new Set<() => void>();
  private token = 0;
  private seq = 0;
  private scope: string | null = null;
  private allowed = false;
  private driverActive = false;
  private clipStop: (() => void) | null = null;

  constructor(private driver: SpeechDriver) {}

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): SpeechSnapshot => this.snapshot;

  /** Swapping the driver (device or simulated voice) always stops the previous one first. */
  setDriver(driver: SpeechDriver): void {
    if (driver === this.driver) return;
    this.cancel("scope_changed");
    this.driver = driver;
    this.set({ simulated: driver.simulated });
  }

  private set(patch: Partial<SpeechSnapshot>, event?: Omit<SpeechEvent, "seq">) {
    const events =
      event === undefined
        ? this.snapshot.events
        : [...this.snapshot.events, { ...event, seq: ++this.seq }].slice(
            -MAX_EVENTS,
          );
    this.snapshot = { ...this.snapshot, ...patch, events };
    this.listeners.forEach((listener) => listener());
  }

  /** The scope the learner is in now; speech started under any other scope is cancelled. */
  setScope(scope: string): void {
    if (this.scope !== null && this.scope !== scope) {
      this.cancel("scope_changed");
    }
    this.scope = scope;
  }

  /** False means sound is muted or text-only; a running reply is stopped. */
  setAllowed(allowed: boolean): void {
    this.allowed = allowed;
    if (!allowed) this.cancel("muted");
  }

  speak(request: SpeakRequest): SpeakOutcome {
    if (!this.allowed) {
      this.set(
        {},
        { type: "suppressed", detail: "sound is off or text-only is on" },
      );
      return "suppressed";
    }
    if (request.scope !== this.scope) {
      this.set({}, { type: "stale_request", detail: request.turnId });
      return "stale";
    }
    const spoken = request.text.trim().slice(0, MAX_SPOKEN_CHARS);
    if (spoken.length === 0) return "suppressed";
    if (!this.driver.available()) {
      this.set(
        {
          phase: "unavailable",
          text: null,
          turnId: request.turnId,
          note: "Spoken replies are not available on this device. Captions and text stay on.",
        },
        { type: "error", detail: "driver unavailable" },
      );
      return "unavailable";
    }
    this.stopDriver();
    const token = ++this.token;
    const scope = request.scope;
    const live = () => token === this.token && scope === this.scope;
    const late = (what: string) =>
      this.set({}, { type: "ignored_late", detail: what });
    this.set(
      {
        phase: "starting",
        text: spoken,
        turnId: request.turnId,
        simulated: this.driver.simulated,
        note: null,
      },
      { type: "start", detail: "requested" },
    );
    this.driverActive = true;
    try {
      this.driver.speak(spoken, {
        onStart: () => {
          if (!live()) return late("start");
          this.set({ phase: "speaking" }, { type: "start", detail: "speaking" });
        },
        onDone: () => {
          if (!live()) return late("done");
          this.driverActive = false;
          this.set({ phase: "finished" }, { type: "end", detail: "finished" });
        },
        onStopped: () => {
          if (!live()) return late("stopped");
          this.driverActive = false;
          this.set(
            { phase: "cancelled", note: "Speech was stopped by the device." },
            { type: "cancel", detail: "device" },
          );
        },
        onError: () => {
          if (!live()) return late("error");
          this.driverActive = false;
          this.set(
            {
              phase: "failed",
              note: "Spoken reply failed. The written reply is unchanged.",
            },
            { type: "error", detail: "driver error" },
          );
        },
      });
    } catch {
      this.driverActive = false;
      this.token += 1;
      this.set(
        {
          phase: "failed",
          note: "Spoken reply failed. The written reply is unchanged.",
        },
        { type: "error", detail: "driver threw" },
      );
      return "unavailable";
    }
    return "started";
  }

  /**
   * Play audio the server already synthesized from the tutor's reply.
   * `start` returns the function that stops playback. The text is the caption.
   */
  playClip(
    request: SpeakRequest,
    start: (handlers: SpeechHandlers) => () => void,
  ): SpeakOutcome {
    if (!this.allowed) {
      this.set(
        {},
        { type: "suppressed", detail: "sound is off or text-only is on" },
      );
      return "suppressed";
    }
    if (request.scope !== this.scope) {
      this.set({}, { type: "stale_request", detail: request.turnId });
      return "stale";
    }
    const spoken = request.text.trim().slice(0, MAX_SPOKEN_CHARS);
    if (spoken.length === 0) return "suppressed";
    this.stopDriver();
    const token = ++this.token;
    const scope = request.scope;
    const live = () => token === this.token && scope === this.scope;
    const late = (what: string) =>
      this.set({}, { type: "ignored_late", detail: what });
    this.set(
      {
        phase: "starting",
        text: spoken,
        turnId: request.turnId,
        simulated: false,
        note: null,
      },
      { type: "start", detail: "recorded" },
    );
    try {
      this.clipStop = start({
        onStart: () => {
          if (!live()) return late("start");
          this.set({ phase: "speaking" }, { type: "start", detail: "speaking" });
        },
        onDone: () => {
          if (!live()) return late("done");
          this.clipStop = null;
          this.set({ phase: "finished" }, { type: "end", detail: "finished" });
        },
        onStopped: () => {
          if (!live()) return late("stopped");
          this.clipStop = null;
          this.set(
            { phase: "cancelled", note: "Speech was stopped by the device." },
            { type: "cancel", detail: "device" },
          );
        },
        onError: () => {
          if (!live()) return late("error");
          this.clipStop = null;
          this.set(
            {
              phase: "failed",
              note: "Spoken reply failed. The written reply is unchanged.",
            },
            { type: "error", detail: "playback error" },
          );
        },
      });
    } catch {
      this.clipStop = null;
      this.token += 1;
      this.set(
        {
          phase: "failed",
          note: "Spoken reply failed. The written reply is unchanged.",
        },
        { type: "error", detail: "playback threw" },
      );
      return "unavailable";
    }
    return "started";
  }

  private stopDriver(): void {
    if (this.clipStop !== null) {
      const stop = this.clipStop;
      this.clipStop = null;
      try {
        stop();
      } catch {
        // Stopping is best effort; the token already rejects whatever arrives later.
      }
    }
    if (!this.driverActive) return;
    this.driverActive = false;
    try {
      this.driver.stop();
    } catch {
      // Stopping is best effort; the token already rejects whatever arrives later.
    }
  }

  cancel(reason: SpeechCancelReason): void {
    // Always advance the token so nothing scheduled earlier can fire, even when idle.
    this.token += 1;
    const active =
      this.snapshot.phase === "starting" || this.snapshot.phase === "speaking";
    this.stopDriver();
    if (!active) return;
    this.set(
      { phase: "cancelled", note: CANCEL_NOTE[reason] },
      { type: "cancel", detail: reason },
    );
  }

  /** Forget a finished/cancelled reply's caption once the learner moves on. */
  clear(): void {
    if (this.snapshot.phase === "starting" || this.snapshot.phase === "speaking")
      return;
    this.set({ phase: "idle", text: null, turnId: null, note: null });
  }
}
