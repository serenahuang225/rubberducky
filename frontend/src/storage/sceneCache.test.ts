import AsyncStorage from '@react-native-async-storage/async-storage';

import type { SceneSnapshot } from '../api/contracts';

import { loadCachedScene, saveCachedScene } from './sceneCache';

function scene(revision: number): SceneSnapshot {
  return {
    schema_version: 'scene-snapshot.v1',
    session_id: 'session-a',
    scene_revision: revision,
    board_width: 1600,
    board_height: 1200,
    pen_width: 3,
    objects: [
      {
        schema_version: 'scene-object.v1',
        id: 'obj-1',
        learner_id: 'learner-a',
        session_id: 'session-a',
        author_role: 'student',
        semantic_role: 'work',
        kind: 'path',
        payload: { points: [{ x: 1, y: 2 }, { x: 3, y: 4 }], width: 3, color_role: 'student' },
        teaching_step_id: null,
        created_at: '2026-10-17T00:00:00.000Z',
        deleted_at: null,
      },
    ],
    student_undo_available: true,
    student_redo_available: false,
    tutor_move_undo_available: false,
  };
}

beforeEach(async () => {
  await AsyncStorage.clear();
});

describe('scene cache', () => {
  it('round-trips the latest committed snapshot', async () => {
    await saveCachedScene(scene(7));
    const cached = await loadCachedScene('session-a');
    expect(cached?.scene_revision).toBe(7);
    expect(cached?.objects).toHaveLength(1);
  });

  it('returns null when nothing is cached', async () => {
    expect(await loadCachedScene('session-a')).toBeNull();
  });

  it('reads corrupt JSON as missing instead of painting bogus objects', async () => {
    await AsyncStorage.setItem('rubberducky.scene-cache.v1.session-a', 'not json');
    expect(await loadCachedScene('session-a')).toBeNull();
  });

  it('rejects a snapshot that fails the versioned contract', async () => {
    await AsyncStorage.setItem(
      'rubberducky.scene-cache.v1.session-a',
      JSON.stringify({ schema_version: 'scene-snapshot.v0', objects: 'oops' }),
    );
    expect(await loadCachedScene('session-a')).toBeNull();
  });

  it('never serves another session\'s cached scene', async () => {
    await saveCachedScene(scene(3));
    expect(await loadCachedScene('session-b')).toBeNull();
  });
});
