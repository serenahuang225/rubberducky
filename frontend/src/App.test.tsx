/**
 * App-level navigation: opening settings and memory must not remount the workspace (a remount
 * would discard the typed draft and any running command), must keep one client identity for
 * unchanged credentials, and deleting the profile must clear the sign-in and say what happened.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import React from "react";

import App from "../App";
import {
  ACCESSIBILITY_DEFAULTS,
  INSPECTION,
  PERSONA_STATE_LOCKED,
  PROFILE_REMOVAL_RECEIPT,
} from "./testing/agencyFixtures";
import { WAIT_PREFERENCE, WAIT_STATE } from "./testing/teachingFixtures";

const LEARNER = {
  schema_version: "learner.v1",
  id: "learner-1",
  display_name: "Riley",
  is_fictional: true,
};
const SESSION = {
  schema_version: "session.v1",
  id: "s1",
  learner_id: "learner-1",
  status: "active",
  goal: null,
  revision: 1,
  cancellation_epoch: 0,
  started_at: "2026-10-12T08:00:00Z",
  ended_at: null,
};
const STATE = {
  schema_version: "session-state.v1",
  session: SESSION,
  current_problem: {
    problem_id: "p",
    attempt_id: "a1",
    statement: "2(x + 3) = 14",
    kind: "practice",
    concept_id: "c",
    statement_object_id: "o1",
  },
  pace: "standard",
  pending_turn_id: null,
  session_context_recheck: false,
  persona: PERSONA_STATE_LOCKED,
};
const SCENE = {
  schema_version: "scene-snapshot.v1",
  session_id: "s1",
  scene_revision: 1,
  board_width: 1600,
  board_height: 1200,
  pen_width: 3,
  objects: [],
  student_undo_available: false,
  student_redo_available: false,
  tutor_move_undo_available: false,
};

const calls: { method: string; url: string; auth: string | null }[] = [];

function fakeFetch(): typeof fetch {
  const respond = (status: number, body: unknown) =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }) as Response;
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace(/^https?:\/\/[^/]+/, "");
    const method = init?.method ?? "GET";
    const headers = (init?.headers ?? {}) as Record<string, string>;
    calls.push({ method, url, auth: headers.Authorization ?? null });
    if (url === "/me" && method === "GET") {
      return respond(200, {
        schema_version: "me.v1",
        learner: LEARNER,
        tutor_configuration: PERSONA_STATE_LOCKED,
        notice: "",
      });
    }
    if (url === "/sessions" && method === "GET") return respond(200, [SESSION]);
    if (url === "/sessions/s1/state") return respond(200, STATE);
    if (url === "/sessions/s1/scene") return respond(200, SCENE);
    if (url === "/sessions/s1/wait") return respond(200, WAIT_STATE);
    if (url === "/health/model")
      return respond(200, {
        schema_version: "model-readiness.v1",
        provider: "mock",
        state: "ready",
        ready: true,
        is_mock: true,
        label: "mock",
        model_id: null,
        model_revision: null,
        detail: "",
      });
    if (url === "/me/wait-preference") return respond(200, WAIT_PREFERENCE);
    if (url === "/me/tutor-configuration")
      return respond(200, PERSONA_STATE_LOCKED);
    if (url === "/me/accessibility-preferences")
      return respond(200, ACCESSIBILITY_DEFAULTS);
    if (url.startsWith("/memory/inspect")) return respond(200, INSPECTION);
    if (method === "DELETE" && url === "/me?confirm=delete-my-profile")
      return respond(200, PROFILE_REMOVAL_RECEIPT);
    return respond(404, {
      schema_version: "error.v1",
      error: { code: "not_found", message: url },
    });
  }) as typeof fetch;
}

async function openWorkspace() {
  await AsyncStorage.setItem(
    "rubberducky.credentials.v1",
    JSON.stringify({
      accessToken: "tok-1",
      learnerId: "learner-1",
      displayName: "Riley",
    }),
  );
  render(<App />);
  await waitFor(() =>
    expect(screen.getByTestId("chat-input")).toBeTruthy(),
  );
}

describe("App navigation", () => {
  const realFetch = globalThis.fetch;
  beforeEach(async () => {
    calls.length = 0;
    await AsyncStorage.clear();
    globalThis.fetch = jest.fn(fakeFetch()) as unknown as typeof fetch;
  });
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it("keeps the workspace mounted, with its draft and requests, while settings and memory are open", async () => {
    await openWorkspace();
    fireEvent.changeText(screen.getByTestId("chat-input"), "2x + 6 = 14");
    const stateReads = () =>
      calls.filter((c) => c.url === "/sessions/s1/state").length;
    const before = stateReads();

    fireEvent.press(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() =>
      expect(screen.getByTestId("settings-screen")).toBeTruthy(),
    );
    // The covered workspace is out of the tab order and accessibility tree.
    expect(screen.queryByTestId("chat-input")).toBeNull();
    fireEvent.press(
      screen.getByRole("button", { name: "Open private memory" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("memory-screen")).toBeTruthy(),
    );
    fireEvent.press(screen.getByRole("button", { name: "Back to board" }));
    await waitFor(() =>
      expect(screen.getByTestId("settings-screen")).toBeTruthy(),
    );
    fireEvent.press(screen.getByRole("button", { name: "Back to board" }));

    await waitFor(() =>
      expect(screen.getByTestId("chat-input")).toBeTruthy(),
    );
    expect(screen.getByTestId("chat-input").props.value).toBe(
      "2x + 6 = 14",
    );
    expect(stateReads()).toBe(before);
    expect(
      calls.filter((c) => c.url === "/me" && c.method === "GET"),
    ).toHaveLength(1);
    expect(
      calls.every((c) => c.auth === null || c.auth === "Bearer tok-1"),
    ).toBe(true);
  });

  it("deletes the profile, clears the sign-in and shows what was removed", async () => {
    await openWorkspace();
    fireEvent.press(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() =>
      expect(screen.getByTestId("settings-screen")).toBeTruthy(),
    );
    fireEvent.press(
      screen.getByRole("button", { name: "Open private memory" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("memory-items")).toBeTruthy(),
    );
    fireEvent.press(screen.getByRole("button", { name: "Delete my profile" }));
    await act(async () => {
      fireEvent.press(
        screen.getByRole("button", { name: "Yes, delete my profile" }),
      );
    });
    await waitFor(() =>
      expect(screen.getByTestId("removal-notice")).toBeTruthy(),
    );
    expect(screen.getByTestId("removal-notice")).toHaveTextContent(
      /Profile removed/,
    );
    expect(screen.getByTestId("removal-notice")).toHaveTextContent(
      /not secure disk, backup or vendor erasure/i,
    );
    expect(await AsyncStorage.getItem("rubberducky.credentials.v1")).toBeNull();
    expect(screen.queryByTestId("chat-input")).toBeNull();
  });
});
