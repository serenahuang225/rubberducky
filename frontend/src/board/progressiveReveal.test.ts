import {
  REVEAL_MAX_STEP_MS,
  REVEAL_MAX_TOTAL_MS,
  RevealController,
  revealDelays,
  type TimerApi,
} from "./progressiveReveal";

function fakeTimers() {
  let next = 1;
  const pending = new Map<number, { cb: () => void; ms: number }>();
  const api: TimerApi = {
    set: (cb, ms) => {
      const handle = next++;
      pending.set(handle, { cb, ms });
      return handle;
    },
    clear: (handle) => {
      pending.delete(handle as number);
    },
  };
  return {
    api,
    pending,
    /** Fire every currently scheduled callback in delay order, including ones already cleared. */
    snapshot: () => [...pending.entries()].sort((a, b) => a[1].ms - b[1].ms),
  };
}

describe("revealDelays", () => {
  it("spreads marks over a short bounded sequence", () => {
    expect(revealDelays(1)).toEqual([REVEAL_MAX_STEP_MS]);
    const many = revealDelays(10);
    expect(many).toHaveLength(10);
    expect(many[many.length - 1]).toBeLessThanOrEqual(REVEAL_MAX_TOTAL_MS);
    expect(many).toEqual([...many].sort((a, b) => a - b));
  });
  it("is empty when there is nothing to reveal", () => {
    expect(revealDelays(0)).toEqual([]);
  });
});

describe("RevealController", () => {
  it("hides every planned mark, then reveals them in order on the real timers", () => {
    const timers = fakeTimers();
    const changes: string[][] = [];
    const controller = new RevealController(timers.api, (hidden) =>
      changes.push([...hidden]),
    );
    controller.start(["a", "b", "c"]);
    expect([...controller.hidden]).toEqual(["a", "b", "c"]);
    const scheduled = timers.snapshot();
    expect(scheduled).toHaveLength(3);
    expect(scheduled[2][1].ms).toBeLessThanOrEqual(REVEAL_MAX_TOTAL_MS);
    for (const [, entry] of scheduled) entry.cb();
    expect([...controller.hidden]).toEqual([]);
    expect(controller.running).toBe(false);
    expect(changes[changes.length - 1]).toEqual([]);
  });

  it("cancel reveals the final geometry and clears every handle", () => {
    const timers = fakeTimers();
    const controller = new RevealController(timers.api, () => undefined);
    controller.start(["a", "b"]);
    controller.cancel();
    expect(timers.pending.size).toBe(0);
    expect([...controller.hidden]).toEqual([]);
    expect(controller.running).toBe(false);
  });

  it("rejects a late callback captured before cancel", () => {
    const timers = fakeTimers();
    const onChange = jest.fn();
    const controller = new RevealController(timers.api, onChange);
    controller.start(["a", "b"]);
    const captured = timers.snapshot().map(([, entry]) => entry.cb);
    controller.cancel();
    onChange.mockClear();
    captured.forEach((cb) => cb());
    expect(onChange).not.toHaveBeenCalled();
    expect([...controller.hidden]).toEqual([]);
  });

  it("a late callback from an older run cannot touch a newer run", () => {
    const timers = fakeTimers();
    const controller = new RevealController(timers.api, () => undefined);
    controller.start(["old"]);
    const oldCallbacks = timers.snapshot().map(([, entry]) => entry.cb);
    controller.start(["new-1", "new-2"]);
    oldCallbacks.forEach((cb) => cb());
    expect([...controller.hidden].sort()).toEqual(["new-1", "new-2"]);
    expect(controller.running).toBe(true);
  });

  it("starting an empty plan hides nothing and schedules nothing", () => {
    const timers = fakeTimers();
    const controller = new RevealController(timers.api, () => undefined);
    controller.start([]);
    expect(timers.pending.size).toBe(0);
    expect(controller.running).toBe(false);
  });
});
