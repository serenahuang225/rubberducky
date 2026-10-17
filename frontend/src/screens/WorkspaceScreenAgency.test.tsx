/**
 * Workspace integration of the learner-agency features through the REAL ApiClient: the tiny
 * avatar's truthful status, brief progressive tutor drawings that follow reduced-motion and
 * cancel when the board is covered, haptics only when allowed, and the settings/memory entry
 * points. Reveal timing uses the real scheduled callbacks under jest's fake timers.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import React from "react";

import { ApiClient } from "../api/client";
import {
  accessibilityPreferencesSchema,
  type TutorConfiguration,
} from "../api/contracts";
import { REVEAL_MAX_TOTAL_MS } from "../board/progressiveReveal";
import * as haptics from "../feedback/haptics";
import { ACCESSIBILITY_DEFAULTS } from "../testing/agencyFixtures";
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
const SESSION = {
  schema_version: "session.v1",
  id: SESSION_ID,
  learner_id: "learner-1",
  status: "active",
  goal: null,
  revision: 1,
  cancellation_epoch: 0,
  started_at: "2026-10-17T00:00:00.000Z",
  ended_at: null,
};
const STATE = {
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

function tutorObject(id: string) {
  return {
    schema_version: "scene-object.v1",
    id,
    learner_id: "learner-1",
    session_id: SESSION_ID,
    author_role: "tutor",
    semantic_role: "problem_statement",
    kind: "text",
    payload: { text: "mark", x: 80, y: 120, color_role: "tutor" },
    teaching_step_id: null,
    created_at: "2026-10-17T00:00:00.000Z",
    deleted_at: null,
  };
}

function makeApi() {
  const control = {
    marksCommitted: false,
    helpGate: null as null | Promise<void>,
    helpFails: false,
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
    if (url.endsWith(`/sessions/${SESSION_ID}/state`))
      return respond(200, STATE);
    if (url.endsWith(`/sessions/${SESSION_ID}/scene`)) {
      return respond(200, {
        schema_version: "scene-snapshot.v1",
        session_id: SESSION_ID,
        scene_revision: control.marksCommitted ? 2 : 1,
        board_width: 1600,
        board_height: 1200,
        pen_width: 3,
        objects: control.marksCommitted
          ? [tutorObject("obj-statement"), tutorObject("obj-1")]
          : [tutorObject("obj-statement")],
        student_undo_available: false,
        student_redo_available: false,
        tutor_move_undo_available: false,
      });
    }
    if (url.endsWith("/health/model")) {
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
    }
    if (url.endsWith("/me/wait-preference"))
      return respond(200, WAIT_PREFERENCE);
    if (url.endsWith(`/sessions/${SESSION_ID}/wait`))
      return respond(200, WAIT_STATE);
    if (url.endsWith(`/sessions/${SESSION_ID}/help`) && method === "POST") {
      if (control.helpGate !== null) await control.helpGate;
      if (control.helpFails)
        return respond(500, {
          schema_version: "error.v1",
          error: { code: "boom", message: "tutor failed" },
        });
      control.marksCommitted = true;
      return respond(200, METHOD_SLIP_TURN);
    }
    return respond(404, {
      schema_version: "error.v1",
      error: { code: "not_found", message: url },
    });
  }) as typeof fetch;
  return { control, fetchImpl };
}

const prefs = (patch: Record<string, unknown> = {}) =>
  accessibilityPreferencesSchema.parse({ ...ACCESSIBILITY_DEFAULTS, ...patch });

function renderWorkspace(
  fetchImpl: typeof fetch,
  extra: Partial<React.ComponentProps<typeof WorkspaceScreen>> = {},
) {
  const client = new ApiClient("http://tutor.test", "token", fetchImpl);
  const props = {
    client,
    sessionId: SESSION_ID,
    persona: PERSONA,
    displayName: "Riley",
    onSessionEnded: jest.fn(),
    ...extra,
  };
  const view = render(<WorkspaceScreen {...props} />);
  return {
    ...view,
    props,
    rerenderWith: (
      patch: Partial<React.ComponentProps<typeof WorkspaceScreen>>,
    ) => view.rerender(<WorkspaceScreen {...props} {...patch} />),
  };
}

const boardLabel = (view: ReturnType<typeof render>) =>
  view.getByTestId("whiteboard").props.accessibilityLabel as string;

async function ready(view: ReturnType<typeof render>) {
  await waitFor(() => expect(view.getByTestId("prompt-problem")).toBeTruthy());
}

describe("WorkspaceScreen learner-agency integration", () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
    jest.useFakeTimers({ doNotFake: ["nextTick", "queueMicrotask"] });
  });
  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it("shows a real idle avatar state, then thinking only while a command runs", async () => {
    const { control, fetchImpl } = makeApi();
    let release: () => void = () => undefined;
    control.helpGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const view = renderWorkspace(fetchImpl);
    await ready(view);
    expect(view.getByTestId("avatar-status")).toHaveTextContent("Ready");

    fireEvent.press(view.getByTestId("help-me"));
    await waitFor(() =>
      expect(view.getByTestId("avatar-status")).toHaveTextContent("Thinking"),
    );
    release();
    await waitFor(() =>
      expect(view.getByTestId("avatar-status")).toHaveTextContent("Ready"),
    );
  });

  it("shows the error state when the tutor reply fails, never an invented one", async () => {
    const { control, fetchImpl } = makeApi();
    control.helpFails = true;
    const view = renderWorkspace(fetchImpl);
    await ready(view);
    fireEvent.press(view.getByTestId("help-me"));
    await waitFor(() =>
      expect(view.getByTestId("avatar-status")).toHaveTextContent(
        "Something went wrong",
      ),
    );
  });

  it("reveals a new tutor mark briefly on a schedule and ends on the full board", async () => {
    const { fetchImpl } = makeApi();
    const view = renderWorkspace(fetchImpl, {
      accessibility: prefs({ animation: "full" }),
    });
    await ready(view);
    expect(boardLabel(view)).toBe("Whiteboard: 0 of your marks, 1 tutor marks");

    fireEvent.press(view.getByTestId("help-me"));
    await waitFor(() => expect(view.getByTestId("prompt-tutor")).toBeTruthy());
    // The mark is committed, but is withheld until its scheduled reveal.
    expect(boardLabel(view)).toBe("Whiteboard: 0 of your marks, 1 tutor marks");
    act(() => {
      jest.advanceTimersByTime(REVEAL_MAX_TOTAL_MS);
    });
    expect(boardLabel(view)).toBe("Whiteboard: 0 of your marks, 2 tutor marks");
  });

  it("shows the mark at once with reduced motion", async () => {
    const { fetchImpl } = makeApi();
    const view = renderWorkspace(fetchImpl, {
      accessibility: prefs({ animation: "reduced" }),
    });
    await ready(view);
    fireEvent.press(view.getByTestId("help-me"));
    await waitFor(() => expect(view.getByTestId("prompt-tutor")).toBeTruthy());
    await waitFor(() =>
      expect(boardLabel(view)).toBe(
        "Whiteboard: 0 of your marks, 2 tutor marks",
      ),
    );
  });

  it("cancels a running reveal when the board is covered, and a late timer cannot change it", async () => {
    const { fetchImpl } = makeApi();
    const view = renderWorkspace(fetchImpl, {
      accessibility: prefs({ animation: "full" }),
    });
    await ready(view);
    fireEvent.press(view.getByTestId("help-me"));
    await waitFor(() => expect(view.getByTestId("prompt-tutor")).toBeTruthy());
    expect(boardLabel(view)).toBe("Whiteboard: 0 of your marks, 1 tutor marks");

    view.rerenderWith({ boardHidden: true });
    expect(boardLabel(view)).toBe("Whiteboard: 0 of your marks, 2 tutor marks");
    act(() => {
      jest.advanceTimersByTime(REVEAL_MAX_TOTAL_MS * 2);
    });
    expect(boardLabel(view)).toBe("Whiteboard: 0 of your marks, 2 tutor marks");
  });

  it("plays one haptic pulse per reply only when haptics are on", async () => {
    const pulse = jest
      .spyOn(haptics, "pulseHaptic")
      .mockResolvedValue("played");
    const on = makeApi();
    const first = renderWorkspace(on.fetchImpl, {
      accessibility: prefs({ haptics_enabled: true }),
    });
    await ready(first);
    fireEvent.press(first.getByTestId("help-me"));
    await waitFor(() => expect(pulse).toHaveBeenCalledTimes(1));
    expect(pulse.mock.calls[0][0]).toEqual({ haptics_enabled: true });
    first.unmount();

    pulse.mockClear();
    const off = makeApi();
    const second = renderWorkspace(off.fetchImpl, {
      accessibility: prefs({ haptics_enabled: false }),
    });
    await ready(second);
    fireEvent.press(second.getByTestId("help-me"));
    await waitFor(() =>
      expect(second.getByTestId("prompt-tutor")).toBeTruthy(),
    );
    expect(
      pulse.mock.calls.every(([choice]) => choice.haptics_enabled === false),
    ).toBe(true);
  });

  it("opens settings and memory from named buttons, and omits them when not wired", async () => {
    const { fetchImpl } = makeApi();
    const onOpenSettings = jest.fn();
    const onOpenMemory = jest.fn();
    const view = renderWorkspace(fetchImpl, { onOpenSettings, onOpenMemory });
    await ready(view);
    fireEvent.press(view.getByRole("button", { name: "Open settings" }));
    fireEvent.press(view.getByRole("button", { name: "Open private memory" }));
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
    expect(onOpenMemory).toHaveBeenCalledTimes(1);
    view.unmount();

    const bare = renderWorkspace(fetchImpl);
    await ready(bare);
    expect(bare.queryByTestId("open-settings")).toBeNull();
  });

  it("has no pressure or engagement-bait surfaces on the root board", async () => {
    const { fetchImpl } = makeApi();
    const view = renderWorkspace(fetchImpl, {
      onOpenSettings: jest.fn(),
      onOpenMemory: jest.fn(),
    });
    await ready(view);
    const everything = JSON.stringify(view.toJSON());
    expect(everything).not.toMatch(
      /confetti|streak|leaderboard|loot|badge|reward|advert|sponsor|feed\b|points|xp\b|rank/i,
    );
  });
});
