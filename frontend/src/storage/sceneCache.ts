/**
 * Durable last-known scene snapshot cache.
 *
 * On reload or re-entry the workspace paints the cached committed scene immediately and
 * replaces it with the server's snapshot as soon as the fetch lands. The cache is a
 * read-through convenience only: the server scene is always authoritative, cached data
 * is validated against the versioned contract, and anything corrupt is ignored rather
 * than shown as if it were durable truth.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';

import { sceneSnapshotSchema, type SceneSnapshot } from '../api/contracts';

const cacheKey = (sessionId: string): string => `rubberducky.scene-cache.v1.${sessionId}`;

/** Load the cached snapshot for one session; corrupt or foreign data reads as missing. */
export async function loadCachedScene(sessionId: string): Promise<SceneSnapshot | null> {
  const raw = await AsyncStorage.getItem(cacheKey(sessionId));
  if (raw === null) {
    return null;
  }
  try {
    const parsed = sceneSnapshotSchema.safeParse(JSON.parse(raw));
    if (!parsed.success || parsed.data.session_id !== sessionId) {
      return null;
    }
    return parsed.data;
  } catch {
    return null;
  }
}

/** Persist the latest committed server snapshot (never an optimistic local guess). */
export async function saveCachedScene(scene: SceneSnapshot): Promise<void> {
  await AsyncStorage.setItem(cacheKey(scene.session_id), JSON.stringify(scene));
}

export async function clearCachedScene(sessionId: string): Promise<void> {
  await AsyncStorage.removeItem(cacheKey(sessionId));
}
