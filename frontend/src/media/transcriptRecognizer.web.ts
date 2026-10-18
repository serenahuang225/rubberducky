/**
 * Browser speech recognition. Chrome sends audio to Google; Safari uses the system
 * recognizer. This module never reads sample buffers and never posts audio.
 */

import type {
  TranscriptHandlers,
  TranscriptRecognizer,
} from "./transcriptRecognizer";

type SpeechResult = {
  isFinal: boolean;
  0: { transcript: string };
};

type SpeechEvent = {
  resultIndex: number;
  results: ArrayLike<SpeechResult>;
};

type SpeechErrorEvent = { error?: string };

type SpeechSession = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechEvent) => void) | null;
  onerror: ((event: SpeechErrorEvent) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  abort: () => void;
};

type SpeechCtor = new () => SpeechSession;

function speechCtor(): SpeechCtor | null {
  const host = globalThis as {
    SpeechRecognition?: SpeechCtor;
    webkitSpeechRecognition?: SpeechCtor;
  };
  return host.SpeechRecognition ?? host.webkitSpeechRecognition ?? null;
}

const FATAL = new Set(["not-allowed", "service-not-allowed", "audio-capture"]);

export function createWebTranscriptRecognizer(): TranscriptRecognizer {
  let handlers: TranscriptHandlers | null = null;
  let session: SpeechSession | null = null;
  let wanted = false;
  let opening = false;

  const open = () => {
    const Ctor = speechCtor();
    if (Ctor === null || !wanted || handlers === null) return;
    const next = new Ctor();
    next.continuous = true;
    next.interimResults = true;
    next.lang = "en-US";
    next.onresult = (event) => {
      if (!wanted || handlers === null) return;
      let finalText = "";
      let interim = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const text = result?.[0]?.transcript ?? "";
        if (result?.isFinal) finalText += text;
        else interim += text;
      }
      if (finalText.trim().length > 0) {
        handlers.onResult({ phase: "final", text: finalText });
      } else if (interim.trim().length > 0) {
        handlers.onResult({ phase: "interim", text: interim });
      }
    };
    next.onerror = (event) => {
      if (FATAL.has(event.error ?? "")) {
        wanted = false;
        handlers?.onError();
      }
    };
    next.onend = () => {
      if (session === next) session = null;
      // Chrome ends the session after a pause. Restart only while the learner
      // still wants the microphone, and never after they pressed stop.
      if (!wanted || opening) return;
      try {
        open();
      } catch {
        handlers?.onError();
      }
    };
    session = next;
    opening = true;
    try {
      next.start();
    } catch {
      session = null;
      wanted = false;
      handlers.onError();
    } finally {
      opening = false;
    }
  };

  return {
    available: () => speechCtor() !== null,
    transmission: "browser_speech_service",
    start: (next) => {
      handlers = next;
      wanted = true;
      if (session !== null) return;
      open();
    },
    stop: () => {
      wanted = false;
      handlers = null;
      const current = session;
      session = null;
      try {
        current?.abort();
      } catch {
        // The session already ended.
      }
    },
  };
}

export const deviceTranscriptRecognizer = createWebTranscriptRecognizer();
