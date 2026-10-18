import type { ReactElement } from "react";

import type { CameraPreviewProps } from "./cameraDriver";
import type { CaptureDriver } from "./captureTypes";
import type { SpeechDriver } from "./speechController";
import type { TranscriptRecognizer } from "./transcriptRecognizer";

/** Everything the media layer needs from the platform, replaceable in tests. */
export type MediaServices = {
  capture: CaptureDriver;
  speech: SpeechDriver;
  simulatedSpeech: SpeechDriver;
  /** Live speech-to-text. Unavailable builds report available() === false. */
  recognizer: TranscriptRecognizer;
  renderPreview: (props: CameraPreviewProps) => ReactElement;
};
