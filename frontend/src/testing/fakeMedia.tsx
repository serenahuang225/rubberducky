/**
 * Fake platform drivers for tests. They record every call so a test can assert that nothing
 * was requested, opened or spoken unless the learner asked for it. Test-only; never bundled.
 */

import React from "react";
import { View } from "react-native";

import type { CaptureDriver, PermissionResult } from "../media/captureTypes";
import type { MediaServices } from "../media/mediaServices";
import type { SpeechDriver, SpeechHandlers } from "../media/speechController";

export type FakeMedia = {
  services: MediaServices;
  calls: string[];
  /** Handlers handed to the device speech driver, oldest first. */
  deviceSpeech: SpeechHandlers[];
  simulatedSpeech: SpeechHandlers[];
  permissions: { microphone: PermissionResult; camera: PermissionResult };
  cameraPresent: boolean;
};

export function fakeMedia(): FakeMedia {
  const fake: FakeMedia = {
    calls: [],
    deviceSpeech: [],
    simulatedSpeech: [],
    permissions: { microphone: "granted", camera: "granted" },
    cameraPresent: true,
    services: undefined as unknown as MediaServices,
  };
  const capture: CaptureDriver = {
    microphone: {
      request: async () => {
        fake.calls.push("mic.request");
        return fake.permissions.microphone;
      },
      open: async () => {
        fake.calls.push("mic.open");
      },
      close: async () => {
        fake.calls.push("mic.close");
      },
    },
    camera: {
      available: async () => {
        fake.calls.push("cam.available");
        return fake.cameraPresent;
      },
      request: async () => {
        fake.calls.push("cam.request");
        return fake.permissions.camera;
      },
      open: async (orientation) => {
        fake.calls.push(`cam.open:${orientation}`);
      },
      close: async () => {
        fake.calls.push("cam.close");
      },
      snapshot: async () => {
        fake.calls.push("cam.snapshot");
        return { width: 640, height: 480, mime: "image/jpeg" as const };
      },
    },
  };
  const speechDriver = (
    simulated: boolean,
    sink: SpeechHandlers[],
  ): SpeechDriver => ({
    simulated,
    available: () => {
      fake.calls.push(`${simulated ? "sim" : "speech"}.available`);
      return true;
    },
    speak: (text, handlers) => {
      fake.calls.push(`${simulated ? "sim" : "speech"}.speak`);
      sink.push(handlers);
    },
    stop: () => {
      fake.calls.push(`${simulated ? "sim" : "speech"}.stop`);
    },
  });
  fake.services = {
    capture,
    speech: speechDriver(false, fake.deviceSpeech),
    simulatedSpeech: speechDriver(true, fake.simulatedSpeech),
    renderPreview: (props) => (
      <View
        testID="fake-preview"
        accessibilityLabel={props.label}
        // Exposes the orientation to assertions without rendering a real camera.
        accessibilityHint={props.orientation}
      />
    ),
  };
  return fake;
}
