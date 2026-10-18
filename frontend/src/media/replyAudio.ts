/**
 * Play MP3 bytes the server returned for the tutor's reply.
 *
 * The AudioContext is created on the hold-to-talk press, before the request, so a later
 * play() still counts as part of that gesture. This module does not synthesize speech.
 */

import type { SpeechHandlers } from "./speechController";

type AudioContextCtor = typeof AudioContext;

let context: AudioContext | null = null;

function contextCtor(): AudioContextCtor | null {
  if (typeof globalThis === "undefined") return null;
  const host = globalThis as { AudioContext?: AudioContextCtor; webkitAudioContext?: AudioContextCtor };
  return host.AudioContext ?? host.webkitAudioContext ?? null;
}

/** Call from the press that starts a recording, before any await. */
export function primeReplyAudio(): void {
  const Ctor = contextCtor();
  if (Ctor === null) return;
  context ??= new Ctor();
  void context.resume();
}

export function bytesFromBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

/** Start playback. Returns stop. Calls `onError` when this browser cannot play the bytes. */
export function playReplyBytes(bytes: Uint8Array, handlers: SpeechHandlers): () => void {
  const current = context ?? (contextCtor() === null ? null : new (contextCtor() as AudioContextCtor)());
  if (current === null) {
    handlers.onError();
    return () => undefined;
  }
  context = current;
  let source: AudioBufferSourceNode | null = null;
  let stopped = false;
  const copy = bytes.slice().buffer as ArrayBuffer;
  void current.decodeAudioData(copy).then(
    (buffer) => {
      if (stopped) return;
      source = current.createBufferSource();
      source.buffer = buffer;
      source.connect(current.destination);
      source.onended = () => {
        if (stopped) return;
        handlers.onDone();
      };
      source.start();
      handlers.onStart();
    },
    () => {
      if (!stopped) handlers.onError();
    },
  );
  return () => {
    stopped = true;
    try {
      source?.stop();
    } catch {
      // Already finished.
    }
  };
}
