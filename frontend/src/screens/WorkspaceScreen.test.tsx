/**
 * WorkspaceScreen journey controls, driven through the REAL ApiClient with a fake fetch
 * transport that records every request. These tests pin the honesty rules:
 *
 * - "Still thinking" may post ONLY explicit wait metadata: it never submits work, checks
 *   in, asks for help or mutates the scene, and it leaves the draft, problem and board
 *   untouched. Idle time alone never posts anything.
 * - Help me uses /help (not synthesized work) and works before any timer expires.
 * - Verifier and reasoning judgments, disclosure and representation are shown as the server
 *   reported them, with a read-only diagnostic inspector.
 * - The tutor's provider identity is shown honestly (the mock says it is a mock), and
 *   "Finish for today" really ends the session and hands control back to the app.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import React from "react";
import { View } from "react-native";

import { ApiClient } from "../api/client";
import type { TutorConfiguration } from "../api/contracts";

import { BoardInputLayer } from "../components/BoardInputLayer";
import {
  METHOD_SLIP_TURN,
  WAIT_PREFERENCE,
  WAIT_STATE,
} from "../testing/teachingFixtures";

import { WorkspaceScreen } from "./WorkspaceScreen";

const SESSION_ID = "s1";

const PERSONA: TutorConfiguration = {
  schema_version: "tutor-configuration.v1",
  id: "cfg-1",
  learner_id: "learner-1",
  appearance: "animal",
  personality: "gentle",
  comfort_override: "none",
  chosen_at: "2026-10-17T00:00:00.000Z",
  last_changed_at: "2026-10-17T00:00:00.000Z",
  comfort_updated_at: null,
};

const READINESS = {
  schema_version: "model-readiness.v1",
  provider: "mock",
  state: "ready",
  ready: true,
  is_mock: true,
  label: "Deterministic mock tutor (not a language model)",
  model_id: null,
  model_revision: null,
  detail:
    "The demo tutor renders deterministic wording; no language model is involved.",
};

const SESSION = {
  schema_version: "session.v1",
  id: SESSION_ID,
  learner_id: "learner-1",
  status: "active",
  goal: "solve_equations_with_parentheses",
  revision: 1,
  started_at: "2026-10-17T00:00:00.000Z",
  ended_at: null,
};

const SESSION_STATE = {
  schema_version: "session-state.v1",
  session: SESSION,
  current_problem: {
    problem_id: "problem.distribute",
    attempt_id: "attempt-1",
    statement: "2(x + 3) = 14",
    kind: "practice",
    concept_id: "concept.distribution",
    statement_object_id: "obj-statement",
  },
  pace: "standard",
  pending_turn_id: null,
  session_context_recheck: false,
  persona: PERSONA,
};

const SCENE = {
  schema_version: "scene-snapshot.v1",
  session_id: SESSION_ID,
  scene_revision: 1,
  board_width: 1600,
  board_height: 1200,
  pen_width: 3,
  objects: [
    {
      schema_version: "scene-object.v1",
      id: "obj-statement",
      learner_id: "learner-1",
      session_id: SESSION_ID,
      author_role: "tutor",
      semantic_role: "problem_statement",
      kind: "text",
      payload: { text: "2(x + 3) = 14", x: 80, y: 120, color_role: "tutor" },
      teaching_step_id: null,
      created_at: "2026-10-17T00:00:00.000Z",
      deleted_at: null,
    },
  ],
  student_undo_available: false,
  student_redo_available: false,
  tutor_move_undo_available: false,
};

type RecordedRequest = { method: string; url: string; body: unknown };

function makeFakeApi() {
  const requests: RecordedRequest[] = [];
  const control = {
    failState: false,
    waitSeconds: 45,
    turn: METHOD_SLIP_TURN as Record<string, unknown>,
    waitFails: false,
  };
  const respond = (status: number, body: unknown) =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }) as Response;
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    requests.push({
      method,
      url,
      body:
        init?.body !== undefined ? JSON.parse(String(init.body)) : undefined,
    });
    if (url.endsWith(`/sessions/${SESSION_ID}/state`)) {
      if (control.failState) {
        return respond(500, {
          schema_version: "error.v1",
          error: { code: "boom", message: "Database unavailable" },
        });
      }
      return respond(200, SESSION_STATE);
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/scene`)) {
      return respond(200, SCENE);
    }
    if (url.endsWith("/health/model")) {
      return respond(200, READINESS);
    }
    if (url.endsWith("/me/wait-preference")) {
      if (method === "PUT") {
        control.waitSeconds = (
          JSON.parse(String(init?.body)) as { wait_seconds: number }
        ).wait_seconds;
      }
      return respond(200, {
        ...WAIT_PREFERENCE,
        wait_seconds: control.waitSeconds,
      });
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/wait`)) {
      return respond(200, { ...WAIT_STATE, wait_seconds: control.waitSeconds });
    }
    if (
      url.endsWith(`/sessions/${SESSION_ID}/still-thinking`) &&
      method === "POST"
    ) {
      if (control.waitFails) throw new TypeError("Network request failed");
      return respond(200, {
        ...WAIT_STATE,
        still_thinking_count: 1,
        still_thinking_at: WAIT_STATE.now,
      });
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/work`) && method === "POST") {
      return respond(200, control.turn);
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/help`) && method === "POST") {
      return respond(200, control.turn);
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/end`) && method === "POST") {
      return respond(200, {
        ...SESSION,
        status: "ended",
        ended_at: "2026-10-17T01:00:00.000Z",
      });
    }
    return respond(404, {
      schema_version: "error.v1",
      error: { code: "not_found", message: url },
    });
  }) as typeof fetch;
  return { requests, control, fetchImpl };
}

/** Flattened visible text of a rendered Text node, whatever its child structure. */
function textOf(node: { props: { children?: unknown } }): string {
  const flatten = (value: unknown): string =>
    Array.isArray(value)
      ? value.map(flatten).join("")
      : value == null
        ? ""
        : String(value);
  return flatten(node.props.children);
}

function renderWorkspace(fetchImpl: typeof fetch, onSessionEnded = jest.fn()) {
  const client = new ApiClient("http://tutor.test", "token", fetchImpl);
  const screen = render(
    <WorkspaceScreen
      client={client}
      sessionId={SESSION_ID}
      persona={PERSONA}
      displayName="Riley"
      onSessionEnded={onSessionEnded}
    />,
  );
  return { ...screen, onSessionEnded };
}

/** Every tutor/board mutation call the client made (plain GET reads are always allowed). */
function mutatingRequests(
  requests: readonly RecordedRequest[],
): RecordedRequest[] {
  return requests.filter((request) => request.method !== "GET");
}

describe("WorkspaceScreen", () => {
  it("Still thinking posts only wait metadata and leaves draft, problem and board unchanged", async () => {
    const { requests, fetchImpl } = makeFakeApi();
    const screen = renderWorkspace(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );
    expect(textOf(screen.getByTestId("prompt-problem"))).toBe("2(x + 3) = 14");
    const boardLabel =
      screen.getByTestId("whiteboard").props.accessibilityLabel;

    // The learner has an unfinished typed draft and taps Still thinking twice.
    fireEvent.changeText(screen.getByTestId("typed-step-input"), "2x +");
    fireEvent.press(screen.getByTestId("still-thinking"));
    fireEvent.press(screen.getByTestId("still-thinking"));

    // A truthful acknowledgement appears once the server recorded the explicit signal.
    await waitFor(() =>
      expect(textOf(screen.getByTestId("prompt-status"))).toBe(
        "Take your time — your tutor will wait.",
      ),
    );
    // The only mutating calls are the explicit wait signals: no work, check-in, help,
    // scene operation, preference write or session end.
    const mutations = mutatingRequests(requests);
    expect(mutations.length).toBeGreaterThanOrEqual(1);
    for (const request of mutations) {
      expect(request.method).toBe("POST");
      expect(request.url).toBe(
        `http://tutor.test/sessions/${SESSION_ID}/still-thinking`,
      );
      expect(request.body).toBeUndefined();
    }
    // The draft, the posed problem and the board are exactly as before.
    expect(screen.getByTestId("typed-step-input").props.value).toBe("2x +");
    expect(textOf(screen.getByTestId("prompt-problem"))).toBe("2(x + 3) = 14");
    expect(screen.getByTestId("whiteboard").props.accessibilityLabel).toBe(
      boardLabel,
    );
    expect(boardLabel).toBe("Whiteboard: 0 of your marks, 1 tutor marks");
    // No tutor words, representation or diagnostic appeared from a wait signal.
    expect(screen.queryByTestId("prompt-tutor")).toBeNull();
    expect(screen.queryByTestId("teaching-context")).toBeNull();
  });

  it("says so plainly when the wait signal could not be recorded, without retrying", async () => {
    const { control, requests, fetchImpl } = makeFakeApi();
    control.waitFails = true;
    const screen = renderWorkspace(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );
    fireEvent.press(screen.getByTestId("still-thinking"));
    await waitFor(() =>
      expect(textOf(screen.getByTestId("prompt-status"))).toMatch(
        /could not tell/i,
      ),
    );
    expect(mutatingRequests(requests)).toHaveLength(1);
    expect(screen.getByTestId("typed-step-input").props.value).toBe("");
  });

  it("Help me uses /help immediately, not synthesized work, and shows the committed move", async () => {
    const { requests, fetchImpl } = makeFakeApi();
    const screen = renderWorkspace(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );

    fireEvent.press(screen.getByTestId("help-me"));
    await waitFor(() =>
      expect(screen.getByTestId("prompt-tutor")).toBeTruthy(),
    );

    const mutations = mutatingRequests(requests);
    expect(mutations.map((request) => request.url)).toEqual([
      `http://tutor.test/sessions/${SESSION_ID}/help`,
    ]);
    expect(mutations[0].body).toEqual({
      schema_version: "help-request.v1",
      expected_revision: 1,
      mode: "hint",
    });
    expect(textOf(screen.getByTestId("prompt-tutor"))).toMatch(/does work/);
  });

  it("shows distinct mathematical and reasoning judgments and denies independent credit", async () => {
    const { fetchImpl } = makeFakeApi();
    const screen = renderWorkspace(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );
    fireEvent.changeText(
      screen.getByTestId("typed-step-input"),
      "x = 4 because I multiplied 2 by x but left 3 unchanged",
    );
    fireEvent.press(screen.getByTestId("submit-step"));
    await waitFor(() =>
      expect(screen.getByTestId("teaching-context")).toBeTruthy(),
    );

    expect(textOf(screen.getByTestId("teaching-math"))).toMatch(
      /solves the equation/i,
    );
    expect(textOf(screen.getByTestId("teaching-reasoning"))).toMatch(
      /tentative/i,
    );
    expect(textOf(screen.getByTestId("teaching-independence"))).toMatch(
      /not counted as independent/i,
    );
    expect(textOf(screen.getByTestId("teaching-representation"))).toContain(
      "Outside factor",
    );
    expect(screen.queryByTestId("teaching-disclosure")).toBeNull();
  });

  it("keeps the diagnostic inspector read-only, collapsed until asked, and source-cited", async () => {
    const { requests, fetchImpl } = makeFakeApi();
    const screen = renderWorkspace(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );
    fireEvent.changeText(screen.getByTestId("typed-step-input"), "2x + 3 = 14");
    fireEvent.press(screen.getByTestId("submit-step"));
    await waitFor(() =>
      expect(screen.getByTestId("diagnostic-toggle")).toBeTruthy(),
    );
    expect(screen.queryByTestId("diagnostic-panel")).toBeNull();
    const before = requests.length;

    fireEvent.press(screen.getByTestId("diagnostic-toggle"));
    expect(textOf(screen.getByTestId("diagnostic-hypothesis"))).toContain(
      "May be distributing to only the first term",
    );
    expect(textOf(screen.getByTestId("diagnostic-confidence"))).toMatch(/40%/);
    expect(textOf(screen.getByTestId("diagnostic-confidence"))).toMatch(
      /tentative/i,
    );
    expect(
      screen.getByText(/A copying slip rather than a method gap/),
    ).toBeTruthy();
    expect(textOf(screen.getByTestId("diagnostic-sources"))).toContain("obs-1");
    expect(textOf(screen.getByTestId("diagnostic-counter-sources"))).toContain(
      "obs-0",
    );
    expect(textOf(screen.getByTestId("diagnostic-justification"))).toMatch(
      /skips a term/,
    );
    // Inspection is purely local: no request, no edit control.
    expect(requests.length).toBe(before);
    expect(screen.queryByText(/delete|correct this|edit/i)).toBeNull();

    fireEvent.press(screen.getByTestId("diagnostic-toggle"));
    expect(screen.queryByTestId("diagnostic-panel")).toBeNull();
  });

  it("discloses a revealed answer and a reduced-support move in the visible context", async () => {
    const { control, fetchImpl } = makeFakeApi();
    control.turn = {
      ...METHOD_SLIP_TURN,
      action_type: "explain_on_request",
      answer_revealed: true,
      support_change: "reduced",
      hint_level: 4,
      representation: "worked_step",
      hypothesis: null,
    };
    const screen = renderWorkspace(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );
    fireEvent.press(screen.getByTestId("help-me"));
    await waitFor(() =>
      expect(screen.getByTestId("teaching-disclosure")).toBeTruthy(),
    );
    expect(textOf(screen.getByTestId("teaching-disclosure"))).toMatch(
      /assisted/i,
    );
    expect(textOf(screen.getByTestId("teaching-support"))).toMatch(
      /less help/i,
    );
    expect(textOf(screen.getByTestId("teaching-representation"))).toContain(
      "Worked step",
    );
  });

  describe("quiet waiting", () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });
    afterEach(() => {
      jest.useRealTimers();
    });

    it("a long idle period only quietly offers a hint: no posts, prompts or tutor text", async () => {
      const { requests, fetchImpl } = makeFakeApi();
      const screen = renderWorkspace(fetchImpl);
      await act(async () => {
        await jest.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByTestId("prompt-problem")).toBeTruthy();
      expect(screen.queryByTestId("quiet-hint")).toBeNull();
      const readsBefore = requests.length;

      await act(async () => {
        await jest.advanceTimersByTimeAsync(10 * 60 * 1000);
      });
      expect(screen.getByTestId("quiet-hint")).toBeTruthy();
      expect(mutatingRequests(requests)).toEqual([]);
      expect(requests.length).toBe(readsBefore);
      expect(screen.queryByTestId("prompt-tutor")).toBeNull();
      expect(screen.queryByTestId("prompt-status")).toBeNull();
      expect(screen.queryByTestId("teaching-context")).toBeNull();
      // The hint is optional: Help me stays an explicit action.
      expect(
        screen.getByTestId("help-me").props.accessibilityHint ?? "",
      ).toMatch(/ready|available/i);
    });

    it("lets the learner see and change the bounded waiting time", async () => {
      const { requests, fetchImpl } = makeFakeApi();
      const screen = renderWorkspace(fetchImpl);
      await act(async () => {
        await jest.advanceTimersByTimeAsync(0);
      });
      fireEvent.press(screen.getByTestId("wait-settings-toggle"));
      expect(textOf(screen.getByTestId("wait-value"))).toContain("45");

      fireEvent.press(screen.getByTestId("wait-increase"));
      await act(async () => {
        await jest.advanceTimersByTimeAsync(0);
      });
      const puts = requests.filter((request) => request.method === "PUT");
      expect(puts).toHaveLength(1);
      expect(puts[0].body).toEqual({
        schema_version: "wait-preference-request.v1",
        wait_seconds: 60,
      });
      expect(textOf(screen.getByTestId("wait-value"))).toContain("60");
    });
  });

  it("labels the tutor provider honestly, straight from the service", async () => {
    const { fetchImpl } = makeFakeApi();
    const screen = renderWorkspace(fetchImpl);
    await waitFor(() =>
      expect(
        screen.getByText(/Deterministic mock tutor \(not a language model\)/),
      ).toBeTruthy(),
    );
    const chip = screen.getByTestId("provider-label");
    expect(chip.props.accessibilityLabel).toMatch(/mock/i);
  });

  it("Finish for today really ends the session and hands back to the app", async () => {
    const { requests, fetchImpl } = makeFakeApi();
    const onSessionEnded = jest.fn();
    const screen = renderWorkspace(fetchImpl, onSessionEnded);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );

    fireEvent.press(screen.getByTestId("finish-session"));
    await waitFor(() => expect(onSessionEnded).toHaveBeenCalledTimes(1));
    const endCalls = requests.filter(
      (request) =>
        request.method === "POST" &&
        request.url.endsWith(`/sessions/${SESSION_ID}/end`),
    );
    expect(endCalls).toHaveLength(1);
  });

  it("explains loading and a recoverable load failure honestly", async () => {
    const { control, fetchImpl } = makeFakeApi();
    control.failState = true;
    const screen = renderWorkspace(fetchImpl);
    // The loading state is shown first.
    expect(screen.getByText(/Setting up your board/)).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByText(/board could not load/i)).toBeTruthy(),
    );
    expect(screen.getByText(/Database unavailable/)).toBeTruthy();

    control.failState = false;
    fireEvent.press(screen.getByTestId("workspace-retry"));
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );
    expect(textOf(screen.getByTestId("prompt-problem"))).toBe("2(x + 3) = 14");
  });

  it("warns that unsaved ink is memory-only when the network and device storage both fail", async () => {
    const { fetchImpl } = makeFakeApi();
    const offlineFetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ) => {
      if (String(input).endsWith("/scene/operations")) {
        throw new TypeError("Network request failed");
      }
      return fetchImpl(input, init);
    }) as typeof fetch;
    const screen = renderWorkspace(offlineFetch);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );

    // Device storage fails after the initial load.
    const setItem = AsyncStorage.setItem as unknown as jest.Mock;
    const originalSetItem = setItem.getMockImplementation() as (
      ...args: unknown[]
    ) => Promise<void>;
    setItem.mockImplementation(async (key: string, ...rest: unknown[]) => {
      if (key.startsWith("rubberducky.outbox.")) {
        throw new Error("storage unavailable");
      }
      return originalSetItem(key, ...rest);
    });
    try {
      fireEvent(screen.getByTestId("whiteboard"), "onLayout", {
        nativeEvent: { layout: { width: 800, height: 600 } },
      });
      const layer = screen.UNSAFE_getByType(BoardInputLayer).findByType(View);
      const point = { identifier: 1, locationX: 100, locationY: 100 };
      fireEvent(layer, "touchStart", {
        nativeEvent: { changedTouches: [point], touches: [point] },
      });
      fireEvent(layer, "touchEnd", {
        nativeEvent: { changedTouches: [point], touches: [] },
      });

      await waitFor(() =>
        expect(screen.getByTestId("save-notice")).toBeTruthy(),
      );
      expect(
        screen.getByText(/not saved and could not be kept on this device/i),
      ).toBeTruthy();
      expect(screen.queryByText(/It is kept on this device/)).toBeNull();
      expect(screen.getByText("Your dot (not saved yet)")).toBeTruthy();
    } finally {
      setItem.mockImplementation(originalSetItem);
    }
  });
});
