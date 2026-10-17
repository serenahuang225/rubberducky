/**
 * The learner's persona state and accessibility preferences, owned above the workspace so
 * the board, avatar and settings screen all read one copy.
 *
 * Authority stays on the server: lock state and every UTC instant come from the persona
 * routes and nothing here compares them with the device clock. Comfort and accessibility edits
 * use their own routes, show at once, and are reconciled with the server's response. A slower
 * response from an older edit never overwrites a newer choice, and a refused edit rolls back.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiClient, ApiClientError } from "../api/client";
import type {
  AccessibilityPatch,
  AccessibilityPreferences,
  Appearance,
  ComfortOverride,
  PersonaState,
  Personality,
} from "../api/contracts";

export const DEFAULT_ACCESSIBILITY: AccessibilityPreferences = {
  schema_version: "accessibility-preferences.v1",
  animation: "system",
  sound_enabled: true,
  haptics_enabled: true,
  text_only: false,
  captions_enabled: true,
  updated_at: null,
};

export type PairChangeOutcome = "saved" | "unchanged" | "locked" | "failed";

export type LearnerSettings = {
  persona: PersonaState | null;
  accessibility: AccessibilityPreferences;
  loaded: boolean;
  loadError: string | null;
  comfortError: string | null;
  accessibilityError: string | null;
  pairError: string | null;
  savingPair: boolean;
  /** Re-read the server's lock state (for example whenever settings opens). */
  refresh: () => Promise<void>;
  setComfort: (value: ComfortOverride) => Promise<void>;
  patchAccessibility: (patch: AccessibilityPatch) => Promise<void>;
  changePair: (
    appearance: Appearance,
    personality: Personality,
  ) => Promise<PairChangeOutcome>;
};

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function useLearnerSettings(client: ApiClient | null): LearnerSettings {
  const [persona, setPersona] = useState<PersonaState | null>(null);
  const [accessibility, setAccessibility] = useState<AccessibilityPreferences>(
    DEFAULT_ACCESSIBILITY,
  );
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [comfortError, setComfortError] = useState<string | null>(null);
  const [accessibilityError, setAccessibilityError] = useState<string | null>(
    null,
  );
  const [pairError, setPairError] = useState<string | null>(null);
  const [savingPair, setSavingPair] = useState(false);
  const clientEpochRef = useRef(0);
  const personaRef = useRef<PersonaState | null>(null);
  const confirmedAccessibilityRef = useRef<AccessibilityPreferences>(
    DEFAULT_ACCESSIBILITY,
  );
  const accessibilityRef = useRef<AccessibilityPreferences>(
    DEFAULT_ACCESSIBILITY,
  );
  const accessibilitySeqRef = useRef(0);
  const comfortSeqRef = useRef(0);

  const storePersona = useCallback((next: PersonaState | null) => {
    personaRef.current = next;
    setPersona(next);
  }, []);
  const storeAccessibility = useCallback((next: AccessibilityPreferences) => {
    accessibilityRef.current = next;
    setAccessibility(next);
  }, []);

  const refresh = useCallback(async () => {
    if (client === null) return;
    const epoch = clientEpochRef.current;
    try {
      const [state, prefs] = await Promise.all([
        client.getTutorConfiguration(),
        client.getAccessibilityPreferences(),
      ]);
      if (epoch !== clientEpochRef.current) return;
      personaRef.current = state;
      setPersona(state);
      // Never replace an edit that is still being saved.
      if (confirmedAccessibilityRef.current === accessibilityRef.current) {
        confirmedAccessibilityRef.current = prefs;
        accessibilityRef.current = prefs;
        setAccessibility(prefs);
      }
      setLoadError(null);
      setLoaded(true);
    } catch (error) {
      if (epoch !== clientEpochRef.current) return;
      setLoadError(
        `Your saved settings could not be loaded (${messageOf(error, "the tutor is unreachable")}). Defaults are shown until they can be.`,
      );
      setLoaded(true);
    }
  }, [client]);

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => (active ? refresh() : undefined));
    // Leaving a client (sign-out, profile deletion, a new credential) drops everything read
    // through it and rejects any response still in flight for it.
    return () => {
      active = false;
      clientEpochRef.current += 1;
      storePersona(null);
      confirmedAccessibilityRef.current = DEFAULT_ACCESSIBILITY;
      storeAccessibility(DEFAULT_ACCESSIBILITY);
      accessibilitySeqRef.current = 0;
      comfortSeqRef.current = 0;
      setLoaded(false);
      setLoadError(null);
      setComfortError(null);
      setAccessibilityError(null);
      setPairError(null);
    };
  }, [refresh, storeAccessibility, storePersona]);

  const setComfort = useCallback(
    async (value: ComfortOverride) => {
      const current = personaRef.current;
      if (client === null || current === null) return;
      const epoch = clientEpochRef.current;
      const seq = ++comfortSeqRef.current;
      setComfortError(null);
      storePersona({ ...current, comfort_override: value });
      try {
        const next = await client.putComfortOverride(value);
        if (epoch !== clientEpochRef.current || seq !== comfortSeqRef.current)
          return;
        storePersona(next);
      } catch (error) {
        if (epoch !== clientEpochRef.current) return;
        setComfortError(
          `Comfort could not be changed: ${messageOf(error, "the tutor is unreachable")}`,
        );
        if (seq === comfortSeqRef.current) storePersona(current);
      }
    },
    [client, storePersona],
  );

  const patchAccessibility = useCallback(
    async (patch: AccessibilityPatch) => {
      if (client === null) return;
      const epoch = clientEpochRef.current;
      const seq = ++accessibilitySeqRef.current;
      setAccessibilityError(null);
      storeAccessibility({ ...accessibilityRef.current, ...patch });
      try {
        const next = await client.patchAccessibilityPreferences(patch);
        if (
          epoch !== clientEpochRef.current ||
          seq !== accessibilitySeqRef.current
        )
          return;
        confirmedAccessibilityRef.current = next;
        storeAccessibility(next);
      } catch (error) {
        if (epoch !== clientEpochRef.current) return;
        setAccessibilityError(
          `That setting could not be saved: ${messageOf(error, "the tutor is unreachable")}`,
        );
        if (seq === accessibilitySeqRef.current) {
          storeAccessibility(confirmedAccessibilityRef.current);
        }
      }
    },
    [client, storeAccessibility],
  );

  const changePair = useCallback(
    async (
      appearance: Appearance,
      personality: Personality,
    ): Promise<PairChangeOutcome> => {
      if (client === null) return "failed";
      const epoch = clientEpochRef.current;
      setPairError(null);
      setSavingPair(true);
      try {
        const next = await client.putTutorConfiguration(
          appearance,
          personality,
        );
        if (epoch !== clientEpochRef.current) return "failed";
        storePersona(next);
        return next.outcome === "no_change" ? "unchanged" : "saved";
      } catch (error) {
        if (epoch !== clientEpochRef.current) return "failed";
        setPairError(messageOf(error, "The change could not be saved."));
        if (
          error instanceof ApiClientError &&
          error.code === "persona_change_locked"
        ) {
          // Re-read so the explanation shows the server's own instant.
          await refresh();
          return "locked";
        }
        return "failed";
      } finally {
        if (epoch === clientEpochRef.current) setSavingPair(false);
      }
    },
    [client, refresh, storePersona],
  );

  return {
    persona,
    accessibility,
    loaded,
    loadError,
    comfortError,
    accessibilityError,
    pairError,
    savingPair,
    refresh,
    setComfort,
    patchAccessibility,
    changePair,
  };
}
