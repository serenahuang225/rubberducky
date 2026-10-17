/**
 * Wait agency: the learner's thinking time, kept honest.
 *
 * Silence is missing evidence, never a signal. When the server's quiet period ends this
 * hook only flips `hintAvailable` so an optional hint can be offered quietly. It never
 * requests help, submits work, speaks, diagnoses or posts anything on a timer. The one POST
 * it can make is the learner's explicit "Still thinking" press, which is wait metadata
 * only and is never replayed automatically (the server counts each press).
 *
 * Timing uses the server's own timestamps (`quiet_hint_at - now`), so a skewed device clock
 * cannot make a hint appear early or late. Every response is guarded by a session epoch and a
 * request sequence, so a late reply from another session or a superseded request is dropped,
 * and the timer is cleared on session change and unmount.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import type { ApiClient } from '../api/client';
import type { WaitPreference, WaitState } from '../api/contracts';

export type StillThinkingStatus = 'idle' | 'sent' | 'failed';

export type WaitAgencyOptions = {
  /** Only wait once a problem is posed in an active session. */
  enabled: boolean;
  /** Changes whenever real activity (a turn or a stroke) happened, to re-read server state. */
  activityKey: string;
};

export type WaitAgency = {
  preference: WaitPreference | null;
  waitState: WaitState | null;
  hintAvailable: boolean;
  stillThinkingStatus: StillThinkingStatus;
  preferenceError: string | null;
  setWaitSeconds: (seconds: number) => Promise<void>;
  stillThinking: () => Promise<void>;
  clearStillThinkingNote: () => void;
};

function delayUntilQuietHint(state: WaitState): number {
  const delta = Date.parse(state.quiet_hint_at) - Date.parse(state.now);
  return Number.isFinite(delta) ? Math.max(0, delta) : 0;
}

type ForSession<T> = { sessionId: string; value: T };

export function useWaitAgency(
  client: ApiClient,
  sessionId: string,
  { enabled, activityKey }: WaitAgencyOptions,
): WaitAgency {
  const [preference, setPreference] = useState<WaitPreference | null>(null);
  // Per-session values carry their session id, so a session change shows none of the old.
  const [waitTagged, setWaitTagged] = useState<ForSession<WaitState> | null>(null);
  const [expiredFor, setExpiredFor] = useState<WaitState | null>(null);
  const [stillTagged, setStillTagged] = useState<ForSession<StillThinkingStatus> | null>(null);
  const [errorTagged, setErrorTagged] = useState<ForSession<string> | null>(null);
  const epochRef = useRef(0);
  const sequenceRef = useRef(0);
  const preferenceRef = useRef<WaitPreference | null>(null);

  // A new session (or unmount) invalidates every request still in flight.
  useEffect(() => {
    epochRef.current += 1;
    return () => {
      epochRef.current += 1;
    };
  }, [client, sessionId]);

  // The preference is the learner's own server-owned setting; read it once per session.
  useEffect(() => {
    if (!enabled) return;
    const epoch = epochRef.current;
    client
      .waitPreference()
      .then((next) => {
        if (epoch !== epochRef.current) return;
        preferenceRef.current = next;
        setPreference(next);
      })
      .catch(() => undefined);
  }, [client, sessionId, enabled]);

  /** Latest-started read wins; null when superseded, stale or unknowable. */
  const readWaitState = useCallback((): Promise<WaitState | null> => {
    const epoch = epochRef.current;
    const sequence = ++sequenceRef.current;
    return client
      .waitState(sessionId)
      .then((next) =>
        epoch === epochRef.current && sequence === sequenceRef.current ? next : null,
      )
      .catch(() => null);
  }, [client, sessionId]);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    void readWaitState().then((next) => {
      if (active && next !== null) setWaitTagged({ sessionId, value: next });
    });
    return () => {
      active = false;
    };
  }, [enabled, activityKey, readWaitState, sessionId]);

  const waitState = waitTagged !== null && waitTagged.sessionId === sessionId ? waitTagged.value : null;

  useEffect(() => {
    if (waitState === null || waitState.quiet_hint_available) return;
    const timer = setTimeout(() => setExpiredFor(waitState), delayUntilQuietHint(waitState));
    return () => clearTimeout(timer);
  }, [waitState]);

  const stillThinking = useCallback(async () => {
    const epoch = epochRef.current;
    const sequence = ++sequenceRef.current;
    try {
      const next = await client.stillThinking(sessionId);
      if (epoch !== epochRef.current) return;
      setStillTagged({ sessionId, value: 'sent' });
      if (sequence === sequenceRef.current) {
        setWaitTagged({ sessionId, value: next });
      }
    } catch {
      if (epoch === epochRef.current) {
        setStillTagged({ sessionId, value: 'failed' });
      }
    }
  }, [client, sessionId]);

  const setWaitSeconds = useCallback(
    async (seconds: number) => {
      const bounds = preferenceRef.current;
      if (bounds === null || !Number.isFinite(seconds)) return;
      const epoch = epochRef.current;
      const clamped = Math.min(bounds.max_seconds, Math.max(bounds.min_seconds, Math.round(seconds)));
      setErrorTagged(null);
      try {
        const saved = await client.putWaitPreference(clamped);
        if (epoch !== epochRef.current) return;
        preferenceRef.current = saved;
        setPreference(saved);
        const next = await readWaitState();
        if (next !== null) setWaitTagged({ sessionId, value: next });
      } catch {
        if (epoch === epochRef.current) {
          setErrorTagged({
            sessionId,
            value: 'The waiting time could not be saved, so it is unchanged.',
          });
        }
      }
    },
    [client, readWaitState, sessionId],
  );

  const clearStillThinkingNote = useCallback(() => setStillTagged(null), []);

  const hintAvailable =
    waitState !== null && (waitState.quiet_hint_available || expiredFor === waitState);

  return {
    preference,
    waitState,
    hintAvailable,
    stillThinkingStatus:
      stillTagged !== null && stillTagged.sessionId === sessionId ? stillTagged.value : 'idle',
    preferenceError:
      errorTagged !== null && errorTagged.sessionId === sessionId ? errorTagged.value : null,
    setWaitSeconds,
    stillThinking,
    clearStillThinkingNote,
  };
}
