import { act, renderHook } from '@testing-library/react-native';

import type { ApiClient } from '../api/client';
import type { SceneSnapshot } from '../api/contracts';

import { useBoardReading } from './useBoardReading';

const scene = { scene_revision: 2, objects: [{ author_role: 'student' }] } as SceneSnapshot;
function setup() {
  const readBoard = jest.fn().mockResolvedValue({ text: 'x = 4', legible: true, scene_revision: 2 });
  const onRead = jest.fn().mockResolvedValue('resolved');
  const props = { client: { readBoard } as unknown as ApiClient, sessionId: 's1', scene,
    revision: 1, attemptId: 'a1', blocked: false, onRead };
  return { props, readBoard, onRead };
}
const tick = async (ms: number) => { await act(async () => { jest.advanceTimersByTime(ms); }); };

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

it('waits for new ink to settle and does not repeatedly read the same board', async () => {
  const test = setup();
  const hook = renderHook(() => useBoardReading(test.props));
  await tick(10000);
  expect(test.readBoard).not.toHaveBeenCalled();
  act(() => hook.result.current.onInkActivity());
  await tick(3000);
  expect(test.readBoard).not.toHaveBeenCalled();
  act(() => hook.result.current.onInkActivity());
  await tick(3000);
  expect(test.readBoard).not.toHaveBeenCalled();
  await tick(4000);
  expect(test.onRead).toHaveBeenCalledWith('x = 4');
  await tick(10000);
  expect(test.readBoard).toHaveBeenCalledTimes(1);
});

it('shows uncertain handwriting without submitting it or filling the composer', async () => {
  const test = setup();
  test.readBoard.mockResolvedValue({ text: 'x = 9?', legible: false, scene_revision: 2 });
  const hook = renderHook(() => useBoardReading(test.props));
  act(() => hook.result.current.onInkActivity());
  await tick(7000);
  expect(hook.result.current.note).toContain('x = 9?');
  expect(test.onRead).not.toHaveBeenCalled();
});

it('discards a reading if more writing occurs while vision is running', async () => {
  const test = setup();
  let resolve!: (value: unknown) => void;
  test.readBoard.mockImplementation(() => new Promise((done) => { resolve = done; }));
  const hook = renderHook(() => useBoardReading(test.props));
  act(() => hook.result.current.onInkActivity());
  await tick(7000);
  act(() => hook.result.current.onInkActivity());
  await act(async () => { resolve({ text: 'old line', legible: true, scene_revision: 2 }); });
  expect(test.onRead).not.toHaveBeenCalled();
});


it('reads new writing after an uncertain partial expression', async () => {
  const test = setup();
  test.readBoard.mockResolvedValueOnce({ text: 'x =', legible: false, scene_revision: 2 });
  const hook = renderHook(() => useBoardReading(test.props));
  act(() => hook.result.current.onInkActivity());
  await tick(7000);
  expect(test.onRead).not.toHaveBeenCalled();
  act(() => hook.result.current.onInkActivity());
  await tick(7000);
  expect(test.onRead).toHaveBeenCalledWith('x = 4');
  expect(test.readBoard).toHaveBeenCalledTimes(2);
});


it('checks a boxed answer even when its text was already read as work', async () => {
  const test = setup();
  const hook = renderHook(() => useBoardReading(test.props));
  act(() => hook.result.current.onInkActivity());
  await tick(7000);
  test.readBoard.mockResolvedValue({ text: 'x = 4', legible: true, scene_revision: 2, boxed_answer: true });
  act(() => hook.result.current.onInkActivity());
  await tick(7000);
  expect(test.onRead).toHaveBeenLastCalledWith('x = 4', true);
});

it('explicit Check answer reads immediately and requests independent verification', async () => {
  const test = setup();
  const hook = renderHook(() => useBoardReading(test.props));
  act(() => hook.result.current.checkAnswer());
  await tick(750);
  expect(test.readBoard).toHaveBeenCalledWith('s1', 2, true);
  expect(test.onRead).toHaveBeenCalledWith('x = 4', true);
});
