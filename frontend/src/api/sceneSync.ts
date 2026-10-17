/**
 * Commit one scene operation with resync-on-conflict.
 *
 * The outbox semantics live server-side (client-chosen operation id, idempotent replay).
 * The client side keeps its promise: identical retries reuse the same operation id, a
 * stale `expected_scene_revision` triggers exactly one resync + retry with the SAME id,
 * and a real conflict surfaces instead of silently duplicating a stroke.
 */

import { ApiClient, ApiClientError, type SceneActionRequest } from './client';
import type { SceneOperationResult, SceneSnapshot } from './contracts';

export type SceneSync = {
  snapshot(): Promise<SceneSnapshot>;
  commit(
    operationId: string,
    expectedRevision: number,
    action: SceneActionRequest,
  ): Promise<SceneOperationResult>;
};

export function makeSceneSync(client: ApiClient, sessionId: string): SceneSync {
  return {
    snapshot: () => client.sceneSnapshot(sessionId),
    commit: (operationId, expectedRevision, action) =>
      client.commitSceneOperation(sessionId, operationId, expectedRevision, action),
  };
}

export class SceneCommitError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'SceneCommitError';
  }
}

export type CommitOutcome = {
  result: SceneOperationResult;
  /** The snapshot after the commit, already resynced. */
  scene: SceneSnapshot;
};

export async function commitWithResync(
  sync: SceneSync,
  operationId: string,
  currentRevision: number,
  action: SceneActionRequest,
): Promise<CommitOutcome> {
  try {
    const result = await sync.commit(operationId, currentRevision, action);
    const scene = await sync.snapshot();
    return { result, scene };
  } catch (error) {
    if (error instanceof ApiClientError && error.code === 'revision_conflict') {
      // Resync once and retry with the SAME operation id; a second conflict is real.
      const fresh = await sync.snapshot();
      const result = await sync.commit(operationId, fresh.scene_revision, action);
      const scene = await sync.snapshot();
      return { result, scene };
    }
    if (error instanceof ApiClientError) {
      throw new SceneCommitError(error.code, error.message);
    }
    throw error;
  }
}
