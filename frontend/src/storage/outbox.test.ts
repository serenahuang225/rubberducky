import AsyncStorage from '@react-native-async-storage/async-storage';

import {
  clearPendingOperations,
  enqueueOperation,
  loadPendingOperations,
  removeOperation,
  type PendingSceneOperation,
} from './outbox';

const stroke = (x: number): PendingSceneOperation => ({
  operationId: `op-${x}`,
  sessionId: 'session-a',
  queuedAt: '2026-10-17T00:00:00.000Z',
  action: { op: 'add_stroke', points: [{ x, y: x }] },
});

beforeEach(async () => {
  await AsyncStorage.clear();
});

describe('scene outbox', () => {
  it('round-trips queued operations oldest first', async () => {
    await enqueueOperation(stroke(1));
    await enqueueOperation(stroke(2));
    const loaded = await loadPendingOperations('session-a');
    expect(loaded.map((entry) => entry.operationId)).toEqual(['op-1', 'op-2']);
    expect(loaded[0].action).toEqual({ op: 'add_stroke', points: [{ x: 1, y: 1 }] });
  });

  it('survives a simulated reload (fresh read from storage)', async () => {
    await enqueueOperation(stroke(1));
    // A reload is exactly a fresh read: no in-memory state is involved.
    expect((await loadPendingOperations('session-a')).map((e) => e.operationId)).toEqual(['op-1']);
  });

  it('never queues the same operation id twice', async () => {
    await enqueueOperation(stroke(1));
    const again = await enqueueOperation(stroke(1));
    expect(again).toHaveLength(1);
    expect(await loadPendingOperations('session-a')).toHaveLength(1);
  });

  it('removes only the acknowledged operation', async () => {
    await enqueueOperation(stroke(1));
    await enqueueOperation(stroke(2));
    const remaining = await removeOperation('session-a', 'op-1');
    expect(remaining.map((entry) => entry.operationId)).toEqual(['op-2']);
    expect((await loadPendingOperations('session-a')).map((e) => e.operationId)).toEqual(['op-2']);
  });

  it('clears the storage key when the last operation is acknowledged', async () => {
    await enqueueOperation(stroke(1));
    await removeOperation('session-a', 'op-1');
    expect(await AsyncStorage.getItem('rubberducky.outbox.v1.session-a')).toBeNull();
  });

  it('keeps sessions isolated', async () => {
    await enqueueOperation(stroke(1));
    await enqueueOperation({ ...stroke(2), sessionId: 'session-b' });
    expect(await loadPendingOperations('session-a')).toHaveLength(1);
    expect(await loadPendingOperations('session-b')).toHaveLength(1);
  });

  it('reads corrupt JSON as an empty queue instead of crashing', async () => {
    await AsyncStorage.setItem('rubberducky.outbox.v1.session-a', '{not json');
    expect(await loadPendingOperations('session-a')).toEqual([]);
  });

  it('drops malformed entries and foreign sessions from a hand-edited queue', async () => {
    await AsyncStorage.setItem(
      'rubberducky.outbox.v1.session-a',
      JSON.stringify([
        stroke(1),
        { operationId: 'bad' },
        { ...stroke(9), action: { op: 'teleport' } },
        { ...stroke(3), sessionId: 'session-b' },
      ]),
    );
    expect((await loadPendingOperations('session-a')).map((e) => e.operationId)).toEqual(['op-1']);
  });

  it('clearPendingOperations empties the queue', async () => {
    await enqueueOperation(stroke(1));
    await clearPendingOperations('session-a');
    expect(await loadPendingOperations('session-a')).toEqual([]);
  });
});
