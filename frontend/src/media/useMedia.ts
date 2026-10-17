/**
 * Media state for one workspace: explicit capture, spoken replies, captions and the labeled
 * simulated voice/photo events.
 *
 * Nothing starts on its own. Capture starts only from the start* actions. Spoken replies
 * start only when the learner picked a voice mode, sound is allowed and a reply commits in
 * the current scope. Speech belongs to a scope made of the session, turn generation, server
 * cancellation epoch and problem; new work, Stop, a new problem, a hidden board, muting or
 * unmount cancel it, and callbacks that arrive later are dropped by the speech controller.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { AppState } from "react-native";

import type { ApiClient } from "../api/client";
import { ApiClientError } from "../api/client";
import type {
  MediaCapabilities,
  MediaEventRequest,
  MediaEventResult,
  RecognitionCandidate,
} from "../api/contracts";
import { newId } from "../api/ids";
import type { MediaActivity } from "../state/avatarStatus";

import { CaptureController, type CaptureSnapshot } from "./captureController";
import type { CameraOrientation, CaptureKind } from "./captureTypes";
import { deriveMediaActivity } from "./mediaActivity";
import type { MediaServices } from "./mediaServices";
import {
  SpeechController,
  type SpeechCancelReason,
  type SpeechSnapshot,
} from "./speechController";
import {
  applyTranscriptResult,
  buildTranscriptEvent,
  VOICE_IDLE,
  type VoiceState,
} from "./voiceSession";

export type VoiceMode = "off" | "device" | "simulated";

export type MediaOutcome = {
  kind: "photo" | "weak_context";
  status: MediaEventResult["status"];
  simulated: boolean;
  message: string;
  candidates: readonly RecognitionCandidate[];
};

export type UseMediaInput = {
  client: ApiClient;
  sessionId: string;
  services: MediaServices;
  /** The learner's current turn generation, server epoch and problem. */
  generation: number;
  epoch: number | null;
  revision: number | null;
  attemptId: string | null;
  /** The committed reply that may be spoken. */
  reply: { turnId: string; text: string; epoch: number } | null;
  /** A tutor command (typed work, help, check-in) is running. */
  busy: boolean;
  soundAllowed: boolean;
  textOnly: boolean;
  /** Settings or memory covers the board. */
  boardHidden: boolean;
};

export type MediaController = {
  capture: CaptureSnapshot;
  speech: SpeechSnapshot;
  voice: VoiceState;
  voiceMode: VoiceMode;
  /** A simulated voice event is awaiting the server's answer; the next one waits for it. */
  voiceBusy: boolean;
  capabilities: MediaCapabilities | null;
  capabilitiesError: string | null;
  fixturesEnabled: boolean;
  transcriptionAvailable: boolean;
  activity: MediaActivity | null;
  outcome: MediaOutcome | null;
  notice: string | null;
  loadCapabilities: () => void;
  setVoiceMode: (mode: VoiceMode) => void;
  startMicrophone: () => void;
  startCamera: (orientation: CameraOrientation) => void;
  stopCapture: (kind: CaptureKind) => void;
  cameraFault: () => void;
  takePhoto: () => void;
  simulatePhoto: () => void;
  simulateWeakCue: () => void;
  nextVoiceEvent: () => void;
  resetVoice: () => void;
  cancelSpeech: (reason: SpeechCancelReason) => void;
  dismissOutcome: () => void;
  renderPreview: MediaServices["renderPreview"];
};

function describeFailure(error: unknown): string {
  if (error instanceof ApiClientError && error.status === 409) {
    return "The board moved on, so that media event was ignored. Nothing changed.";
  }
  if (error instanceof ApiClientError) return error.message;
  return "The tutor could not be reached, so that media event was not sent. Nothing changed.";
}

export function useMedia(input: UseMediaInput): MediaController {
  const {
    client,
    sessionId,
    services,
    generation,
    epoch,
    revision,
    attemptId,
    reply,
    busy,
    soundAllowed,
    textOnly,
    boardHidden,
  } = input;

  const [capture] = useState(() => new CaptureController(services.capture));
  const [speech] = useState(() => new SpeechController(services.speech));
  const captureSnapshot = useSyncExternalStore(
    capture.subscribe,
    capture.getSnapshot,
  );
  const speechSnapshot = useSyncExternalStore(
    speech.subscribe,
    speech.getSnapshot,
  );
  const [voiceMode, setVoiceModeState] = useState<VoiceMode>("off");
  const [voice, setVoice] = useState<VoiceState>(VOICE_IDLE);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [capabilities, setCapabilities] = useState<MediaCapabilities | null>(
    null,
  );
  const [capabilitiesError, setCapabilitiesError] = useState<string | null>(
    null,
  );
  const [outcome, setOutcome] = useState<MediaOutcome | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [mediaSession, setMediaSession] = useState(sessionId);
  if (mediaSession !== sessionId) {
    // Transcript and photo results belong to one session; a new one starts clean.
    setMediaSession(sessionId);
    setVoice(VOICE_IDLE);
    setOutcome(null);
    setNotice(null);
  }
  const capabilitiesRequested = useRef(false);
  const scopeRef = useRef({ sessionId, epoch, revision });
  const latest = useRef({ revision, epoch, capabilities });

  useEffect(() => {
    scopeRef.current = { sessionId, epoch, revision };
    latest.current = { revision, epoch, capabilities };
  });

  // Text-only blocks capture entirely; leaving it never turns anything back on by itself.
  useEffect(() => {
    void capture.setBlocked(textOnly);
  }, [capture, textOnly]);

  // Sound policy: muted/text-only or no voice chosen means the driver is never called.
  useEffect(() => {
    speech.setDriver(
      voiceMode === "simulated" ? services.simulatedSpeech : services.speech,
    );
    speech.setAllowed(soundAllowed && voiceMode !== "off");
  }, [speech, services, soundAllowed, voiceMode]);

  const scope = [sessionId, generation, epoch, attemptId].join("|");
  const prevParts = useRef({ sessionId, generation, attemptId });
  useEffect(() => {
    const prev = prevParts.current;
    if (prev.attemptId !== attemptId || prev.sessionId !== sessionId) {
      speech.cancel("new_problem");
    } else if (prev.generation !== generation) {
      speech.cancel("interrupt");
    }
    prevParts.current = { sessionId, generation, attemptId };
    speech.setScope(scope);
  }, [speech, scope, sessionId, generation, attemptId]);

  // New work (typed step, Help me, check-in) silences the reply it overtakes.
  useEffect(() => {
    if (busy) speech.cancel("new_work");
  }, [speech, busy]);

  useEffect(() => {
    if (boardHidden) {
      speech.cancel("board_hidden");
      void capture.stopAll("unfocus");
    }
  }, [speech, capture, boardHidden]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (next) => {
      if (next !== "active") {
        speech.cancel("board_hidden");
        void capture.stopAll("background");
      }
    });
    return () => subscription.remove();
  }, [speech, capture]);

  useEffect(
    () => () => {
      speech.cancel("unmount");
      void capture.stopAll("unmount");
    },
    [speech, capture],
  );

  // Speak a newly committed reply once, only if it still belongs to the current epoch. A reply
  // that was already on screen when the learner turned voice on is not read retroactively.
  const spokenRef = useRef<string | null>(reply?.turnId ?? null);
  const replyId = reply?.turnId ?? null;
  useEffect(() => {
    if (replyId === null || spokenRef.current === replyId) return;
    spokenRef.current = replyId;
    if (reply === null || (epoch !== null && reply.epoch < epoch)) return;
    if (voiceMode === "off") return;
    speech.speak({ turnId: reply.turnId, text: reply.text, scope });
    // Only a newly committed turn may start speech.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replyId]);

  const loadCapabilities = useCallback(() => {
    if (capabilitiesRequested.current) return;
    capabilitiesRequested.current = true;
    client
      .mediaCapabilities()
      .then((value) => {
        setCapabilities(value);
        setCapabilitiesError(null);
      })
      .catch(() => {
        capabilitiesRequested.current = false;
        setCapabilitiesError(
          "Media options could not be loaded. Typing and drawing still work.",
        );
      });
  }, [client]);

  const send = useCallback(
    async (event: MediaEventRequest): Promise<MediaEventResult | null> => {
      const { revision: rev, epoch: ep } = latest.current;
      if (rev === null || ep === null) {
        setNotice(
          "The board is still loading, so that media event was not sent.",
        );
        return null;
      }
      const target = scopeRef.current.sessionId;
      try {
        const result = await client.postMediaEvent(target, event, {
          revision: rev,
          epoch: ep,
        });
        // A result for a session the learner has since left must not change this screen.
        if (scopeRef.current.sessionId !== target) return null;
        setNotice(null);
        return result;
      } catch (error) {
        if (scopeRef.current.sessionId === target)
          setNotice(describeFailure(error));
        return null;
      }
    },
    [client],
  );

  const showOutcome = useCallback(
    (kind: MediaOutcome["kind"], result: MediaEventResult) => {
      setOutcome({
        kind,
        status: result.status,
        simulated: result.simulated,
        message: result.message,
        candidates: result.candidates,
      });
    },
    [],
  );

  const takePhoto = useCallback(() => {
    void (async () => {
      const frame = await capture.takeSnapshot();
      const orientation = capture.getSnapshot().camera.orientation;
      if (frame === null || orientation === null) {
        setNotice("The camera is not ready yet, so no photo was taken.");
        return;
      }
      const limit = latest.current.capabilities?.limits.max_image_edge;
      if (limit !== undefined && Math.max(frame.width, frame.height) > limit) {
        setNotice(
          `That photo is larger than the ${limit} px limit, so it was not sent. Typed work still works.`,
        );
        return;
      }
      const result = await send({
        kind: "image_snapshot",
        event_id: `mev-${newId()}`,
        source: "device",
        orientation,
        ...frame,
      });
      if (result !== null) showOutcome("photo", result);
    })();
  }, [capture, send, showOutcome]);

  const simulatePhoto = useCallback(() => {
    void (async () => {
      const result = await send({
        kind: "image_snapshot",
        event_id: `mev-${newId()}`,
        source: "simulated",
        orientation: "work_facing",
        mime: "image/jpeg",
        width: 640,
        height: 480,
      });
      if (result !== null) showOutcome("photo", result);
    })();
  }, [send, showOutcome]);

  const simulateWeakCue = useCallback(() => {
    void (async () => {
      const result = await send({
        kind: "weak_context",
        event_id: `mev-${newId()}`,
        source: "simulated",
        signal: "silence",
      });
      if (result !== null) showOutcome("weak_context", result);
    })();
  }, [send, showOutcome]);

  const voiceBusyRef = useRef(false);
  const voiceRef = useRef(voice);
  useEffect(() => {
    voiceRef.current = voice;
  }, [voice]);

  const nextVoiceEvent = useCallback(() => {
    if (voiceBusyRef.current) return;
    void (async () => {
      const before = voiceRef.current;
      const built = buildTranscriptEvent(before);
      if (built === null) return;
      voiceBusyRef.current = true;
      setVoiceBusy(true);
      const result = await send(built.request);
      voiceBusyRef.current = false;
      setVoiceBusy(false);
      if (result === null) return;
      // A reset or another event while this one was in flight makes its result stale.
      setVoice((current) =>
        current === before
          ? applyTranscriptResult(current, built.request, result)
          : current,
      );
    })();
  }, [send]);

  const resetVoice = useCallback(() => setVoice(VOICE_IDLE), []);

  const startMicrophone = useCallback(
    () => void capture.startMicrophone(),
    [capture],
  );
  const startCamera = useCallback(
    (orientation: CameraOrientation) => void capture.startCamera(orientation),
    [capture],
  );
  const stopCapture = useCallback(
    (kind: CaptureKind) => void capture.stop(kind, "user"),
    [capture],
  );
  const cameraFault = useCallback(() => void capture.fail("camera"), [capture]);
  const cancelSpeech = useCallback(
    (reason: SpeechCancelReason) => speech.cancel(reason),
    [speech],
  );
  const setVoiceMode = useCallback(
    (mode: VoiceMode) => {
      if (mode === "off") speech.cancel("user_stop");
      setVoiceModeState(mode);
    },
    [speech],
  );
  const dismissOutcome = useCallback(() => setOutcome(null), []);

  // Real transcription is never configured by this build, so a microphone that is on is not
  // reported as the tutor listening unless the server says a transcriber is available.
  const transcriptionAvailable =
    capabilities !== null && capabilities.transcription.status === "available";
  const activity = useMemo(
    () =>
      deriveMediaActivity({
        capture: captureSnapshot,
        speech: speechSnapshot,
        voice,
        transcriptionAvailable,
      }),
    [captureSnapshot, speechSnapshot, voice, transcriptionAvailable],
  );

  return {
    capture: captureSnapshot,
    speech: speechSnapshot,
    voice,
    voiceMode,
    voiceBusy,
    capabilities,
    capabilitiesError,
    fixturesEnabled: capabilities?.fixtures.enabled === true,
    transcriptionAvailable,
    activity,
    outcome,
    notice,
    loadCapabilities,
    setVoiceMode,
    startMicrophone,
    startCamera,
    stopCapture,
    cameraFault,
    takePhoto,
    simulatePhoto,
    simulateWeakCue,
    nextVoiceEvent,
    resetVoice,
    cancelSpeech,
    dismissOutcome,
    renderPreview: services.renderPreview,
  };
}
