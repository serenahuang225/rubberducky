import { createSimulatedSpeechDriver } from "./speechDriver";

jest.mock("expo-speech", () => ({ speak: jest.fn(), stop: jest.fn() }));

function manualTimers() {
  let next = 1;
  const queue = new Map<number, { fn: () => void; ms: number }>();
  return {
    timers: {
      setTimeout: (fn: () => void, ms: number) => {
        queue.set(next, { fn, ms });
        return next++;
      },
      clearTimeout: (handle: unknown) => {
        queue.delete(handle as number);
      },
    },
    flush: () => {
      for (const [id, entry] of [...queue].sort((a, b) => a[1].ms - b[1].ms)) {
        queue.delete(id);
        entry.fn();
      }
    },
    size: () => queue.size,
  };
}

describe("simulated speech driver", () => {
  const handlers = () => ({
    onStart: jest.fn(),
    onDone: jest.fn(),
    onStopped: jest.fn(),
    onError: jest.fn(),
  });

  it("is labeled simulated and reports start then done", () => {
    const { timers, flush } = manualTimers();
    const driver = createSimulatedSpeechDriver(1000, timers);
    const h = handlers();
    expect(driver.simulated).toBe(true);
    driver.speak("hello", h);
    flush();
    expect(h.onStart).toHaveBeenCalledTimes(1);
    expect(h.onDone).toHaveBeenCalledTimes(1);
  });

  it("stopping clears the pending callbacks so a stopped reply never finishes", () => {
    const { timers, flush, size } = manualTimers();
    const driver = createSimulatedSpeechDriver(1000, timers);
    const h = handlers();
    driver.speak("hello", h);
    driver.stop();
    expect(size()).toBe(0);
    flush();
    expect(h.onStart).not.toHaveBeenCalled();
    expect(h.onDone).not.toHaveBeenCalled();
  });
});
