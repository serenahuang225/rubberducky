/**
 * Speech/caption lifecycle bound to the workspace's real scope (session, turn generation,
 * server epoch, problem) and to the learner's sound policy. Late driver callbacks are
 * delivered after every cancellation trigger to show that they cannot restart anything.
 * The drivers are fakes: this proves cancellation logic, not live audio or transcription.
 */

import { act, renderHook, waitFor } from "@testing-library/react-native";
import { AppState } from "react-native";

import type { ApiClient } from "../api/client";
import { fakeMedia, type FakeMedia } from "../testing/fakeMedia";

import { useMedia, type UseMediaInput } from "./useMedia";

type Overrides = Partial<Omit<UseMediaInput, "client" | "services">>;

function setup(
  fake: FakeMedia,
  initial: Overrides = {},
  capabilities?: { transcription: { status: string; detail: string } },
) {
  const client = {
    mediaCapabilities: jest.fn(async () => capabilities),
    postMediaEvent: jest.fn(async (_session: string, event: { kind: string; phase?: string; source?: string }) => {
      fake.mediaPosts.push(event as never);
      return {
        status:
          event.kind === "transcript" && event.phase === "final"
            ? "final_accepted"
            : "provisional",
        simulated: event.source === "simulated",
        message: "ok",
        candidates: [],
      };
    }),
  } as unknown as ApiClient;
  const base: UseMediaInput = {
    client,
    sessionId: "s1",
    services: fake.services,
    generation: 1,
    epoch: 0,
    revision: 1,
    attemptId: "a1",
    reply: null,
    busy: false,
    soundAllowed: true,
    textOnly: false,
    boardHidden: false,
    ...initial,
  };
  const hook = renderHook((props: Overrides) => useMedia({ ...base, ...props }), {
    initialProps: initial,
  });
  return hook;
}

const reply = (turnId: string, epoch = 0) => ({
  turnId,
  text: `Reply ${turnId}`,
  epoch,
});

async function speakingHook(fake: FakeMedia, overrides: Overrides = {}) {
  const hook = setup(fake, overrides);
  act(() => hook.result.current.setVoiceMode("device"));
  hook.rerender({ ...overrides, reply: reply("t1") });
  expect(fake.deviceSpeech).toHaveLength(1);
  act(() => fake.deviceSpeech[0].onStart());
  expect(hook.result.current.speech.phase).toBe("speaking");
  expect(hook.result.current.activity).toEqual({
    kind: "speaking",
    source: "live",
  });
  return hook;
}

describe("useMedia startup", () => {
  it("calls no driver at all until the learner acts", () => {
    const fake = fakeMedia();
    const hook = setup(fake);
    hook.rerender({ reply: reply("t1") });
    expect(fake.calls).toEqual([]);
    expect(hook.result.current.capture.microphone.status).toBe("off");
    expect(hook.result.current.capture.camera.status).toBe("off");
    expect(hook.result.current.activity).toBeNull();
  });

  it("does not read a reply that was already on screen when voice is turned on", () => {
    const fake = fakeMedia();
    const hook = setup(fake, { reply: reply("old") });
    act(() => hook.result.current.setVoiceMode("device"));
    expect(fake.deviceSpeech).toHaveLength(0);
    hook.rerender({ reply: reply("old") });
    expect(fake.deviceSpeech).toHaveLength(0);
  });
});

describe("useMedia spoken replies follow sound policy", () => {
  it("speaks a newly committed reply once when voice is on and sound allowed", () => {
    const fake = fakeMedia();
    const hook = setup(fake);
    act(() => hook.result.current.setVoiceMode("device"));
    hook.rerender({ reply: reply("t1") });
    hook.rerender({ reply: reply("t1") });
    expect(fake.calls.filter((c) => c === "speech.speak")).toHaveLength(1);
  });

  it("makes zero driver calls when sound is muted or text-only is on", () => {
    for (const policy of [{ soundAllowed: false }, { textOnly: true, soundAllowed: false }]) {
      const fake = fakeMedia();
      const hook = setup(fake, policy);
      act(() => hook.result.current.setVoiceMode("device"));
      hook.rerender({ ...policy, reply: reply("t1") });
      hook.rerender({ ...policy, reply: reply("t2") });
      act(() => hook.result.current.cancelSpeech("user_stop"));
      expect(fake.calls.filter((c) => c.startsWith("speech."))).toEqual([]);
      expect(hook.result.current.activity).toBeNull();
    }
  });

  it("makes zero driver calls while the voice mode is off", () => {
    const fake = fakeMedia();
    const hook = setup(fake);
    hook.rerender({ reply: reply("t1") });
    expect(fake.calls).toEqual([]);
  });

  it("muting mid-speech stops the driver and the status leaves speaking", () => {
    const fake = fakeMedia();
    return speakingHook(fake).then((hook) => {
      hook.rerender({ reply: reply("t1"), soundAllowed: false });
      expect(fake.calls).toContain("speech.stop");
      expect(hook.result.current.activity).toBeNull();
    });
  });

  it("labels the simulated driver's speech as simulated", () => {
    const fake = fakeMedia();
    const hook = setup(fake);
    act(() => hook.result.current.setVoiceMode("simulated"));
    hook.rerender({ reply: reply("t1") });
    act(() => fake.simulatedSpeech[0].onStart());
    expect(hook.result.current.activity).toEqual({
      kind: "speaking",
      source: "simulated",
    });
    expect(fake.deviceSpeech).toHaveLength(0);
  });

  it("does not speak a reply from an epoch the server has already moved past", () => {
    const fake = fakeMedia();
    const hook = setup(fake, { epoch: 3 });
    act(() => hook.result.current.setVoiceMode("device"));
    hook.rerender({ epoch: 3, reply: reply("late", 2) });
    expect(fake.deviceSpeech).toHaveLength(0);
  });
});

describe("useMedia cancellation triggers", () => {
  async function deliverLate(fake: FakeMedia, hook: ReturnType<typeof setup>) {
    const handlers = fake.deviceSpeech[0];
    act(() => {
      handlers.onStart();
      handlers.onDone();
      handlers.onError();
    });
    expect(hook.result.current.activity).toBeNull();
    expect(hook.result.current.speech.phase).toBe("cancelled");
    expect(fake.deviceSpeech).toHaveLength(1);
  }

  it("new work (a running tutor command) cancels speech", async () => {
    const fake = fakeMedia();
    const hook = await speakingHook(fake);
    hook.rerender({ reply: reply("t1"), busy: true });
    expect(hook.result.current.speech.note).toMatch(/new work/i);
    await deliverLate(fake, hook);
  });

  it("an interrupted turn generation cancels speech", async () => {
    const fake = fakeMedia();
    const hook = await speakingHook(fake);
    hook.rerender({ reply: reply("t1"), generation: 2 });
    expect(hook.result.current.speech.note).toMatch(/stopped the reply/i);
    await deliverLate(fake, hook);
  });

  it("a new problem cancels speech", async () => {
    const fake = fakeMedia();
    const hook = await speakingHook(fake);
    hook.rerender({ reply: reply("t1"), attemptId: "a2" });
    expect(hook.result.current.speech.note).toMatch(/problem changed/i);
    await deliverLate(fake, hook);
  });

  it("a new server epoch (withdrawn output after correction or deletion) cancels speech", async () => {
    const fake = fakeMedia();
    const hook = await speakingHook(fake);
    hook.rerender({ reply: reply("t1"), epoch: 1 });
    expect(hook.result.current.speech.phase).toBe("cancelled");
    await deliverLate(fake, hook);
  });

  it("a new session cancels speech", async () => {
    const fake = fakeMedia();
    const hook = await speakingHook(fake);
    hook.rerender({ reply: reply("t1"), sessionId: "s2" });
    expect(hook.result.current.speech.phase).toBe("cancelled");
    await deliverLate(fake, hook);
  });

  it("covering the board cancels speech", async () => {
    const fake = fakeMedia();
    const hook = await speakingHook(fake);
    hook.rerender({ reply: reply("t1"), boardHidden: true });
    expect(hook.result.current.speech.note).toMatch(/left the board/i);
    await deliverLate(fake, hook);
  });

  it("Stop speaking cancels speech and keeps the reply text untouched", async () => {
    const fake = fakeMedia();
    const hook = await speakingHook(fake);
    act(() => hook.result.current.cancelSpeech("user_stop"));
    await deliverLate(fake, hook);
  });

  it("unmounting cancels speech", async () => {
    const fake = fakeMedia();
    const hook = await speakingHook(fake);
    hook.unmount();
    expect(fake.calls).toContain("speech.stop");
    const before = fake.calls.length;
    fake.deviceSpeech[0].onDone();
    expect(fake.calls).toHaveLength(before);
  });

  it("a following current turn speaks normally after a cancellation", async () => {
    const fake = fakeMedia();
    const hook = await speakingHook(fake);
    hook.rerender({ reply: reply("t1"), generation: 2, epoch: 1 });
    hook.rerender({ reply: reply("t2", 1), generation: 2, epoch: 1 });
    expect(fake.deviceSpeech).toHaveLength(2);
    act(() => fake.deviceSpeech[1].onStart());
    expect(hook.result.current.speech).toMatchObject({
      phase: "speaking",
      turnId: "t2",
    });
    // The first, cancelled reply still cannot change anything.
    act(() => fake.deviceSpeech[0].onDone());
    expect(hook.result.current.speech.phase).toBe("speaking");
  });
});

describe("useMedia capture lifecycle", () => {
  it("backgrounding the app releases the camera and microphone", async () => {
    let listener: ((state: string) => void) | null = null;
    jest.spyOn(AppState, "addEventListener").mockImplementation(((
      _type: string,
      handler: (state: string) => void,
    ) => {
      listener = handler;
      return { remove: jest.fn() };
    }) as never);
    const fake = fakeMedia();
    const hook = setup(fake);
    act(() => hook.result.current.startMicrophone());
    act(() => hook.result.current.startCamera("work_facing"));
    await waitFor(() => {
      expect(hook.result.current.capture.microphone.status).toBe("on");
      expect(hook.result.current.capture.camera.status).toBe("on");
    });
    await act(async () => {
      listener?.("background");
    });
    await waitFor(() => {
      expect(hook.result.current.capture.microphone.status).toBe("off");
      expect(hook.result.current.capture.camera.status).toBe("off");
    });
    expect(fake.calls).toEqual(expect.arrayContaining(["mic.close", "cam.close"]));
    expect(hook.result.current.capture.camera.note).toMatch(/foreground/i);
    jest.restoreAllMocks();
  });

  it("covering the board releases capture with an honest reason", async () => {
    const fake = fakeMedia();
    const hook = setup(fake);
    act(() => hook.result.current.startCamera("student_facing"));
    await waitFor(() =>
      expect(hook.result.current.capture.camera.status).toBe("on"),
    );
    hook.rerender({ boardHidden: true });
    await waitFor(() =>
      expect(hook.result.current.capture.camera.status).toBe("off"),
    );
    expect(hook.result.current.capture.camera.note).toMatch(/left the board/i);
  });

  it("turning text-only on releases capture and blocks new starts", async () => {
    const fake = fakeMedia();
    const hook = setup(fake);
    act(() => hook.result.current.startMicrophone());
    await waitFor(() =>
      expect(hook.result.current.capture.microphone.status).toBe("on"),
    );
    hook.rerender({ textOnly: true, soundAllowed: false });
    await waitFor(() =>
      expect(hook.result.current.capture.microphone.status).toBe("off"),
    );
    const before = fake.calls.length;
    act(() => hook.result.current.startCamera("student_facing"));
    await waitFor(() =>
      expect(hook.result.current.capture.camera.note).toMatch(/text-only/i),
    );
    expect(fake.calls).toHaveLength(before);
  });

  it("an open microphone is not reported as listening while transcription is unconfigured", async () => {
    const fake = fakeMedia();
    const hook = setup(fake);
    act(() => hook.result.current.startMicrophone());
    await waitFor(() =>
      expect(hook.result.current.capture.microphone.status).toBe("on"),
    );
    expect(hook.result.current.transcriptionAvailable).toBe(false);
    expect(hook.result.current.activity).toBeNull();
    expect(fake.recognizerStarts).toBe(0);
  });

  it("sends browser speech as a device transcript and ignores it after the microphone stops", async () => {
    const fake = fakeMedia();
    fake.recognizerAvailable = true;
    const hook = setup(fake, {}, {
      transcription: { status: "available", detail: "browser" },
    });
    act(() => hook.result.current.loadCapabilities());
    await waitFor(() =>
      expect(hook.result.current.transcriptionAvailable).toBe(true),
    );
    act(() => hook.result.current.startMicrophone());
    await waitFor(() =>
      expect(hook.result.current.capture.microphone.status).toBe("on"),
    );
    expect(fake.recognizerStarts).toBe(1);
    const handlers = fake.recognizerHandlers;
    expect(handlers).not.toBeNull();
    act(() => handlers?.onResult({ phase: "interim", text: "2x plus 3" }));
    await waitFor(() => expect(fake.mediaPosts).toHaveLength(1));
    expect(fake.mediaPosts[0]).toMatchObject({
      kind: "transcript",
      source: "device",
      phase: "interim",
      text: "2x plus 3",
    });
    await waitFor(() =>
      expect(hook.result.current.voice.provisional).toBe("2x plus 3"),
    );
    expect(hook.result.current.activity).toEqual({
      kind: "listening",
      source: "live",
    });
    act(() => hook.result.current.stopCapture("microphone"));
    await waitFor(() =>
      expect(hook.result.current.capture.microphone.status).toBe("off"),
    );
    const posted = fake.mediaPosts.length;
    act(() =>
      handlers?.onResult({ phase: "final", text: "should be ignored" }),
    );
    expect(fake.mediaPosts).toHaveLength(posted);
    expect(hook.result.current.voice.final).toBeNull();
  });
});
