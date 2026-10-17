/**
 * Durable per-session scene outbox.
 *
 * A finished stroke that cannot reach the server (offline, server down, timeout) is
 * queued here with the operation id it was first given. The queue survives reloads and
 * app restarts; on reconnect the workspace retries each entry with the SAME operation
 * id, and the server's idempotent commit turns a retried-but-already-saved operation
 * into a replay instead of a duplicate. Nothing here ever marks unsaved work as saved.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';

import type { SceneActionRequest } from '../api/client';

export type PendingSceneOperation = {
  /** Stable client-chosen id; reused verbatim on every retry (server idempotency). */
  operationId: string;
  sessionId: string;
  /** ISO timestamp of the first failed save, for display/debugging. */
  queuedAt: string;
  action: SceneActionRequest;
};

const outboxKey = (sessionId: string): string => `rubberducky.outbox.v1.${sessionId}`;

const VALID_OPS = new Set(['add_stroke', 'erase_object', 'undo', 'redo', 'undo_tutor_move']);

function isValidAction(raw: unknown): raw is SceneActionRequest {
  if (typeof raw !== 'object' || raw === null) {
    return false;
  }
  const op = (raw as { op?: unknown }).op;
  return typeof op === 'string' && VALID_OPS.has(op);
}

function isValidEntry(raw: unknown): raw is PendingSceneOperation {
  if (typeof raw !== 'object' || raw === null) {
    return false;
  }
  const entry = raw as Record<string, unknown>;
  return (
    typeof entry.operationId === 'string' &&
    entry.operationId.length > 0 &&
    typeof entry.sessionId === 'string' &&
    entry.sessionId.length > 0 &&
    typeof entry.queuedAt === 'string' &&
    isValidAction(entry.action)
  );
}

/** Load the queued operations for one session, oldest first. Corrupt data reads as empty. */
export async function loadPendingOperations(sessionId: string): Promise<PendingSceneOperation[]> {
  const raw = await AsyncStorage.getItem(outboxKey(sessionId));
  if (raw === null) {
    return [];
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed
      .filter(isValidEntry)
      .filter((entry) => entry.sessionId === sessionId);
  } catch {
    return [];
  }
}

async function store(sessionId: string, entries: PendingSceneOperation[]): Promise<void> {
  if (entries.length === 0) {
    await AsyncStorage.removeItem(outboxKey(sessionId));
    return;
  }
  await AsyncStorage.setItem(outboxKey(sessionId), JSON.stringify(entries));
}

/**
 * Append an operation. Re-enqueueing an existing operation id is a no-op, so a crashed
 * enqueue-then-render cannot double-queue the same stroke.
 */
export async function enqueueOperation(
  operation: PendingSceneOperation,
): Promise<PendingSceneOperation[]> {
  const existing = await loadPendingOperations(operation.sessionId);
  if (existing.some((entry) => entry.operationId === operation.operationId)) {
    return existing;
  }
  const next = [...existing, operation];
  await store(operation.sessionId, next);
  return next;
}

/** Remove one operation after the server accepted (or replayed) it. */
export async function removeOperation(
  sessionId: string,
  operationId: string,
): Promise<PendingSceneOperation[]> {
  const existing = await loadPendingOperations(sessionId);
  const next = existing.filter((entry) => entry.operationId !== operationId);
  if (next.length !== existing.length) {
    await store(sessionId, next);
  }
  return next;
}

export async function clearPendingOperations(sessionId: string): Promise<void> {
  await AsyncStorage.removeItem(outboxKey(sessionId));
}
