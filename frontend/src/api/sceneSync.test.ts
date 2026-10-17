import { ApiClientError } from './client';
import { commitWithResync, type SceneSync } from './sceneSync';

function snapshotAt(revision: number) {
  return {
    schema_version: 'scene-snapshot.v1',
    session_id: 's1',
    scene_revision: revision,
    board_width: 1600,
    board_height: 1200,
    pen_width: 3,
    objects: [],
    student_undo_available: false,
    student_redo_available: false,
    tutor_move_undo_available: false,
  } as const;
}

function resultAt(revision: number, replayed = false) {
  return {
    schema_version: 'scene-operation-result.v1',
    operation_id: 'op-1',
    session_id: 's1',
    scene_revision: revision,
    kind: 'add_object',
    author_role: 'student',
    object_id: 'obj-1',
    affected_object_ids: ['obj-1'],
    replayed,
  } as const;
}

const stroke = { op: 'add_stroke' as const, points: [{ x: 1, y: 1 }, { x: 2, y: 2 }] };

describe('commitWithResync', () => {
  it('commits once at the expected revision and returns the fresh scene', async () => {
    const sync: SceneSync = {
      snapshot: jest.fn().mockResolvedValue(snapshotAt(1)),
      commit: jest.fn().mockResolvedValue(resultAt(1)),
    };
    const outcome = await commitWithResync(sync, 'op-1', 0, stroke);
    expect(outcome.result.scene_revision).toBe(1);
    expect(outcome.scene.scene_revision).toBe(1);
    expect(sync.commit).toHaveBeenCalledTimes(1);
  });

  it('on a stale revision it resyncs and retries once with the SAME operation id', async () => {
    const commit = jest
      .fn()
      .mockRejectedValueOnce(new ApiClientError(409, 'revision_conflict', 'stale'))
      .mockResolvedValueOnce(resultAt(5));
    const sync: SceneSync = {
      snapshot: jest
        .fn()
        .mockResolvedValueOnce(snapshotAt(4))
        .mockResolvedValueOnce(snapshotAt(5)),
      commit,
    };
    const outcome = await commitWithResync(sync, 'op-1', 0, stroke);
    expect(commit).toHaveBeenCalledTimes(2);
    expect(commit.mock.calls[0][0]).toBe('op-1');
    expect(commit.mock.calls[1][0]).toBe('op-1');
    expect(commit.mock.calls[1][1]).toBe(4);
    expect(outcome.result.scene_revision).toBe(5);
  });

  it('a replayed identical retry is accepted as the same single operation', async () => {
    const sync: SceneSync = {
      snapshot: jest.fn().mockResolvedValue(snapshotAt(1)),
      commit: jest.fn().mockResolvedValue(resultAt(1, true)),
    };
    const outcome = await commitWithResync(sync, 'op-1', 0, stroke);
    expect(outcome.result.replayed).toBe(true);
  });

  it('surfaces an idempotency conflict instead of duplicating', async () => {
    const sync: SceneSync = {
      snapshot: jest.fn(),
      commit: jest
        .fn()
        .mockRejectedValue(new ApiClientError(409, 'idempotency_conflict', 'different content')),
    };
    await expect(commitWithResync(sync, 'op-1', 0, stroke)).rejects.toMatchObject({
      name: 'SceneCommitError',
      code: 'idempotency_conflict',
    });
    expect(sync.commit).toHaveBeenCalledTimes(1);
  });
});
