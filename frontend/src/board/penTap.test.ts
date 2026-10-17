import { DOUBLE_TAP_MS, PenTapSwitch } from './penTap';

const dot = [{ x: 10, y: 20 }];
const nearby = [{ x: 40, y: 30 }];
const far = [{ x: 200, y: 20 }];
const stroke = [
  { x: 10, y: 20 },
  { x: 80, y: 90 },
];

describe('PenTapSwitch', () => {
  it('holds a single tap, then gives it back when the window closes', () => {
    const gate = new PenTapSwitch();
    expect(gate.note(dot, 0)).toEqual({ action: 'hold' });
    expect(gate.take()).toEqual(dot);
    expect(gate.take()).toBeNull();
  });

  it('treats two close taps as undo and keeps neither as ink', () => {
    const gate = new PenTapSwitch();
    gate.note(dot, 0);
    expect(gate.note(nearby, DOUBLE_TAP_MS)).toEqual({ action: 'undo' });
    expect(gate.take()).toBeNull();
  });

  it('commits a tap that is too far from the next one, and holds the next', () => {
    const gate = new PenTapSwitch();
    gate.note(dot, 0);
    expect(gate.note(far, 100)).toEqual({ action: 'commit-then-hold', held: dot });
  });

  it('commits a waiting tap when a real stroke starts', () => {
    const gate = new PenTapSwitch();
    gate.note(dot, 0);
    expect(gate.note(stroke, 50)).toEqual({ action: 'commit-held', held: dot });
  });

  it('commits a real stroke immediately when nothing is waiting', () => {
    const gate = new PenTapSwitch();
    expect(gate.note(stroke, 0)).toEqual({ action: 'commit' });
  });

  it('does not undo when the second tap arrives too late', () => {
    const gate = new PenTapSwitch();
    gate.note(dot, 0);
    expect(gate.note(nearby, DOUBLE_TAP_MS + 1)).toEqual({
      action: 'commit-then-hold',
      held: dot,
    });
  });
});
