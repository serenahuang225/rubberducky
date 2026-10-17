import { StrokeMachine } from './stroke';
import {
  handleInterruption,
  handlePointerCancel,
  handlePointerDown,
  handlePointerMove,
  handlePointerUp,
  type PointerDescriptor,
} from './pointerEvents';
import type { LogicalPoint } from './geometry';

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

function event(partial: Partial<PointerDescriptor>): PointerDescriptor {
  return {
    pointerId: 1,
    pointerType: 'mouse',
    button: 0,
    buttons: 1,
    isPrimary: true,
    x: 0,
    y: 0,
    ...partial,
  };
}

describe('web pointer normalization', () => {
  it('a primary mouse drag produces one stroke', () => {
    const { machine, commits } = setup();
    expect(handlePointerDown(machine, event({ x: 10, y: 10 }))).toBe('began');
    expect(handlePointerMove(machine, event({ x: 20, y: 20 }))).toBe('moved');
    expect(handlePointerUp(machine, event({ x: 20, y: 20 }))).toBe('ended');
    expect(commits).toEqual([[{ x: 10, y: 10 }, { x: 20, y: 20 }]]);
  });

  it('a primary press and release without motion produces a dot', () => {
    const { machine, commits } = setup();
    handlePointerDown(machine, event({ pointerType: 'pen', x: 300, y: 200 }));
    handlePointerUp(machine, event({ pointerType: 'pen', x: 300, y: 200, buttons: 0 }));
    expect(commits).toEqual([[{ x: 300, y: 200 }]]);
  });

  it('hover moves never draw', () => {
    const { machine, commits } = setup();
    expect(handlePointerMove(machine, event({ buttons: 0, x: 50, y: 50 }))).toBe('ignored');
    expect(handlePointerMove(machine, event({ pointerType: 'pen', buttons: 0, x: 60, y: 60 }))).toBe('ignored');
    expect(commits).toEqual([]);
    expect(machine.isActive()).toBe(false);
  });

  it('secondary and middle mouse buttons never start a stroke', () => {
    const { machine, commits } = setup();
    expect(handlePointerDown(machine, event({ button: 2, buttons: 2 }))).toBe('ignored');
    expect(handlePointerDown(machine, event({ button: 1, buttons: 4 }))).toBe('ignored');
    handlePointerMove(machine, event({ button: 2, buttons: 2, x: 100, y: 100 }));
    handlePointerUp(machine, event({ button: 2, buttons: 0 }));
    expect(commits).toEqual([]);
  });

  it('a second simultaneous pointer cannot splice into the active stroke', () => {
    const { machine, commits } = setup();
    handlePointerDown(machine, event({ pointerId: 1, pointerType: 'pen', x: 0, y: 0 }));
    // Palm/second finger landing mid-stroke.
    expect(
      handlePointerDown(machine, event({ pointerId: 2, pointerType: 'touch', isPrimary: false, x: 800, y: 800 })),
    ).toBe('ignored');
    handlePointerMove(machine, event({ pointerId: 2, pointerType: 'touch', isPrimary: false, x: 900, y: 900 }));
    handlePointerMove(machine, event({ pointerId: 1, pointerType: 'pen', x: 10, y: 10 }));
    handlePointerUp(machine, event({ pointerId: 2, pointerType: 'touch', isPrimary: false }));
    handlePointerUp(machine, event({ pointerId: 1, pointerType: 'pen' }));
    expect(commits).toEqual([[{ x: 0, y: 0 }, { x: 10, y: 10 }]]);
  });

  it('pointercancel discards the stroke with no commit and no stuck state', () => {
    const { machine, commits, cancels } = setup();
    handlePointerDown(machine, event({ x: 5, y: 5 }));
    handlePointerMove(machine, event({ x: 6, y: 6 }));
    expect(handlePointerCancel(machine, event({ buttons: 0 }))).toBe('cancelled');
    expect(commits).toEqual([]);
    expect(cancels()).toBe(1);
    expect(machine.isActive()).toBe(false);
  });

  it('lost capture / blur cancels instead of committing a partial line', () => {
    const { machine, commits, cancels } = setup();
    handlePointerDown(machine, event({ x: 5, y: 5 }));
    handlePointerMove(machine, event({ x: 6, y: 6 }));
    expect(handleInterruption(machine)).toBe('cancelled');
    expect(commits).toEqual([]);
    expect(cancels()).toBe(1);
    // A late up event after cancellation cannot connect a line to the next stroke.
    handlePointerUp(machine, event({ x: 200, y: 200 }));
    handlePointerDown(machine, event({ x: 300, y: 300 }));
    handlePointerUp(machine, event({ x: 300, y: 300 }));
    expect(commits).toEqual([[{ x: 300, y: 300 }]]);
  });

  it('touch contact draws the same ink as mouse', () => {
    const { machine, commits } = setup();
    handlePointerDown(machine, event({ pointerType: 'touch', x: 100, y: 100 }));
    handlePointerMove(machine, event({ pointerType: 'touch', x: 120, y: 140 }));
    handlePointerUp(machine, event({ pointerType: 'touch', x: 120, y: 140, buttons: 0 }));
    expect(commits).toEqual([[{ x: 100, y: 100 }, { x: 120, y: 140 }]]);
  });
});
