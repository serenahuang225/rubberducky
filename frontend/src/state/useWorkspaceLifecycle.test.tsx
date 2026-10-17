/**
 * Lifecycle facts useWorkspace exposes for the avatar and the progressive drawing: the turn
 * generation, whether the tutor is unreachable, and whether the last command definitively failed.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { act, renderHook, waitFor } from "@testing-library/react-native";

import { ApiClient } from "../api/client";
import { METHOD_SLIP_TURN } from "../testing/teachingFixtures";

import { useWorkspace } from "./useWorkspace";

type Mode = "ok" | "drop" | "reject" | "hold";

function makeBackend() {
  const backend = {
    mode: "ok" as Mode,
    revision: 1,
    epoch: 0,
    pending: null as string | null,
    release: null as null | (() => void),
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
    if (url.endsWith("/state")) {
      if (backend.mode === "drop")
        throw new TypeError("Network request failed");
      return respond(200, {
        schema_version: "session-state.v1",
        session: {
          schema_version: "session.v1",
          id: "s1",
          learner_id: "l1",
          status: "active",
          goal: null,
          revision: backend.revision,
          cancellation_epoch: backend.epoch,
          started_at: "2026-10-17T00:00:00.000Z",
          ended_at: null,
        },
        current_problem: {
          problem_id: "p",
          attempt_id: "attempt-1",
          statement: "2(x + 3) = 14",
          kind: "practice",
          concept_id: "c",
          statement_object_id: null,
        },
        pace: "standard",
        pending_turn_id: backend.pending,
        session_context_recheck: false,
        persona: null,
      });
    }
    if (url.endsWith("/scene")) {
      if (backend.mode === "drop")
        throw new TypeError("Network request failed");
      return respond(200, {
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
      });
    }
    if (url.endsWith("/work") && method === "POST") {
      if (backend.mode === "drop")
        throw new TypeError("Network request failed");
      if (backend.mode === "reject") {
        return respond(422, {
          schema_version: "error.v1",
          error: {
            code: "invalid_request",
            message: "That step could not be read.",
          },
        });
      }
      if (backend.mode === "hold") {
        backend.pending = "turn-held";
        await new Promise<void>((resolve) => {
          backend.release = resolve;
        });
      }
      backend.pending = null;
      return respond(200, {
        ...METHOD_SLIP_TURN,
        drawings: [],
        cancellation_epoch: backend.epoch,
      });
    }
    if (url.endsWith("/interrupt") && method === "POST") {
      backend.epoch += 1;
      backend.pending = null;
      return respond(200, {
        schema_version: "interrupt-result.v1",
        session_id: "s1",
        cancellation_epoch: backend.epoch,
        session_revision: backend.revision,
        interrupted_turn_ids: ["turn-held"],
        replayed: false,
      });
    }
    return respond(404, {
      schema_version: "error.v1",
      error: { code: "not_found", message: url },
    });
  }) as typeof fetch;
  return { backend, fetchImpl };
}

beforeEach(async () => {
  await AsyncStorage.clear();
});

async function renderWorkspace(fetchImpl: typeof fetch) {
  const client = new ApiClient("http://tutor.test", "token", fetchImpl);
  const hook = renderHook(
    ({ id }: { id: string }) => useWorkspace(client, id),
    {
      initialProps: { id: "s1" },
    },
  );
  await waitFor(() => expect(hook.result.current.phase).toBe("ready"));
  return hook;
}

describe("useWorkspace lifecycle facts", () => {
  it("advances the turn generation when a reply is stopped and when the session changes", async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    const initial = hook.result.current.turnGeneration;
    backend.mode = "hold";
    let done: Promise<unknown> | undefined;
    await act(async () => {
      done = hook.result.current.submitWork("2x + 3 = 14");
      await Promise.resolve();
    });
    await waitFor(() => expect(hook.result.current.canInterrupt).toBe(true));
    expect(hook.result.current.turnGeneration).toBe(initial);
    await act(async () => {
      await hook.result.current.interrupt();
    });
    expect(hook.result.current.turnGeneration).toBeGreaterThan(initial);
    const afterStop = hook.result.current.turnGeneration;
    await act(async () => {
      backend.release?.();
      await done;
    });
    hook.rerender({ id: "s2" });
    expect(hook.result.current.turnGeneration).toBeGreaterThan(afterStop);
  });

  it("reports a lost connection only after a request fails to reach the tutor, and clears it on success", async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    expect(hook.result.current.connectionLost).toBe(false);
    backend.mode = "drop";
    await act(async () => {
      await hook.result.current.submitWork("2x + 3 = 14");
    });
    expect(hook.result.current.connectionLost).toBe(true);
    expect(hook.result.current.commandFailed).toBe(false);
    backend.mode = "ok";
    await act(async () => {
      await hook.result.current.submitWork("2x + 3 = 14");
    });
    expect(hook.result.current.connectionLost).toBe(false);
  });

  it("reports a definitive rejection as a failed command and clears it when the next command starts", async () => {
    const { backend, fetchImpl } = makeBackend();
    const hook = await renderWorkspace(fetchImpl);
    backend.mode = "reject";
    await act(async () => {
      await hook.result.current.submitWork("???");
    });
    expect(hook.result.current.commandFailed).toBe(true);
    expect(hook.result.current.connectionLost).toBe(false);
    backend.mode = "ok";
    await act(async () => {
      await hook.result.current.submitWork("2x + 3 = 14");
    });
    expect(hook.result.current.commandFailed).toBe(false);
  });
});
