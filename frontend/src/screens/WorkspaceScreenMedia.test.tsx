/**
 * Workspace integration of optional media through the REAL ApiClient: explicit capture only,
 * visible indicators with Stop, denial/absence that leave typed work usable, bounded
 * uncertain media events, provisional/final transcripts, captions, mute/text-only suppression
 * and the avatar status the media facts produce. Drivers and voice events are deterministic
 * fakes, so nothing here is evidence of live transcription, recognition or acoustic barge-in.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import React from "react";

import { ApiClient } from "../api/client";
import {
  accessibilityPreferencesSchema,
  type TutorConfiguration,
} from "../api/contracts";
import { ACCESSIBILITY_DEFAULTS } from "../testing/agencyFixtures";
import { fakeMedia, type FakeMedia } from "../testing/fakeMedia";
import {
  METHOD_SLIP_TURN,
  WAIT_PREFERENCE,
  WAIT_STATE,
} from "../testing/teachingFixtures";

import { WorkspaceScreen } from "./WorkspaceScreen";

const SESSION_ID = "s1";

function typedStepInput(
  view: Pick<ReturnType<typeof render>, "getByTestId" | "queryByTestId">,
) {
  return view.getByTestId("chat-input");
}
const PERSONA: TutorConfiguration = {
  schema_version: "tutor-configuration.v1",
  id: "cfg-1",
  learner_id: "learner-1",
  appearance: "animal",
  personality: "janelle",
  comfort_override: "none",
  chosen_at: "2026-10-17T00:00:00.000Z",
  last_changed_at: "2026-10-17T00:00:00.000Z",
  comfort_updated_at: null,
};
const STATE = {
  schema_version: "session-state.v1",
  session: {
    schema_version: "session.v1",
    id: SESSION_ID,
    learner_id: "learner-1",
    status: "active",
    goal: null,
    revision: 1,
    cancellation_epoch: 0,
    started_at: "2026-10-17T00:00:00.000Z",
    ended_at: null,
  },
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

const CAPABILITIES = (fixtures: boolean) => ({
  schema_version: "media-capabilities.v1",
  perception: {
    status: "unavailable",
    detail: "No image recognition is configured, so photos are never read.",
  },
  transcription: {
    status: "unavailable",
    detail: "No speech transcription is configured.",
  },
  speech_interruption: {
    supported: true,
    acoustic_barge_in: false,
    detail:
      "Stop interrupts the tutor's reply; the tutor cannot hear you interrupt.",
  },
  spoken_reply: {
    status: "unavailable",
    detail: "Hold to talk is off. The microphone button still uses this browser's speech.",
  },
  fixtures: { enabled: fixtures, detail: "Deterministic fixtures." },
  limits: {
    max_image_bytes: 262144,
    max_image_edge: 2048,
    max_image_events_per_minute: 3,
    max_image_events_per_session: 12,
    max_events_per_minute: 120,
    max_events_per_session: 500,
    max_transcript_chars: 500,
  },
  defaults: {
    raw_media_stored: false,
    raw_media_logged: false,
    transcripts_retained: false,
    provider_transmission: "none_configured",
  },
  disclosures: {
    local: ["Everything stays on this device."],
    transmitted: ["Nothing is transmitted to an outside service."],
  },
});

function result(body: Record<string, unknown>, extra: Record<string, unknown>) {
  return {
    schema_version: "media-event-result.v1",
    event_id: body.event_id,
    kind: body.kind,
    status: "provisional",
    simulated: body.source === "simulated",
    session_id: SESSION_ID,
    session_revision: 1,
    cancellation_epoch: 0,
    replayed: false,
    candidates: [],
    requires_confirmation: false,
    message: "",
    assessment_effect: "none",
    evidence_recorded: false,
    raw_media_retained: false,
    ...extra,
  };
}

function makeApi(options: { fixtures?: boolean; spoken?: "available" | "unavailable" } = {}) {
  const control = {
    mediaPosts: [] as Record<string, unknown>[],
    workPosts: 0,
    helpPosts: 0,
    mediaFails: false,
    finalized: new Set<string>(),
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
    if (url.endsWith("/media/capabilities")) {
      const body = CAPABILITIES(options.fixtures ?? false);
      const spoken = options.spoken ?? "unavailable";
      return respond(200, {
        ...body,
        spoken_reply: {
          status: spoken,
          detail:
            spoken === "available"
              ? "Hold to talk. xAI transcribes, the tutor replies, and xAI speaks only that reply."
              : "Hold to talk is off. The microphone button still uses this browser's speech.",
        },
      });
    }
    if (
      url.endsWith(`/sessions/${SESSION_ID}/media/events`) &&
      method === "POST"
    ) {
      if (control.mediaFails) throw new TypeError("Network request failed");
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      control.mediaPosts.push(body);
      if (body.kind === "image_snapshot" && body.source === "device") {
        return respond(
          200,
          result(body, {
            status: "perception_unavailable",
            message: "Photo reading is not configured. Type your step instead.",
          }),
        );
      }
      if (body.kind === "image_snapshot") {
        return respond(
          200,
          result(body, {
            status: "candidates_uncertain",
            requires_confirmation: true,
            message: "Synthetic reading. Check it before using it.",
            candidates: [
              {
                text: "2x + 3 = 14",
                confidence: 0.4,
                status: "uncertain",
                editable: true,
                synthetic: true,
              },
            ],
          }),
        );
      }
      if (body.kind === "weak_context") {
        return respond(
          200,
          result(body, {
            status: "clarification_prompt",
            message: "Would you like to tell me how it is going?",
          }),
        );
      }
      const utterance = String(body.utterance_id);
      if (body.phase === "interim") {
        return respond(
          200,
          result(body, {
            status: control.finalized.has(utterance)
              ? "ignored_late"
              : "provisional",
          }),
        );
      }
      const duplicate = control.finalized.has(utterance);
      control.finalized.add(utterance);
      return respond(
        200,
        result(body, {
          status: duplicate ? "duplicate_final" : "final_accepted",
          requires_confirmation: !duplicate,
        }),
      );
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/help`) && method === "POST") {
      control.helpPosts += 1;
      return respond(200, METHOD_SLIP_TURN);
    }
    if (url.endsWith(`/sessions/${SESSION_ID}/work`) && method === "POST") {
      control.workPosts += 1;
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
  fake: FakeMedia,
  extra: Partial<React.ComponentProps<typeof WorkspaceScreen>> = {},
) {
  const client = new ApiClient("http://tutor.test", "token", fetchImpl);
  const props = {
    client,
    sessionId: SESSION_ID,
    persona: PERSONA,
    displayName: "Riley",
    onSessionEnded: jest.fn(),
    media: fake.services,
    ...extra,
  };
  const view = render(<WorkspaceScreen {...props} />);
  return {
    ...view,
    rerenderWith: (
      patch: Partial<React.ComponentProps<typeof WorkspaceScreen>>,
    ) => view.rerender(<WorkspaceScreen {...props} {...patch} />),
  };
}

async function ready(view: ReturnType<typeof render>) {
  await waitFor(() => expect(view.getByTestId("prompt-problem")).toBeTruthy());
}

async function openPanel(view: ReturnType<typeof render>) {
  fireEvent.press(view.getByTestId("media-toggle"));
  await waitFor(() => expect(view.getByTestId("media-status")).toBeTruthy());
}

const avatar = (view: ReturnType<typeof render>) =>
  view.getByTestId("avatar-status");

describe("WorkspaceScreen optional media", () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
  });
  afterEach(() => jest.restoreAllMocks());

  it("starts nothing while rendering or opening the panel, and discloses honestly", async () => {
    const { fetchImpl } = makeApi();
    const fake = fakeMedia();
    const view = renderWorkspace(fetchImpl, fake);
    await ready(view);
    expect(view.queryByTestId("media-indicators")).toBeNull();
    await openPanel(view);
    expect(fake.calls).toEqual([]);
    expect(view.getByTestId("media-disclosure")).toHaveTextContent(
      /Everything stays on this device\./,
    );
    expect(view.getByTestId("media-status")).toHaveTextContent(
      /Voice transcription: unavailable/,
    );
    expect(view.getByTestId("media-status")).toHaveTextContent(
      /Photo reading: unavailable/,
    );
    expect(view.queryByTestId("media-fixtures")).toBeNull();
    expect(view.queryByTestId("hold-to-talk")).toBeNull();
    expect(view.getByTestId("spoken-reply-status")).toHaveTextContent(
      /Hold to talk: unavailable/,
    );
  });

  it("shows hold to talk only when the server and this browser can record", async () => {
    const devices = {
      getUserMedia: jest.fn(async () => ({ getTracks: () => [{ stop: () => undefined }] })),
    };
    Object.defineProperty(global.navigator, "mediaDevices", {
      configurable: true,
      value: devices,
    });
    const { fetchImpl } = makeApi({ spoken: "available" });
    const fake = fakeMedia();
    const view = renderWorkspace(fetchImpl, fake);
    await ready(view);
    await openPanel(view);
    expect(view.getByTestId("spoken-reply-status")).toHaveTextContent(
      /Hold to talk: available/,
    );
    fireEvent(view.getByTestId("hold-to-talk"), "pressIn");
    fireEvent(view.getByTestId("hold-to-talk"), "pressOut");
    await waitFor(() =>
      expect(view.getByTestId("talk-note")).toHaveTextContent(/Hold a little longer/),
    );
    expect(devices.getUserMedia).toHaveBeenCalled();
  });

  it("turns the microphone on only on press, shows an indicator and Stop releases it", async () => {
    const { fetchImpl } = makeApi();
    const fake = fakeMedia();
    const view = renderWorkspace(fetchImpl, fake);
    await ready(view);
    await openPanel(view);
    fireEvent.press(view.getByTestId("mic-start"));
    await waitFor(() =>
      expect(view.getByTestId("indicator-microphone")).toHaveTextContent(
        /Microphone is on/,
      ),
    );
    expect(fake.calls).toEqual(["mic.request", "mic.open"]);
    // An open microphone with no transcriber is not "the tutor listening".
    expect(avatar(view)).toHaveTextContent(/Ready/);
    expect(view.getByTestId("mic-note")).toHaveTextContent(
      /voice transcription is not configured/,
    );
    await act(async () => {
      fireEvent.press(view.getByTestId("stop-microphone"));
    });
    await waitFor(() =>
      expect(view.queryByTestId("indicator-microphone")).toBeNull(),
    );
    expect(fake.calls.at(-1)).toBe("mic.close");
  });

  it("keeps typing and drawing available after a denied microphone", async () => {
    const { fetchImpl, control } = makeApi();
    const fake = fakeMedia();
    fake.permissions.microphone = "denied";
    const view = renderWorkspace(fetchImpl, fake);
    await ready(view);
    await openPanel(view);
    fireEvent.press(view.getByTestId("mic-start"));
    await waitFor(() =>
      expect(view.getByTestId("capture-note")).toHaveTextContent(
        /Microphone permission was not granted/,
      ),
    );
    expect(fake.calls).toEqual(["mic.request"]);
    expect(view.queryByTestId("indicator-microphone")).toBeNull();
    fireEvent.changeText(typedStepInput(view), "2x + 3 = 14");
    fireEvent.press(view.getByTestId("chat-send"));
    await waitFor(() => expect(control.workPosts).toBe(1));
    expect(view.getByTestId("whiteboard")).toBeTruthy();
  });

  it("does not offer a camera in the voice panel", async () => {
    const { fetchImpl } = makeApi();
    const fake = fakeMedia();
    const view = renderWorkspace(fetchImpl, fake);
    await ready(view);
    await openPanel(view);
    expect(view.queryByTestId("camera-start-student")).toBeNull();
    expect(view.queryByTestId("camera-start-work")).toBeNull();
    expect(view.queryByTestId("take-photo")).toBeNull();
    expect(fake.calls).not.toContain("cam.request");
  });

  it("blocks capture entirely in text-only mode", async () => {
    const { fetchImpl } = makeApi();
    const fake = fakeMedia();
    const view = renderWorkspace(fetchImpl, fake, {
      accessibility: prefs({ text_only: true }),
    });
    await ready(view);
    await openPanel(view);
    expect(view.getByTestId("media-text-only")).toBeTruthy();
    expect(
      view.getByTestId("mic-start").props.accessibilityState.disabled,
    ).toBe(true);
    fireEvent.press(view.getByTestId("mic-start"));
    expect(fake.calls).toEqual([]);
  });

  it("reads a committed reply aloud with a caption and truthful speaking status", async () => {
    const { fetchImpl } = makeApi();
    const fake = fakeMedia();
    const view = renderWorkspace(fetchImpl, fake);
    await ready(view);
    await openPanel(view);
    fireEvent.press(view.getByTestId("voice-device"));
    fireEvent.press(view.getByTestId("help-me"));
    await waitFor(() => expect(fake.deviceSpeech).toHaveLength(1));
    // Asked to speak is not speaking: the status waits for the driver's own start.
    expect(avatar(view)).not.toHaveTextContent(/Speaking/);
    act(() => {
      fake.deviceSpeech[0].onStart();
    });
    await waitFor(() => expect(avatar(view)).toHaveTextContent(/Speaking/));
    expect(view.getByTestId("speech-caption")).toHaveTextContent(
      /What does the 2 do to each term\?/,
    );
    fireEvent.press(view.getByTestId("stop-speech"));
    await waitFor(() => expect(avatar(view)).toHaveTextContent(/Ready/));
    expect(view.queryByTestId("speech-caption")).toBeNull();
    // A late callback from the stopped reply cannot bring it back.
    act(() => {
      fake.deviceSpeech[0].onStart();
    });
    act(() => {
      fake.deviceSpeech[0].onDone();
    });
    expect(avatar(view)).toHaveTextContent(/Ready/);
    expect(fake.calls.filter((call) => call === "speech.speak")).toHaveLength(
      1,
    );
  });

  it("new work silences a reply that is being spoken and late audio cannot restart it", async () => {
    const { fetchImpl, control } = makeApi();
    const fake = fakeMedia();
    const view = renderWorkspace(fetchImpl, fake);
    await ready(view);
    await openPanel(view);
    fireEvent.press(view.getByTestId("voice-device"));
    fireEvent.press(view.getByTestId("help-me"));
    await waitFor(() => expect(fake.deviceSpeech).toHaveLength(1));
    act(() => {
      fake.deviceSpeech[0].onStart();
    });
    await waitFor(() => expect(avatar(view)).toHaveTextContent(/Speaking/));

    fireEvent.changeText(typedStepInput(view), "x = 4");
    fireEvent.press(view.getByTestId("chat-send"));
    await waitFor(() => expect(control.workPosts).toBe(1));
    expect(fake.calls).toContain("speech.stop");
    act(() => {
      fake.deviceSpeech[0].onStart();
    });
    expect(avatar(view)).not.toHaveTextContent(/Speaking/);
    expect(view.getByTestId("speech-note")).toHaveTextContent(
      /new work|stopped/i,
    );
  });

  it("makes zero speech driver calls when sound is muted, and captions and text stay", async () => {
    const { fetchImpl } = makeApi();
    const fake = fakeMedia();
    const view = renderWorkspace(fetchImpl, fake, {
      accessibility: prefs({ sound_enabled: false }),
    });
    await ready(view);
    await openPanel(view);
    fireEvent.press(view.getByTestId("voice-device"));
    expect(view.getByTestId("voice-muted-note")).toBeTruthy();
    fireEvent.press(view.getByTestId("help-me"));
    await waitFor(() => expect(view.getByTestId("prompt-tutor")).toBeTruthy());
    expect(fake.calls.filter((call) => call.includes("speech"))).toEqual([]);
    expect(avatar(view)).not.toHaveTextContent(/Speaking/);
  });

  it("covering the board stops speech and releases capture", async () => {
    const { fetchImpl } = makeApi();
    const fake = fakeMedia();
    const view = renderWorkspace(fetchImpl, fake);
    await ready(view);
    await openPanel(view);
    fireEvent.press(view.getByTestId("voice-device"));
    fireEvent.press(view.getByTestId("help-me"));
    await waitFor(() => expect(fake.deviceSpeech).toHaveLength(1));
    act(() => {
      fake.deviceSpeech[0].onStart();
    });
    await act(async () => {
      view.rerenderWith({ boardHidden: true });
    });
    await waitFor(() => expect(view.queryByTestId("fake-preview")).toBeNull());
    expect(fake.calls).toEqual(expect.arrayContaining(["speech.stop"]));
  });

  describe("labeled simulated events", () => {
    it("offers fixtures only when the server enables them", async () => {
      const off = makeApi({ fixtures: false });
      const fake = fakeMedia();
      const view = renderWorkspace(off.fetchImpl, fake);
      await ready(view);
      await openPanel(view);
      expect(view.queryByTestId("voice-simulated")).toBeNull();
      expect(view.queryByTestId("sim-voice-next")).toBeNull();
    });

    it("plays interim, revised, final, duplicate and late events without submitting work", async () => {
      const { fetchImpl, control } = makeApi({ fixtures: true });
      const fake = fakeMedia();
      const view = renderWorkspace(fetchImpl, fake);
      await ready(view);
      await openPanel(view);
      await waitFor(() =>
        expect(view.getByTestId("sim-voice-next")).toBeTruthy(),
      );

      fireEvent.press(view.getByTestId("sim-voice-next"));
      await waitFor(() =>
        expect(view.getByTestId("voice-provisional")).toHaveTextContent(
          /Provisional \(not final\): 2x plus 3/,
        ),
      );
      expect(avatar(view)).toHaveTextContent(/Listening \(simulated\)/);

      fireEvent.press(view.getByTestId("sim-voice-next"));
      await waitFor(() =>
        expect(view.getByTestId("voice-provisional")).toHaveTextContent(
          /2x plus 3 equals 1/,
        ),
      );
      expect(view.queryByTestId("voice-final-input")).toBeNull();

      fireEvent.press(view.getByTestId("sim-voice-next"));
      await waitFor(() =>
        expect(view.getByTestId("voice-final-input")).toBeTruthy(),
      );
      expect(view.queryByTestId("voice-provisional")).toBeNull();
      expect(avatar(view)).toHaveTextContent(/Ready/);

      fireEvent.press(view.getByTestId("sim-voice-next"));
      await waitFor(() =>
        expect(view.getByTestId("voice-note")).toHaveTextContent(
          /repeated final/,
        ),
      );
      fireEvent.press(view.getByTestId("sim-voice-next"));
      await waitFor(() =>
        expect(view.getByTestId("voice-note")).toHaveTextContent(/late update/),
      );
      // The late interim did not reopen the utterance or the listening state.
      expect(view.queryByTestId("voice-provisional")).toBeNull();
      expect(avatar(view)).toHaveTextContent(/Ready/);
      expect(control.workPosts).toBe(0);
      expect(control.mediaPosts.map((post) => post.phase)).toEqual([
        "interim",
        "interim",
        "final",
        "final",
        "interim",
      ]);
      expect(
        new Set(control.mediaPosts.map((post) => post.utterance_id)).size,
      ).toBe(1);
      expect(
        control.mediaPosts.every((post) => post.source === "simulated"),
      ).toBe(true);
    });

    it("offers final text for editing and only fills the typed step", async () => {
      const { fetchImpl, control } = makeApi({ fixtures: true });
      const fake = fakeMedia();
      const view = renderWorkspace(fetchImpl, fake);
      await ready(view);
      await openPanel(view);
      await waitFor(() =>
        expect(view.getByTestId("sim-voice-next")).toBeTruthy(),
      );
      for (let i = 0; i < 3; i += 1) {
        fireEvent.press(view.getByTestId("sim-voice-next"));
        await waitFor(() =>
          expect(
            view.getByTestId("sim-voice-next").props.accessibilityState
              .disabled,
          ).toBe(false),
        );
        await waitFor(() => expect(control.mediaPosts).toHaveLength(i + 1));
      }
      await waitFor(() =>
        expect(view.getByTestId("voice-final-input")).toBeTruthy(),
      );
      fireEvent.changeText(
        view.getByTestId("voice-final-input"),
        "2x + 6 = 14",
      );
      fireEvent.press(view.getByTestId("voice-final-use"));
      expect(typedStepInput(view).props.value).toBe(
        "2x + 6 = 14",
      );
      expect(control.workPosts).toBe(0);
    });

    it("shows a synthetic reading as uncertain and editable, not as the learner's work", async () => {
      const { fetchImpl, control } = makeApi({ fixtures: true });
      const fake = fakeMedia();
      const view = renderWorkspace(fetchImpl, fake);
      await ready(view);
      await openPanel(view);
      await waitFor(() => expect(view.getByTestId("sim-photo")).toBeTruthy());
      fireEvent.press(view.getByTestId("sim-photo"));
      await waitFor(() =>
        expect(view.getByTestId("media-outcome")).toBeTruthy(),
      );
      expect(view.getByTestId("media-outcome")).toHaveTextContent(
        /Simulated, synthetic result for testing/,
      );
      expect(view.getByTestId("candidate-0-input").props.value).toBe(
        "2x + 3 = 14",
      );
      expect(
        view.getByTestId("candidate-0-input").props.accessibilityLabel,
      ).toMatch(/uncertain reading.*check and edit/i);
      expect(typedStepInput(view).props.value).toBe("");
      fireEvent.press(view.getByTestId("candidate-0-use"));
      expect(typedStepInput(view).props.value).toBe(
        "2x + 3 = 14",
      );
      expect(control.workPosts).toBe(0);
    });

    it("answers a quiet moment with a neutral question, not an inference", async () => {
      const { fetchImpl } = makeApi({ fixtures: true });
      const fake = fakeMedia();
      const view = renderWorkspace(fetchImpl, fake);
      await ready(view);
      await openPanel(view);
      await waitFor(() => expect(view.getByTestId("sim-cue")).toBeTruthy());
      fireEvent.press(view.getByTestId("sim-cue"));
      await waitFor(() =>
        expect(view.getByTestId("media-outcome")).toHaveTextContent(
          /Would you like to tell me how it is going\?/,
        ),
      );
    });

    it("says so and changes nothing when a media event cannot reach the tutor", async () => {
      const { fetchImpl, control } = makeApi({ fixtures: true });
      const fake = fakeMedia();
      const view = renderWorkspace(fetchImpl, fake);
      await ready(view);
      await openPanel(view);
      await waitFor(() => expect(view.getByTestId("sim-photo")).toBeTruthy());
      control.mediaFails = true;
      fireEvent.press(view.getByTestId("sim-photo"));
      await waitFor(() =>
        expect(view.getByTestId("media-notice")).toHaveTextContent(
          /could not be reached/,
        ),
      );
      expect(view.queryByTestId("media-outcome")).toBeNull();
      fireEvent.changeText(typedStepInput(view), "x = 4");
      fireEvent.press(view.getByTestId("chat-send"));
      await waitFor(() => expect(control.workPosts).toBe(1));
    });

    it("labels simulated spoken replies and stops them with the same Stop control", async () => {
      const { fetchImpl } = makeApi({ fixtures: true });
      const fake = fakeMedia();
      const view = renderWorkspace(fetchImpl, fake);
      await ready(view);
      await openPanel(view);
      await waitFor(() =>
        expect(view.getByTestId("voice-simulated")).toBeTruthy(),
      );
      fireEvent.press(view.getByTestId("voice-simulated"));
      fireEvent.press(view.getByTestId("help-me"));
      await waitFor(() => expect(fake.simulatedSpeech).toHaveLength(1));
      act(() => {
        fake.simulatedSpeech[0].onStart();
      });
      await waitFor(() =>
        expect(avatar(view)).toHaveTextContent(/Speaking \(simulated\)/),
      );
      expect(view.getByTestId("speech-caption")).toHaveTextContent(
        /Caption \(simulated voice\)/,
      );
      expect(fake.deviceSpeech).toHaveLength(0);
      fireEvent.press(view.getByTestId("stop-speech"));
      await waitFor(() => expect(avatar(view)).toHaveTextContent(/Ready/));
    });
  });
});
