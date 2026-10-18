import { act, renderHook, waitFor } from "@testing-library/react-native";

import { ApiClient } from "../api/client";
import {
  ACCESSIBILITY_DEFAULTS,
  PERSONA_STATE_LOCKED,
  PERSONA_STATE_OPEN,
} from "../testing/agencyFixtures";

import { useLearnerSettings } from "./useLearnerSettings";

type Recorded = { method: string; url: string; body: unknown };

function makeBackend() {
  const backend = {
    persona: { ...PERSONA_STATE_LOCKED } as Record<string, unknown>,
    prefs: { ...ACCESSIBILITY_DEFAULTS } as Record<string, unknown>,
    requests: [] as Recorded[],
    failComfort: false,
    delayPatches: [] as (() => void)[],
    holdPatches: false,
  };
  const respond = (status: number, body: unknown) =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }) as Response;
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace("http://api", "");
    const method = init?.method ?? "GET";
    const body =
      init?.body === undefined
        ? undefined
        : (JSON.parse(String(init.body)) as Record<string, unknown>);
    backend.requests.push({ method, url, body });
    if (url === "/me/tutor-configuration" && method === "GET")
      return respond(200, backend.persona);
    if (url === "/me/tutor-configuration" && method === "PUT") {
      if (backend.persona.persona_locked) {
        const same =
          body?.appearance === backend.persona.appearance &&
          body?.personality === backend.persona.personality;
        if (!same) {
          return respond(409, {
            schema_version: "error.v1",
            error: {
              code: "persona_change_locked",
              message:
                "Appearance and personality can change again at 2026-10-17T12:30:00Z.",
            },
          });
        }
        return respond(200, { ...backend.persona, outcome: "no_change" });
      }
      backend.persona = {
        ...backend.persona,
        appearance: body?.appearance,
        personality: body?.personality,
        outcome: "changed",
      };
      return respond(200, backend.persona);
    }
    if (url === "/me/comfort-override" && method === "PUT") {
      if (backend.failComfort)
        return respond(500, {
          schema_version: "error.v1",
          error: { code: "boom", message: "down" },
        });
      backend.persona = {
        ...backend.persona,
        comfort_override: body?.comfort_override,
        comfort_changed: true,
        comfort_updated_at: "2026-10-12T09:05:00Z",
      };
      return respond(200, backend.persona);
    }
    if (url === "/me/accessibility-preferences" && method === "GET")
      return respond(200, backend.prefs);
    if (url === "/me/accessibility-preferences" && method === "PATCH") {
      const { schema_version: _ignored, ...patch } = body ?? {};
      backend.prefs = {
        ...backend.prefs,
        ...patch,
        updated_at: "2026-10-12T09:06:00Z",
      };
      if (backend.holdPatches) {
        const snapshot = backend.prefs;
        await new Promise<void>((resolve) =>
          backend.delayPatches.push(resolve),
        );
        return respond(200, snapshot);
      }
      return respond(200, backend.prefs);
    }
    return respond(404, {
      schema_version: "error.v1",
      error: { code: "not_found", message: url },
    });
  }) as typeof fetch;
  return { backend, client: new ApiClient("http://api", "tok", fetchImpl) };
}

async function setup() {
  const made = makeBackend();
  const hook = renderHook(() => useLearnerSettings(made.client));
  await waitFor(() => expect(hook.result.current.loaded).toBe(true));
  return { ...made, hook };
}

describe("useLearnerSettings", () => {
  it("loads the server lock state and effective accessibility preferences", async () => {
    const { hook } = await setup();
    expect(hook.result.current.persona?.persona_locked).toBe(true);
    expect(hook.result.current.persona?.next_change_available_at).toBe(
      "2026-10-17T12:30:00Z",
    );
    expect(hook.result.current.accessibility.animation).toBe("system");
  });

  it("keeps defaults, but says so, when preferences cannot load", async () => {
    const failing = new ApiClient("http://api", "tok", (async () => {
      throw new TypeError("Network request failed");
    }) as typeof fetch);
    const hook = renderHook(() => useLearnerSettings(failing));
    await waitFor(() => expect(hook.result.current.loadError).not.toBeNull());
    expect(hook.result.current.accessibility.sound_enabled).toBe(true);
    expect(hook.result.current.persona).toBeNull();
  });

  it("changes comfort immediately while locked, through its own route, leaving the durable pair untouched", async () => {
    const { hook, backend } = await setup();
    await act(async () => {
      await hook.result.current.setComfort("neutral_supportive");
    });
    expect(hook.result.current.persona?.comfort_override).toBe(
      "neutral_supportive",
    );
    expect(hook.result.current.persona?.persona_locked).toBe(true);
    expect(hook.result.current.persona?.last_changed_at).toBe(
      PERSONA_STATE_LOCKED.last_changed_at,
    );
    expect(
      backend.requests
        .filter((r) => r.method !== "GET")
        .map((r) => `${r.method} ${r.url}`),
    ).toEqual(["PUT /me/comfort-override"]);
  });

  it("shows a comfort choice at once and rolls it back with a message if the server refuses", async () => {
    const { hook, backend } = await setup();
    backend.failComfort = true;
    await act(async () => {
      await hook.result.current.setComfort("reduced_sass");
    });
    expect(hook.result.current.persona?.comfort_override).toBe("none");
    expect(hook.result.current.comfortError).toMatch(/could not/i);
  });

  it("patches accessibility without touching the persona routes", async () => {
    const { hook, backend } = await setup();
    await act(async () => {
      await hook.result.current.patchAccessibility({
        text_only: true,
        sound_enabled: false,
      });
    });
    expect(hook.result.current.accessibility.text_only).toBe(true);
    expect(hook.result.current.accessibility.sound_enabled).toBe(false);
    const writes = backend.requests.filter((r) => r.method !== "GET");
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({
      method: "PATCH",
      url: "/me/accessibility-preferences",
    });
    expect(hook.result.current.persona?.last_changed_at).toBe(
      PERSONA_STATE_LOCKED.last_changed_at,
    );
  });

  it("applies an accessibility choice immediately, before the server answers", async () => {
    const { hook, backend } = await setup();
    backend.holdPatches = true;
    let pending: Promise<void> | undefined;
    act(() => {
      pending = hook.result.current.patchAccessibility({
        animation: "reduced",
      });
    });
    expect(hook.result.current.accessibility.animation).toBe("reduced");
    await act(async () => {
      backend.delayPatches.forEach((release) => release());
      await pending;
    });
    expect(hook.result.current.accessibility.animation).toBe("reduced");
  });

  it("a stale slower response cannot overwrite a newer choice", async () => {
    const { hook, backend } = await setup();
    backend.holdPatches = true;
    let first: Promise<void> | undefined;
    let second: Promise<void> | undefined;
    act(() => {
      first = hook.result.current.patchAccessibility({ sound_enabled: false });
      second = hook.result.current.patchAccessibility({
        haptics_enabled: false,
      });
    });
    await act(async () => {
      // Release the newer request first, then the older, whose body predates the second edit.
      backend.delayPatches[1]();
      backend.delayPatches[0]();
      await Promise.all([first, second]);
    });
    expect(hook.result.current.accessibility.sound_enabled).toBe(false);
    expect(hook.result.current.accessibility.haptics_enabled).toBe(false);
  });

  it("reports a locked pair change with the server reason and keeps the stored pair", async () => {
    const { hook } = await setup();
    let outcome: string | undefined;
    await act(async () => {
      outcome = await hook.result.current.changePair("older_adult", "janelle");
    });
    expect(outcome).toBe("locked");
    expect(hook.result.current.pairError).toMatch(/can change again/i);
    expect(hook.result.current.persona?.appearance).toBe("animal");
  });

  it("saves a pair change once the server says it is available", async () => {
    const { hook, backend } = await setup();
    backend.persona = { ...PERSONA_STATE_OPEN };
    await act(async () => {
      await hook.result.current.refresh();
    });
    expect(hook.result.current.persona?.persona_locked).toBe(false);
    let outcome: string | undefined;
    await act(async () => {
      outcome = await hook.result.current.changePair("older_adult", "janelle");
    });
    expect(outcome).toBe("saved");
    expect(hook.result.current.persona?.appearance).toBe("older_adult");
  });
});
