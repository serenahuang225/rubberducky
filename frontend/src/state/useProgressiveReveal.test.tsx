import { act, renderHook } from "@testing-library/react-native";

import { tutorTurnResultSchema, type TutorTurnResult } from "../api/contracts";
import { REVEAL_MAX_TOTAL_MS, type TimerApi } from "../board/progressiveReveal";
import { METHOD_SLIP_TURN } from "../testing/teachingFixtures";

import {
  useProgressiveReveal,
  type ProgressiveRevealInput,
} from "./useProgressiveReveal";

const IDS = ["m1", "m2", "m3"];

function turnWith(
  turnId: string,
  epoch: number,
  ids: string[] = IDS,
): TutorTurnResult {
  return tutorTurnResultSchema.parse({
    ...METHOD_SLIP_TURN,
    turn_id: turnId,
    cancellation_epoch: epoch,
    drawings: ids.map((id) => ({
      object_id: id,
      tool: "highlight",
      semantic_role: "emphasis",
    })),
  });
}

const base = (
  patch: Partial<ProgressiveRevealInput> = {},
): ProgressiveRevealInput => ({
  sessionId: "s1",
  turn: turnWith("t1", 2),
  generation: 1,
  epoch: 2,
  attemptId: "a1",
  presentIds: new Set(IDS),
  motion: "full",
  suspended: false,
  ...patch,
});

const hiddenList = (set: ReadonlySet<string>) => [...set].sort();

/** Real timer callbacks recorded so late invocation after cancel can be exercised. */
function recordingTimers() {
  const scheduled: { cb: () => void; ms: number; cleared: boolean }[] = [];
  const api: TimerApi = {
    set: (cb, ms) => {
      const entry = { cb, ms, cleared: false };
      scheduled.push(entry);
      return entry;
    },
    clear: (handle) => {
      (handle as { cleared: boolean }).cleared = true;
    },
  };
  return { api, scheduled };
}

describe("useProgressiveReveal", () => {
  it("reveals committed tutor marks in a bounded sequence and ends with every mark visible", () => {
    jest.useFakeTimers();
    try {
      const { result } = renderHook(
        (props: ProgressiveRevealInput) => useProgressiveReveal(props),
        {
          initialProps: base(),
        },
      );
      expect(hiddenList(result.current)).toEqual(IDS);
      act(() => {
        jest.advanceTimersByTime(300);
      });
      expect(hiddenList(result.current)).toEqual(["m2", "m3"]);
      act(() => {
        jest.advanceTimersByTime(REVEAL_MAX_TOTAL_MS);
      });
      expect(hiddenList(result.current)).toEqual([]);
    } finally {
      jest.useRealTimers();
    }
  });

  it("shows the final marks at once under reduced motion, with the same final scene", () => {
    const { result } = renderHook(
      (props: ProgressiveRevealInput) => useProgressiveReveal(props),
      {
        initialProps: base({ motion: "reduced" }),
      },
    );
    expect(hiddenList(result.current)).toEqual([]);
  });

  it("waits for the server epoch to match the turn before starting, then reveals", () => {
    jest.useFakeTimers();
    try {
      const { result, rerender } = renderHook(
        (props: ProgressiveRevealInput) => useProgressiveReveal(props),
        {
          initialProps: base({ epoch: 1, presentIds: new Set() }),
        },
      );
      expect(hiddenList(result.current)).toEqual(IDS);
      rerender(base({ epoch: 2, presentIds: new Set(IDS) }));
      act(() => {
        jest.advanceTimersByTime(300);
      });
      expect(hiddenList(result.current)).toEqual(["m2", "m3"]);
    } finally {
      jest.useRealTimers();
    }
  });

  it.each([
    ["an interruption advancing the turn generation", { generation: 2 }],
    ["the server epoch advancing", { epoch: 3 }],
    ["a different problem", { attemptId: "a2" }],
    ["a different session", { sessionId: "s2" }],
    ["the board being hidden", { suspended: true }],
    ["reduced motion being chosen", { motion: "reduced" as const }],
  ])(
    "cancels mid-sequence on %s and rejects the late scheduled callbacks",
    (_name, change) => {
      const { api, scheduled } = recordingTimers();
      const { result, rerender } = renderHook(
        (props: ProgressiveRevealInput) => useProgressiveReveal(props),
        {
          initialProps: base({ timers: api }),
        },
      );
      expect(hiddenList(result.current)).toEqual(IDS);
      expect(scheduled).toHaveLength(3);
      act(() => scheduled[0].cb());
      expect(hiddenList(result.current)).toEqual(["m2", "m3"]);
      rerender(base({ timers: api, ...change }));
      expect(scheduled.every((entry) => entry.cleared)).toBe(true);
      expect(hiddenList(result.current)).toEqual([]);
      // A callback the platform had already queued fires late: nothing may change.
      act(() => {
        scheduled[1].cb();
        scheduled[2].cb();
      });
      expect(hiddenList(result.current)).toEqual([]);
    },
  );

  it("never replays a turn after it was cancelled or finished", () => {
    jest.useFakeTimers();
    try {
      const { result, rerender } = renderHook(
        (props: ProgressiveRevealInput) => useProgressiveReveal(props),
        {
          initialProps: base(),
        },
      );
      rerender(base({ generation: 2 }));
      expect(hiddenList(result.current)).toEqual([]);
      rerender(base({ generation: 2, presentIds: new Set([...IDS, "extra"]) }));
      expect(hiddenList(result.current)).toEqual([]);
    } finally {
      jest.useRealTimers();
    }
  });

  it("does not reveal marks for a turn that an interruption already superseded before it started", () => {
    const { result, rerender } = renderHook(
      (props: ProgressiveRevealInput) => useProgressiveReveal(props),
      {
        initialProps: base({ epoch: 1, presentIds: new Set() }),
      },
    );
    expect(hiddenList(result.current)).toEqual(IDS);
    rerender(base({ epoch: 3, presentIds: new Set(IDS) }));
    expect(hiddenList(result.current)).toEqual([]);
  });

  it("clears every timer handle on unmount", () => {
    const { api, scheduled } = recordingTimers();
    const { unmount } = renderHook(
      (props: ProgressiveRevealInput) => useProgressiveReveal(props),
      {
        initialProps: base({ timers: api }),
      },
    );
    unmount();
    expect(scheduled.every((entry) => entry.cleared)).toBe(true);
  });

  it("starts a fresh sequence for the next committed turn without leaking the old one", () => {
    const { api, scheduled } = recordingTimers();
    const { result, rerender } = renderHook(
      (props: ProgressiveRevealInput) => useProgressiveReveal(props),
      {
        initialProps: base({ timers: api }),
      },
    );
    act(() => scheduled[0].cb());
    const next = ["n1", "n2"];
    rerender(
      base({
        timers: api,
        turn: turnWith("t2", 4, next),
        epoch: 4,
        presentIds: new Set([...IDS, ...next]),
      }),
    );
    expect(scheduled.slice(0, 3).every((entry) => entry.cleared)).toBe(true);
    expect(hiddenList(result.current)).toEqual(next);
    act(() => scheduled[1].cb());
    expect(hiddenList(result.current)).toEqual(next);
    act(() => scheduled[3].cb());
    expect(hiddenList(result.current)).toEqual(["n2"]);
  });
});
