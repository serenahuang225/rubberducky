/**
 * One hold-to-talk recording. Nothing opens the microphone until `start`.
 * The clip is kept in memory only long enough to post it.
 */

export type TalkClip = {
  bytes: Blob;
  mime: string;
};

export type TalkStream = {
  getTracks: () => { stop: () => void }[];
};

export type TalkSession = {
  start: () => void;
  stop: () => Promise<TalkClip | null>;
};

export type TalkHost = {
  available: () => boolean;
  getUserMedia: () => Promise<TalkStream>;
  record: (stream: TalkStream) => TalkSession;
};

const MIN_CLIP_BYTES = 200;

function pickMime(): string {
  const recorder = (globalThis as { MediaRecorder?: { isTypeSupported?: (t: string) => boolean } })
    .MediaRecorder;
  const supported = recorder?.isTypeSupported?.bind(recorder);
  if (supported?.("audio/webm;codecs=opus")) return "audio/webm;codecs=opus";
  if (supported?.("audio/webm")) return "audio/webm";
  if (supported?.("audio/mp4")) return "audio/mp4";
  return "";
}

export function browserTalkHost(): TalkHost {
  return {
    available: () =>
      typeof navigator !== "undefined" && typeof navigator.mediaDevices?.getUserMedia === "function",
    getUserMedia: () => navigator.mediaDevices.getUserMedia({ audio: true }),
    record: (stream) => {
      const Rec = (globalThis as { MediaRecorder?: new (s: MediaStream, o?: { mimeType: string }) => MediaRecorder })
        .MediaRecorder;
      if (Rec === undefined) {
        return {
          start: () => undefined,
          stop: async () => {
            stream.getTracks().forEach((track) => track.stop());
            return null;
          },
        };
      }
      const mime = pickMime();
      const recorder = mime
        ? new Rec(stream as MediaStream, { mimeType: mime })
        : new Rec(stream as MediaStream);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      };
      return {
        start: () => recorder.start(),
        stop: () =>
          new Promise((resolve) => {
            recorder.onstop = () => {
              stream.getTracks().forEach((track) => track.stop());
              const type = (recorder.mimeType || mime || "audio/webm").split(";")[0] || "audio/webm";
              const bytes = new Blob(chunks, { type });
              resolve(bytes.size >= MIN_CLIP_BYTES ? { bytes, mime: type } : null);
            };
            if (recorder.state === "inactive") {
              stream.getTracks().forEach((track) => track.stop());
              resolve(null);
              return;
            }
            recorder.stop();
          }),
      };
    },
  };
}

export type TalkRecorder = {
  available: () => boolean;
  start: () => Promise<void>;
  stop: () => Promise<TalkClip | null>;
};

export function talkCaptureAvailable(): boolean {
  return browserTalkHost().available();
}

export function createTalkRecorder(host: TalkHost = browserTalkHost()): TalkRecorder {
  let generation = 0;
  let session: TalkSession | null = null;

  return {
    available: () => host.available(),
    start: async () => {
      const ticket = ++generation;
      const stream = await host.getUserMedia();
      if (ticket !== generation) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      session = host.record(stream);
      session.start();
    },
    stop: async () => {
      generation += 1;
      const current = session;
      session = null;
      if (current === null) return null;
      return current.stop();
    },
  };
}
