/**
 * Typed-step draft handling on the real WorkspaceScreen and ApiClient. The learner's text is
 * only removed from the box once the server gave an authoritative outcome for exactly that
 * text; a failed or uncertain send keeps it, and a newer edit is never overwritten.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import React from "react";

import { ApiClient } from "../api/client";
import type { TutorConfiguration } from "../api/contracts";
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

type Call = { key: string; body: Record<string, unknown> };

function makeApi() {
  const api = {
    revision: 1,
    epoch: 0,
    pending: null as string | null,
    calls: [] as Call[],
    mode: null as null | "drop_before" | "invalid" | "hold",
    held: null as null | (() => void),
    stored: new Map<string, unknown>(),
  };
  const respond = (status: number, body: unknown) =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }) as Response;
  const error = (status: number, code: string, message = code) =>
    respond(status, { schema_version: "error.v1", error: { code, message } });
  const turn = (status: "committed" | "superseded", index: number) => ({
    ...METHOD_SLIP_TURN,
    turn_id: `turn-${index}`,
    status,
    base_revision: index,
    session_revision: index + 1,
    cancellation_epoch: api.epoch,
    rejections:
      status === "superseded"
        ? [{ code: "interrupted", message: "stopped" }]
        : [],
    drawings: [],
  });

  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.endsWith(`/sessions/${SESSION_ID}/state`)) {
      return respond(200, {
        schema_version: "session-state.v1",
        session: {
          schema_version: "session.v1",
          id: SESSION_ID,
          learner_id: "learner-1",
          status: "active",
          goal: "solve_equations_with_parentheses",
          revision: api.revision,
          cancellation_epoch: api.epoch,
          started_at: "2026-10-17T00:00:00.000Z",
          ended_at: null,
        },
        current_problem: {
          problem_id: "problem.distribute",
          attempt_id: "attempt-1",
          statement: "2(x + 3) = 14",
          kind: "practice",
          concept_id: "concept.distribution",
          statement_object_id: null,
        },
        pace: "standard",
        pending_turn_id: api.pending,
        session_context_recheck: false,
        persona: PERSONA,
      });
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/scene`)) {
      return respond(200, {
        schema_version: "scene-snapshot.v1",
        session_id: SESSION_ID,
        scene_revision: 1,
        board_width: 1600,
        board_height: 1200,
        pen_width: 3,
        objects: [],
        student_undo_available: false,
        student_redo_available: false,
        tutor_move_undo_available: false,
      });
    }
    if (url.endsWith("/me/wait-preference"))
      return respond(200, WAIT_PREFERENCE);
    if (url.endsWith(`/sessions/${SESSION_ID}/wait`))
      return respond(200, WAIT_STATE);
    if (
      url.endsWith(`/sessions/${SESSION_ID}/interrupt`) &&
      method === "POST"
    ) {
      const stopped = api.pending === null ? [] : [api.pending];
      api.pending = null;
      api.epoch += 1;
      return respond(200, {
        schema_version: "interrupt-result.v1",
        session_id: SESSION_ID,
        cancellation_epoch: api.epoch,
        session_revision: api.revision,
        interrupted_turn_ids: stopped,
        replayed: false,
      });
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/work`) && method === "POST") {
      const headers = init?.headers as Record<string, string>;
      const key = headers["Idempotency-Key"];
      api.calls.push({
        key,
        body: JSON.parse(String(init?.body)) as Record<string, unknown>,
      });
      const mode = api.mode;
      api.mode = null;
      if (mode === "drop_before") throw new TypeError("Network request failed");
      const known = api.stored.get(key);
      if (known !== undefined)
        return respond(200, { ...(known as object), replayed: true });
      if (mode === "invalid")
        return error(422, "validation_error", "That step could not be read.");
      const index = api.revision;
      api.revision += 1;
      api.pending = `turn-${index}`;
      if (mode === "hold") {
        await new Promise<void>((resolve) => {
          api.held = resolve;
        });
        const late = api.pending === null ? "superseded" : "committed";
        api.pending = null;
        return respond(200, turn(late, index));
      }
      api.pending = null;
      const result = turn("committed", index);
      api.stored.set(key, result);
      return respond(200, result);
    }
    if (url.endsWith("/health/model")) return error(404, "not_found");
    return error(404, "not_found", url);
  }) as typeof fetch;
  return { api, fetchImpl };
}

function renderScreen(fetchImpl: typeof fetch) {
  const client = new ApiClient("http://tutor.test", "token", fetchImpl);
  return render(
    <WorkspaceScreen
      client={client}
      sessionId={SESSION_ID}
      persona={PERSONA}
      displayName="Riley"
      onSessionEnded={jest.fn()}
    />,
  );
}

const flush = () =>
  act(async () => {
    await Promise.resolve();
  });

beforeEach(async () => {
  await AsyncStorage.clear();
});

describe("WorkspaceScreen typed step draft", () => {
  it("clears the box only after the server answered for that text", async () => {
    const { api, fetchImpl } = makeApi();
    const screen = renderScreen(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );

    fireEvent.changeText(screen.getByTestId("typed-step-input"), "2x + 6 = 14");
    fireEvent.press(screen.getByTestId("submit-step"));
    // While the request is out the learner's text is not thrown away.
    expect(screen.getByTestId("typed-step-input").props.value).toBe(
      "2x + 6 = 14",
    );

    await waitFor(() =>
      expect(screen.getByTestId("teaching-context")).toBeTruthy(),
    );
    expect(screen.getByTestId("typed-step-input").props.value).toBe("");
    expect(api.calls).toHaveLength(1);
  });

  it("keeps the typed text after a transport failure and retries it with the same key and body", async () => {
    const { api, fetchImpl } = makeApi();
    const screen = renderScreen(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );
    api.mode = "drop_before";

    fireEvent.changeText(screen.getByTestId("typed-step-input"), "2x + 6 = 14");
    fireEvent.press(screen.getByTestId("submit-step"));
    await waitFor(() =>
      expect(screen.getByTestId("workspace-error")).toBeTruthy(),
    );
    expect(screen.getByTestId("typed-step-input").props.value).toBe(
      "2x + 6 = 14",
    );
    expect(screen.queryByTestId("teaching-context")).toBeNull();

    fireEvent.press(screen.getByTestId("submit-step"));
    await waitFor(() =>
      expect(screen.getByTestId("teaching-context")).toBeTruthy(),
    );
    expect(api.calls).toHaveLength(2);
    expect(api.calls[1]).toEqual(api.calls[0]);
    expect(screen.getByTestId("typed-step-input").props.value).toBe("");
    expect(screen.queryByTestId("workspace-error")).toBeNull();
  });

  it("keeps the text when the server refuses the request outright", async () => {
    const { api, fetchImpl } = makeApi();
    const screen = renderScreen(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );
    api.mode = "invalid";

    fireEvent.changeText(screen.getByTestId("typed-step-input"), "???");
    fireEvent.press(screen.getByTestId("submit-step"));
    await waitFor(() =>
      expect(screen.getByTestId("workspace-error")).toBeTruthy(),
    );
    expect(screen.getByTestId("typed-step-input").props.value).toBe("???");
  });

  it("Stop settles the submitted draft at once, without waiting for the withdrawn reply", async () => {
    const { api, fetchImpl } = makeApi();
    const screen = renderScreen(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );

    api.mode = "hold";
    fireEvent.changeText(screen.getByTestId("typed-step-input"), "2x + 6 = 14");
    fireEvent.press(screen.getByTestId("submit-step"));
    await waitFor(() => expect(screen.getByTestId("stop-reply")).toBeTruthy());
    expect(screen.getByTestId("typed-step-input").props.value).toBe(
      "2x + 6 = 14",
    );

    await act(async () => {
      fireEvent.press(screen.getByTestId("stop-reply"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("typed-step-input").props.value).toBe(""),
    );

    // The late provider reply of the stopped turn paints nothing.
    await act(async () => {
      api.held?.();
    });
    await flush();
    expect(screen.queryByTestId("teaching-context")).toBeNull();
    expect(screen.queryByTestId("prompt-tutor")).toBeNull();
  });

  it("never clears a newer edit when the answer for the earlier text arrives", async () => {
    const { api, fetchImpl } = makeApi();
    const screen = renderScreen(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("prompt-problem")).toBeTruthy(),
    );

    api.mode = "hold";
    fireEvent.changeText(screen.getByTestId("typed-step-input"), "2x + 6 = 14");
    fireEvent.press(screen.getByTestId("submit-step"));
    await waitFor(() => expect(api.held).not.toBeNull());
    // The box is locked while sending in this UI, so deliver the newer edit through the
    // input's own handler, as a buffered native keystroke would.
    await act(async () => {
      screen
        .getByTestId("typed-step-input")
        .props.onChangeText("x = 4 and then check");
    });
    await act(async () => {
      api.held?.();
    });
    await waitFor(() =>
      expect(screen.getByTestId("teaching-context")).toBeTruthy(),
    );
    expect(screen.getByTestId("typed-step-input").props.value).toBe(
      "x = 4 and then check",
    );
  });
});
