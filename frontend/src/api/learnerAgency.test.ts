import {
  ACCESSIBILITY_DEFAULTS,
  EVIDENCE_CORRECTION_RECEIPT,
  INSPECTION,
  NOTE_DELETION_RECEIPT,
  PERSONA_STATE_LOCKED,
  PROFILE_REMOVAL_RECEIPT,
  SESSION_REMOVAL_RECEIPT,
} from "../testing/agencyFixtures";

import { ApiClient, ApiClientError } from "./client";

type Recorded = { method: string; url: string; body: unknown };

function makeClient(
  responder: (req: Recorded) => { status: number; body: unknown },
) {
  const requests: Recorded[] = [];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const request: Recorded = {
      method: init?.method ?? "GET",
      url: String(input),
      body:
        init?.body === undefined ? undefined : JSON.parse(String(init.body)),
    };
    requests.push(request);
    const { status, body } = responder(request);
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as Response;
  }) as typeof fetch;
  return { client: new ApiClient("http://api", "tok", fetchImpl), requests };
}

describe("persona routes", () => {
  it("reads the server lock state with UTC instants", async () => {
    const { client, requests } = makeClient(() => ({
      status: 200,
      body: PERSONA_STATE_LOCKED,
    }));
    const state = await client.getTutorConfiguration();
    expect(requests[0]).toMatchObject({
      method: "GET",
      url: "http://api/me/tutor-configuration",
    });
    expect(state.persona_locked).toBe(true);
    expect(state.next_change_available_at).toBe("2026-10-17T12:30:00Z");
    expect(state.server_now).toBe("2026-10-12T09:00:00Z");
    expect(state.comfort_updated_at).toBeNull();
  });

  it("sends a pair change without a comfort override so it cannot reset one", async () => {
    const { client, requests } = makeClient(() => ({
      status: 200,
      body: { ...PERSONA_STATE_LOCKED, outcome: "initial_selection" },
    }));
    const state = await client.putTutorConfiguration("animal", "janelle");
    expect(requests[0].method).toBe("PUT");
    expect(requests[0].url).toBe("http://api/me/tutor-configuration");
    expect(requests[0].body).toEqual({
      schema_version: "tutor-configuration-request.v1",
      appearance: "animal",
      personality: "janelle",
    });
    expect(state.outcome).toBe("initial_selection");
  });

  it("surfaces a locked pair change as a typed 409 error carrying the server code", async () => {
    const { client } = makeClient(() => ({
      status: 409,
      body: {
        schema_version: "error.v1",
        error: {
          code: "persona_change_locked",
          message:
            "Your rubber duck can change again at 2026-10-17T12:30:00Z.",
        },
      },
    }));
    const failure = await client
      .putTutorConfiguration("older_adult", "janelle")
      .catch((e) => e);
    expect(failure).toBeInstanceOf(ApiClientError);
    expect(failure.status).toBe(409);
    expect(failure.code).toBe("persona_change_locked");
  });

  it("changes comfort through its own route, never the durable pair route", async () => {
    const { client, requests } = makeClient(() => ({
      status: 200,
      body: {
        ...PERSONA_STATE_LOCKED,
        comfort_override: "neutral_supportive",
        comfort_changed: true,
        comfort_updated_at: "2026-10-12T09:01:00Z",
      },
    }));
    const state = await client.putComfortOverride("neutral_supportive");
    expect(requests).toHaveLength(1);
    expect(requests[0].method).toBe("PUT");
    expect(requests[0].url).toBe("http://api/me/comfort-override");
    expect(requests[0].body).toEqual({
      schema_version: "comfort-override-request.v1",
      comfort_override: "neutral_supportive",
    });
    expect(state.comfort_override).toBe("neutral_supportive");
    expect(state.last_changed_at).toBe(PERSONA_STATE_LOCKED.last_changed_at);
    expect(state.comfort_updated_at).toBe("2026-10-12T09:01:00Z");
  });
});

describe("accessibility routes", () => {
  it("reads the effective preferences", async () => {
    const { client, requests } = makeClient(() => ({
      status: 200,
      body: ACCESSIBILITY_DEFAULTS,
    }));
    const prefs = await client.getAccessibilityPreferences();
    expect(requests[0]).toMatchObject({
      method: "GET",
      url: "http://api/me/accessibility-preferences",
    });
    expect(prefs.animation).toBe("system");
    expect(prefs.captions_enabled).toBe(true);
  });

  it("patches only the supplied fields", async () => {
    const { client, requests } = makeClient(() => ({
      status: 200,
      body: { ...ACCESSIBILITY_DEFAULTS, sound_enabled: false },
    }));
    const prefs = await client.patchAccessibilityPreferences({
      sound_enabled: false,
    });
    expect(requests[0].method).toBe("PATCH");
    expect(requests[0].url).toBe("http://api/me/accessibility-preferences");
    expect(requests[0].body).toEqual({
      schema_version: "accessibility-preferences-request.v1",
      sound_enabled: false,
    });
    expect(prefs.sound_enabled).toBe(false);
  });
});

describe("memory routes", () => {
  it("inspects with an explicit per-bucket limit and optional session", async () => {
    const { client, requests } = makeClient(() => ({
      status: 200,
      body: INSPECTION,
    }));
    const inspection = await client.inspectMemory({
      limit: 35,
      sessionId: "s1",
    });
    expect(requests[0].url).toBe(
      "http://api/memory/inspect?limit=35&session_id=s1",
    );
    expect(inspection.items).toHaveLength(3);
    expect(inspection.items[0].sources[0].excerpt).toBe("2x + 3 = 14");
    expect(inspection.limit).toBe(20);
  });

  it("corrects evidence and notes through their correction routes", async () => {
    const { client, requests } = makeClient((req) =>
      req.url.includes("/evidence/")
        ? { status: 200, body: EVIDENCE_CORRECTION_RECEIPT }
        : {
            status: 200,
            body: {
              schema_version: "memory-correction.v1",
              kind: "note",
              record_id: "mem-1",
              changed: true,
              replacement_id: "mem-2",
              original: "old",
              current: "new",
              effects: EVIDENCE_CORRECTION_RECEIPT.effects,
            },
          },
    );
    const evidence = await client.correctEvidence("obs-1", true);
    expect(requests[0]).toMatchObject({
      method: "POST",
      url: "http://api/memory/evidence/obs-1/correction",
      body: { correct: true },
    });
    expect(evidence.effects.mastery_estimates[0].p_known).toBeCloseTo(0.67);
    const note = await client.correctNote("mem-1", "I meant something else");
    expect(requests[1]).toMatchObject({
      method: "POST",
      url: "http://api/memory/notes/mem-1/correction",
      body: { content: "I meant something else" },
    });
    expect(note.replacement_id).toBe("mem-2");
  });

  it("deletes a note, evidence and a hypothesis with DELETE", async () => {
    const { client, requests } = makeClient(() => ({
      status: 200,
      body: NOTE_DELETION_RECEIPT,
    }));
    await client.deleteNote("mem-1");
    await client.deleteEvidence("obs-1");
    await client.deleteHypothesis("hyp-1");
    expect(requests.map((r) => `${r.method} ${r.url}`)).toEqual([
      "DELETE http://api/memory/notes/mem-1",
      "DELETE http://api/memory/evidence/obs-1",
      "DELETE http://api/memory/hypotheses/hyp-1",
    ]);
  });

  it("removes a session and the whole profile with the explicit confirmation", async () => {
    const { client, requests } = makeClient((req) => ({
      status: 200,
      body: req.url.endsWith("/me?confirm=delete-my-profile")
        ? PROFILE_REMOVAL_RECEIPT
        : SESSION_REMOVAL_RECEIPT,
    }));
    const session = await client.deleteSession("s1");
    expect(requests[0]).toMatchObject({
      method: "DELETE",
      url: "http://api/sessions/s1",
    });
    expect(session.scope).toBe("session");
    const profile = await client.deleteProfile();
    expect(requests[1]).toMatchObject({
      method: "DELETE",
      url: "http://api/me?confirm=delete-my-profile",
    });
    expect(profile.credentials_revoked).toBe(1);
  });

  it("url-encodes record ids", async () => {
    const { client, requests } = makeClient(() => ({
      status: 200,
      body: NOTE_DELETION_RECEIPT,
    }));
    await client.deleteNote("a/b c");
    expect(requests[0].url).toBe("http://api/memory/notes/a%2Fb%20c");
  });
});
