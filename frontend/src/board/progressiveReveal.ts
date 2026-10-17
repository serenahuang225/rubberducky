/**
 * Brief, bounded progressive reveal of committed tutor marks.
 *
 * The marks already exist in the authoritative scene; this only withholds them from view for
 * a documented short sequence (at most REVEAL_MAX_TOTAL_MS, one mark per step). Every timer
 * handle is owned by the controller and every callback carries its run token, so cancelling,
 * or starting a newer run, makes any callback still in flight a no-op. Cancelling reveals the
 * remainder immediately, so the final board never depends on the animation having run.
 */

export const REVEAL_MAX_STEP_MS = 300;
export const REVEAL_MAX_TOTAL_MS = 1200;

export type TimerApi = {
  set: (callback: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
};

export const realTimers: TimerApi = {
  set: (callback, ms) => setTimeout(callback, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** Cumulative reveal times: mark i appears at delays[i]; the last is within the total bound. */
export function revealDelays(count: number): number[] {
  if (count <= 0) return [];
  const step = Math.min(REVEAL_MAX_STEP_MS, REVEAL_MAX_TOTAL_MS / count);
  return Array.from({ length: count }, (_, index) =>
    Math.round(step * (index + 1)),
  );
}

export class RevealController {
  private run = 0;
  private handles: unknown[] = [];
  private hiddenIds = new Set<string>();

  constructor(
    private readonly timers: TimerApi,
    private readonly onChange: (hidden: ReadonlySet<string>) => void,
  ) {}

  get hidden(): ReadonlySet<string> {
    return this.hiddenIds;
  }

  get running(): boolean {
    return this.hiddenIds.size > 0;
  }

  start(ids: readonly string[]): void {
    this.clearTimers();
    const token = ++this.run;
    this.hiddenIds = new Set(ids);
    const delays = revealDelays(ids.length);
    ids.forEach((id, index) => {
      this.handles.push(
        this.timers.set(() => {
          if (token !== this.run) return;
          const next = new Set(this.hiddenIds);
          next.delete(id);
          this.hiddenIds = next;
          this.onChange(next);
        }, delays[index]),
      );
    });
    this.onChange(this.hiddenIds);
  }

  /** Stop the sequence and show everything that is on the board. */
  cancel(): void {
    this.run += 1;
    this.clearTimers();
    if (this.hiddenIds.size === 0) return;
    this.hiddenIds = new Set();
    this.onChange(this.hiddenIds);
  }

  private clearTimers(): void {
    for (const handle of this.handles) this.timers.clear(handle);
    this.handles = [];
  }
}
