import type { LogicalPoint } from './geometry';
import { StrokeMachine } from './stroke';
import {
  handleTouchCancel,
  handleTouchEnd,
  handleTouchMove,
  handleTouchStart,
  type TouchSample,
} from './touchEvents';

function setup() {
  const commits: LogicalPoint[][] = [];
  let cancels = 0;
  const machine = new StrokeMachine({
    onPreview: () => undefined,
    onCommit: (points) => commits.push([...points]),
    onCancel: () => {
      cancels += 1;
    },
  });
  return { machine, commits, cancels: () => cancels };
}

const touch = (identifier: string, x: number, y: number): TouchSample => ({ identifier, x, y });

describe('native touch normalization', () => {
  it('a single finger drag commits one stroke', () => {
    const { machine, commits } = setup();
    expect(handleTouchStart(machine, [touch('1', 10, 10)])).toBe('began');
    expect(handleTouchMove(machine, [touch('1', 20, 20)])).toBe('moved');
    expect(handleTouchEnd(machine, [touch('1', 20, 20)])).toBe('ended');
    expect(commits).toEqual([[{ x: 10, y: 10 }, { x: 20, y: 20 }]]);
  });

  it('a tap commits a dot', () => {
    const { machine, commits } = setup();
    handleTouchStart(machine, [touch('1', 400, 400)]);
    handleTouchEnd(machine, [touch('1', 400, 400)]);
    expect(commits).toEqual([[{ x: 400, y: 400 }]]);
  });

  it('a second simultaneous contact (palm/finger) cannot join the stroke', () => {
    const { machine, commits } = setup();
    handleTouchStart(machine, [touch('1', 10, 10)]);
    // Palm lands: begin is refused, its moves are ignored.
    expect(handleTouchStart(machine, [touch('2', 700, 700)])).toBe('ignored');
    expect(handleTouchMove(machine, [touch('1', 20, 20), touch('2', 750, 750)])).toBe('moved');
    // Palm lifts first: the pen stroke continues untouched.
    expect(handleTouchEnd(machine, [touch('2', 750, 750)])).toBe('ignored');
    expect(handleTouchEnd(machine, [touch('1', 20, 20)])).toBe('ended');
    expect(commits).toEqual([[{ x: 10, y: 10 }, { x: 20, y: 20 }]]);
  });

  it('a cancelled gesture discards the stroke', () => {
    const { machine, commits, cancels } = setup();
    handleTouchStart(machine, [touch('1', 10, 10)]);
    handleTouchMove(machine, [touch('1', 30, 30)]);
    expect(handleTouchCancel(machine)).toBe('cancelled');
    expect(commits).toEqual([]);
    expect(cancels()).toBe(1);
    expect(machine.isActive()).toBe(false);
  });

  it('moves without an active stroke are ignored', () => {
    const { machine, commits } = setup();
    expect(handleTouchMove(machine, [touch('1', 10, 10)])).toBe('ignored');
    expect(handleTouchEnd(machine, [touch('1', 10, 10)])).toBe('ignored');
    expect(handleTouchCancel(machine)).toBe('ignored');
    expect(commits).toEqual([]);
  });
});
