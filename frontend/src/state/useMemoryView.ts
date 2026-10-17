/**
 * Private memory view state: inspection (bounded per bucket), corrections, deletions and
 * session/profile removal. Every change goes through the server's own routes; after each one
 * the view is re-read so derived updates (withdrawn beliefs, recomputed estimates) are shown
 * from the server, never guessed. Mutations are serialized so two taps cannot interleave.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiClient } from "../api/client";
import type { MemoryInspection, MemoryItem, Session } from "../api/contracts";

import {
  summarizeCorrection,
  summarizeDeletion,
  summarizeRemoval,
  type ChangeSummary,
} from "./memoryEffects";

export const DEFAULT_ITEM_LIMIT = 20;
/** The server's maximum per bucket (five buckets, so at most five times this many items). */
export const MAX_ITEM_LIMIT = 50;

export type MemoryView = {
  phase: "loading" | "ready" | "failed";
  inspection: MemoryInspection | null;
  sessions: Session[];
  limit: number;
  canShowMore: boolean;
  error: string | null;
  lastChange: ChangeSummary | null;
  working: boolean;
  reload: () => Promise<void>;
  showMore: () => void;
  correctEvidence: (item: MemoryItem, correct: boolean) => Promise<boolean>;
  correctNote: (item: MemoryItem, content: string) => Promise<boolean>;
  deleteItem: (item: MemoryItem) => Promise<boolean>;
  deleteSession: (sessionId: string) => Promise<boolean>;
  deleteProfile: () => Promise<ChangeSummary | null>;
};

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function useMemoryView(client: ApiClient): MemoryView {
  const [phase, setPhase] = useState<MemoryView["phase"]>("loading");
  const [inspection, setInspection] = useState<MemoryInspection | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [limit, setLimit] = useState(DEFAULT_ITEM_LIMIT);
  const [error, setError] = useState<string | null>(null);
  const [lastChange, setLastChange] = useState<ChangeSummary | null>(null);
  const [working, setWorking] = useState(false);
  const workingRef = useRef(false);
  const epochRef = useRef(0);
  const limitRef = useRef(limit);
  useEffect(() => {
    limitRef.current = limit;
  }, [limit]);

  const load = useCallback(
    async (nextLimit: number) => {
      const epoch = epochRef.current;
      try {
        const [view, list] = await Promise.all([
          client.inspectMemory({ limit: nextLimit }),
          client.listSessions(),
        ]);
        if (epoch !== epochRef.current) return;
        setInspection(view);
        setSessions(list);
        setError(null);
        setPhase("ready");
      } catch (failure) {
        if (epoch !== epochRef.current) return;
        setError(
          `Your memory could not be loaded: ${messageOf(failure, "the tutor is unreachable")}`,
        );
        setPhase((current) => (current === "ready" ? "ready" : "failed"));
      }
    },
    [client],
  );

  useEffect(() => {
    epochRef.current += 1;
    void load(limitRef.current);
    return () => {
      epochRef.current += 1;
      setPhase("loading");
    };
  }, [load]);

  const reload = useCallback(() => load(limitRef.current), [load]);

  const showMore = useCallback(() => {
    setLimit(MAX_ITEM_LIMIT);
    void load(MAX_ITEM_LIMIT);
  }, [load]);

  /** Run one change at a time; true when the server accepted it. */
  const mutate = useCallback(
    async (
      run: () => Promise<ChangeSummary>,
      failure: string,
      reloadAfter = true,
    ): Promise<boolean> => {
      if (workingRef.current) return false;
      workingRef.current = true;
      setWorking(true);
      setError(null);
      try {
        const summary = await run();
        setLastChange(summary);
        if (reloadAfter) await load(limitRef.current);
        return true;
      } catch (caught) {
        setError(
          `${failure} ${messageOf(caught, "The tutor is unreachable.")}`,
        );
        return false;
      } finally {
        workingRef.current = false;
        setWorking(false);
      }
    },
    [load],
  );

  const correctEvidence = useCallback(
    (item: MemoryItem, correct: boolean) =>
      mutate(
        async () =>
          summarizeCorrection(await client.correctEvidence(item.id, correct)),
        "That correction was not saved.",
      ),
    [client, mutate],
  );

  const correctNote = useCallback(
    (item: MemoryItem, content: string) =>
      mutate(
        async () =>
          summarizeCorrection(await client.correctNote(item.id, content)),
        "That correction was not saved.",
      ),
    [client, mutate],
  );

  const deleteItem = useCallback(
    (item: MemoryItem) =>
      mutate(async () => {
        const receipt =
          item.kind === "evidence"
            ? await client.deleteEvidence(item.id)
            : item.kind === "hypothesis"
              ? await client.deleteHypothesis(item.id)
              : await client.deleteNote(item.id);
        return summarizeDeletion(receipt);
      }, "That deletion did not happen."),
    [client, mutate],
  );

  const deleteSession = useCallback(
    (sessionId: string) =>
      mutate(
        async () => summarizeRemoval(await client.deleteSession(sessionId)),
        "That session was not removed.",
      ),
    [client, mutate],
  );

  const deleteProfile = useCallback(async (): Promise<ChangeSummary | null> => {
    const result: { summary: ChangeSummary | null } = { summary: null };
    const accepted = await mutate(
      async () => {
        result.summary = summarizeRemoval(await client.deleteProfile());
        return result.summary;
      },
      "Your profile was not removed.",
      false,
    );
    return accepted ? result.summary : null;
  }, [client, mutate]);

  return {
    phase,
    inspection,
    sessions,
    limit,
    canShowMore: limit < MAX_ITEM_LIMIT,
    error,
    lastChange,
    working,
    reload,
    showMore,
    correctEvidence,
    correctNote,
    deleteItem,
    deleteSession,
    deleteProfile,
  };
}
