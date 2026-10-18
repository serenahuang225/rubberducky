import {
  SpeechController,
  type SpeechDriver,
  type SpeechHandlers,
} from "./speechController";

function fakeDriver(
  options: { simulated?: boolean; available?: boolean } = {},
) {
  const calls: string[] = [];
  const handlers: SpeechHandlers[] = [];
  const driver: SpeechDriver = {
    simulated: options.simulated ?? false,
    available: () => {
      calls.push("available");
      return options.available ?? true;
    },
    speak: (text, h) => {
      calls.push(`speak:${text}`);
      handlers.push(h);
    },
    stop: () => {
      calls.push("stop");
    },
  };
  return { driver, calls, handlers };
}

function ready(options: Parameters<typeof fakeDriver>[0] = {}) {
  const fake = fakeDriver(options);
  const controller = new SpeechController(fake.driver);
  controller.setAllowed(true);
  controller.setScope("s1|1|0|a1");
  return { ...fake, controller };
}

const request = (scope = "s1|1|0|a1", turnId = "t1") => ({
  turnId,
  text: "Try subtracting 6 from both sides.",
  scope,
});

describe("SpeechController lifecycle", () => {
  it("moves starting, speaking, finished from the driver's own callbacks", () => {
    const { controller, handlers } = ready();
    expect(controller.speak(request())).toBe("started");
    expect(controller.getSnapshot().phase).toBe("starting");
    handlers[0].onStart();
    expect(controller.getSnapshot().phase).toBe("speaking");
    expect(controller.getSnapshot().text).toMatch(/subtracting/);
    handlers[0].onDone();
    expect(controller.getSnapshot().phase).toBe("finished");
    expect(controller.getSnapshot().events.map((e) => e.type)).toEqual([
      "start",
      "start",
      "end",
    ]);
  });

  it("makes zero driver calls while sound is off or text-only is on", () => {
    const { driver, calls } = fakeDriver();
    const controller = new SpeechController(driver);
    controller.setScope("s1|1|0|a1");
    controller.setAllowed(false);
    expect(controller.speak(request())).toBe("suppressed");
    controller.cancel("user_stop");
    controller.clear();
    expect(calls).toEqual([]);
    expect(controller.getSnapshot().phase).toBe("idle");
    expect(controller.getSnapshot().events.at(-1)?.type).toBe("suppressed");
  });

  it("muting while speaking stops the driver once and never speaks again", () => {
    const { controller, calls, handlers } = ready();
    controller.speak(request());
    handlers[0].onStart();
    controller.setAllowed(false);
    expect(calls.filter((call) => call === "stop")).toHaveLength(1);
    expect(controller.getSnapshot()).toMatchObject({
      phase: "cancelled",
      note: expect.stringMatching(/sound is off/i),
    });
    expect(controller.speak(request())).toBe("suppressed");
    expect(calls.filter((call) => call.startsWith("speak:"))).toHaveLength(1);
  });

  it("refuses a reply whose scope is no longer current", () => {
    const { controller, calls } = ready();
    controller.setScope("s1|2|1|a1");
    expect(controller.speak(request("s1|1|0|a1"))).toBe("stale");
    expect(calls.some((call) => call.startsWith("speak:"))).toBe(false);
  });

  it("reports unavailable speech honestly without throwing", () => {
    const { controller } = ready({ available: false });
    expect(controller.speak(request())).toBe("unavailable");
    expect(controller.getSnapshot()).toMatchObject({
      phase: "unavailable",
      note: expect.stringMatching(/not available/i),
    });
  });

  it("marks the reply failed when the driver errors, leaving text untouched", () => {
    const { controller, handlers } = ready();
    controller.speak(request());
    handlers[0].onError();
    expect(controller.getSnapshot().phase).toBe("failed");
  });

  it("labels simulated speech so it is never mistaken for live audio", () => {
    const { controller } = ready({ simulated: true });
    controller.speak(request());
    expect(controller.getSnapshot().simulated).toBe(true);
  });
});

describe("SpeechController cancellation and late callbacks", () => {
  it.each([
    "user_stop",
    "new_work",
    "interrupt",
    "new_problem",
    "board_hidden",
    "unmount",
  ] as const)("%s stops speech and rejects every later callback", (reason) => {
    const { controller, calls, handlers } = ready();
    controller.speak(request());
    handlers[0].onStart();
    controller.cancel(reason);
    expect(controller.getSnapshot().phase).toBe("cancelled");
    expect(calls).toContain("stop");
    handlers[0].onStart();
    handlers[0].onDone();
    handlers[0].onError();
    expect(controller.getSnapshot().phase).toBe("cancelled");
    expect(
      controller.getSnapshot().events.filter((e) => e.type === "ignored_late"),
    ).toHaveLength(3);
  });

  it("a new epoch or generation in the scope cancels a running reply", () => {
    const { controller, handlers } = ready();
    controller.speak(request());
    handlers[0].onStart();
    controller.setScope("s1|1|1|a1");
    expect(controller.getSnapshot().phase).toBe("cancelled");
    handlers[0].onStart();
    expect(controller.getSnapshot().phase).toBe("cancelled");
  });

  it("an unchanged scope keeps speaking", () => {
    const { controller, handlers } = ready();
    controller.speak(request());
    handlers[0].onStart();
    controller.setScope("s1|1|0|a1");
    expect(controller.getSnapshot().phase).toBe("speaking");
  });

  it("a callback from a replaced reply cannot restart or finish the new one", () => {
    const { controller, handlers } = ready();
    controller.speak(request("s1|1|0|a1", "t1"));
    controller.speak(request("s1|1|0|a1", "t2"));
    handlers[1].onStart();
    handlers[0].onDone();
    expect(controller.getSnapshot()).toMatchObject({
      phase: "speaking",
      turnId: "t2",
    });
  });

  it("cancelling while idle makes no driver call but still rejects pending callbacks", () => {
    const { controller, calls, handlers } = ready();
    controller.speak(request());
    handlers[0].onDone();
    const before = calls.length;
    controller.cancel("new_work");
    expect(calls).toHaveLength(before);
    handlers[0].onStart();
    expect(controller.getSnapshot().phase).toBe("finished");
  });

  it("a following reply under the new scope speaks normally after cancellation", () => {
    const { controller, handlers } = ready();
    controller.speak(request());
    handlers[0].onStart();
    controller.setScope("s1|2|1|a2");
    expect(controller.speak(request("s1|2|1|a2", "t2"))).toBe("started");
    handlers[1].onStart();
    expect(controller.getSnapshot()).toMatchObject({
      phase: "speaking",
      turnId: "t2",
    });
  });

  it("swapping the driver stops the previous one", () => {
    const first = fakeDriver();
    const second = fakeDriver({ simulated: true });
    const controller = new SpeechController(first.driver);
    controller.setAllowed(true);
    controller.setScope("s");
    controller.speak({ turnId: "t", text: "hi", scope: "s" });
    controller.setDriver(second.driver);
    expect(first.calls).toContain("stop");
    expect(controller.getSnapshot().simulated).toBe(true);
  });

  it("keeps a bounded event trace", () => {
    const { controller } = ready();
    for (let i = 0; i < 40; i += 1) controller.speak(request("old"));
    expect(controller.getSnapshot().events.length).toBeLessThanOrEqual(24);
  });

  it("plays server audio of the tutor reply and Stop speaking ends it", () => {
    const { controller, calls } = ready();
    let stopped = false;
    const outcome = controller.playClip(request(), (handlers) => {
      handlers.onStart();
      return () => {
        stopped = true;
      };
    });
    expect(outcome).toBe("started");
    expect(controller.getSnapshot()).toMatchObject({
      phase: "speaking",
      text: "Try subtracting 6 from both sides.",
    });
    expect(calls.filter((call) => call.startsWith("speak:"))).toEqual([]);
    controller.cancel("user_stop");
    expect(stopped).toBe(true);
    expect(controller.getSnapshot().phase).toBe("cancelled");
    expect(controller.getSnapshot().note).toMatch(/stopped/i);
  });
});
