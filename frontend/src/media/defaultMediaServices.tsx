import React from "react";

import type { CaptureDriver } from "./captureTypes";
import type { MediaServices } from "./mediaServices";
import type { SpeechDriver } from "./speechController";

let services: MediaServices | null = null;

function once<T>(load: () => T): () => T {
  let value: T | undefined;
  return () => (value ??= load());
}

/* eslint-disable @typescript-eslint/no-require-imports */
const loadCapture = once(
  () => (require("./captureDriver") as typeof import("./captureDriver")).deviceCaptureDriver,
);
const loadSpeech = once(
  () => (require("./speechDriver") as typeof import("./speechDriver")).deviceSpeechDriver,
);
const loadSimulated = once(() =>
  (require("./speechDriver") as typeof import("./speechDriver")).createSimulatedSpeechDriver(),
);
const loadPreview = once(
  () => (require("./cameraDriver") as typeof import("./cameraDriver")).CameraPreview,
);
/* eslint-enable @typescript-eslint/no-require-imports */

const capture: CaptureDriver = {
  microphone: {
    request: () => loadCapture().microphone.request(),
    open: () => loadCapture().microphone.open(),
    close: () => loadCapture().microphone.close(),
  },
  camera: {
    available: () => loadCapture().camera.available(),
    request: () => loadCapture().camera.request(),
    open: (orientation) => loadCapture().camera.open(orientation),
    close: () => loadCapture().camera.close(),
    snapshot: () => loadCapture().camera.snapshot(),
  },
};

const speech: SpeechDriver = {
  simulated: false,
  available: () => loadSpeech().available(),
  speak: (text, handlers) => loadSpeech().speak(text, handlers),
  stop: () => loadSpeech().stop(),
};

const simulatedSpeech: SpeechDriver = {
  simulated: true,
  available: () => true,
  speak: (text, handlers) => loadSimulated().speak(text, handlers),
  stop: () => loadSimulated().stop(),
};

/**
 * The real expo-camera / expo-audio / expo-speech drivers. Each native module is loaded the
 * first time a driver method is called, which only happens after the learner starts media,
 * so rendering a screen never touches them.
 */
export function defaultMediaServices(): MediaServices {
  services ??= {
    capture,
    speech,
    simulatedSpeech,
    renderPreview: (props) => {
      const Preview = loadPreview();
      return <Preview {...props} />;
    },
  };
  return services;
}
