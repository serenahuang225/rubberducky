import { createWebTranscriptRecognizer } from "./transcriptRecognizer.web";

type Handler = {
  onresult: ((event: unknown) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: jest.Mock;
  abort: jest.Mock;
};

function installRecognizer() {
  const sessions: Handler[] = [];
  class FakeSpeech {
    continuous = false;
    interimResults = false;
    lang = "";
    onresult: Handler["onresult"] = null;
    onerror: Handler["onerror"] = null;
    onend: Handler["onend"] = null;
    start = jest.fn();
    abort = jest.fn();
    constructor() {
      sessions.push(this);
    }
  }
  const host = globalThis as { webkitSpeechRecognition?: typeof FakeSpeech };
  const previous = host.webkitSpeechRecognition;
  host.webkitSpeechRecognition = FakeSpeech;
  return {
    sessions,
    restore: () => {
      host.webkitSpeechRecognition = previous;
    },
  };
}

describe("web transcript recognizer", () => {
  it("is unavailable when the browser has no speech API", () => {
    const host = globalThis as {
      SpeechRecognition?: unknown;
      webkitSpeechRecognition?: unknown;
    };
    const speech = host.SpeechRecognition;
    const webkit = host.webkitSpeechRecognition;
    host.SpeechRecognition = undefined;
    host.webkitSpeechRecognition = undefined;
    const recognizer = createWebTranscriptRecognizer();
    expect(recognizer.available()).toBe(false);
    host.SpeechRecognition = speech;
    host.webkitSpeechRecognition = webkit;
  });

  it("emits interim then final text and ignores results after stop", () => {
    const { sessions, restore } = installRecognizer();
    const recognizer = createWebTranscriptRecognizer();
    const seen: string[] = [];
    recognizer.start({
      onResult: (chunk) => seen.push(`${chunk.phase}:${chunk.text}`),
      onError: () => seen.push("error"),
    });
    const session = sessions[0];
    session.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: false, 0: { transcript: "2x plus" } }],
    });
    session.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "2x + 3 = 14" } }],
    });
    recognizer.stop();
    session.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "late" } }],
    });
    expect(session.start).toHaveBeenCalledTimes(1);
    expect(session.abort).toHaveBeenCalledTimes(1);
    expect(seen).toEqual(["interim:2x plus", "final:2x + 3 = 14"]);
    restore();
  });

  it("does not restart after the learner stops, and does restart after a pause", () => {
    const { sessions, restore } = installRecognizer();
    const recognizer = createWebTranscriptRecognizer();
    recognizer.start({ onResult: () => undefined, onError: () => undefined });
    sessions[0].onend?.();
    expect(sessions).toHaveLength(2);
    recognizer.stop();
    sessions[1].onend?.();
    expect(sessions).toHaveLength(2);
    restore();
  });
});
