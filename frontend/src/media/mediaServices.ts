import type { ReactElement } from "react";

import type { CameraPreviewProps } from "./cameraDriver";
import type { CaptureDriver } from "./captureTypes";
import type { SpeechDriver } from "./speechController";

/** Everything the media layer needs from the platform, replaceable in tests. */
export type MediaServices = {
  capture: CaptureDriver;
  speech: SpeechDriver;
  simulatedSpeech: SpeechDriver;
  renderPreview: (props: CameraPreviewProps) => ReactElement;
};
