import { MAX_PATH_POINTS, type LogicalPoint } from './geometry';
import { StrokeMachine } from './stroke';

function recorder() {
  const previews: LogicalPoint[][] = [];
  const commits: LogicalPoint[][] = [];
  let cancels = 0;
  const machine = new StrokeMachine({
    onPreview: (points) => previews.push([...points]),
    onCommit: (points) => commits.push([...points]),
    onCancel: () => {
      cancels += 1;
    },
  });
  return { machine, previews, commits, cancels: () => cancels };
}

describe('StrokeMachine', () => {
  it('collects a drag stroke and commits it once on end', () => {
    const { machine, commits, previews } = recorder();
    expect(machine.begin('a', { x: 1, y: 1 })).toBe(true);
    machine.move('a', { x: 5, y: 5 });
    machine.move('a', { x: 9, y: 5 });
    machine.end('a');
    expect(commits).toEqual([[{ x: 1, y: 1 }, { x: 5, y: 5 }, { x: 9, y: 5 }]]);
    expect(previews.length).toBe(3);
    expect(machine.isActive()).toBe(false);
  });

  it('commits a single-point tap as a dot stroke', () => {
    const { machine, commits } = recorder();
    machine.begin('a', { x: 42, y: 24 });
    machine.end('a');
    expect(commits).toEqual([[{ x: 42, y: 24 }]]);
  });

  it('refuses a second pointer while one stroke is active (no splicing)', () => {
    const { machine, commits } = recorder();
    expect(machine.begin('pen', { x: 0, y: 0 })).toBe(true);
    expect(machine.begin('palm', { x: 500, y: 500 })).toBe(false);
    machine.move('palm', { x: 900, y: 900 });
    machine.move('pen', { x: 10, y: 10 });
    machine.end('palm'); // unknown pointer: no commit
    machine.end('pen');
    expect(commits).toEqual([[{ x: 0, y: 0 }, { x: 10, y: 10 }]]);
  });

  it('ignores moves and ends from pointers that do not own the stroke', () => {
    const { machine, commits } = recorder();
    machine.begin('a', { x: 1, y: 1 });
    machine.move('b', { x: 100, y: 100 });
    machine.end('b');
    machine.end('a');
    expect(commits).toEqual([[{ x: 1, y: 1 }]]);
  });

  it('never admits non-finite points into a stroke', () => {
    const { machine, commits } = recorder();
    expect(machine.begin('a', { x: Number.NaN, y: 0 })).toBe(false);
    machine.begin('a', { x: 1, y: 1 });
    machine.move('a', { x: Number.POSITIVE_INFINITY, y: 2 });
    machine.move('a', { x: 2, y: 2 });
    machine.end('a');
    expect(commits).toEqual([[{ x: 1, y: 1 }, { x: 2, y: 2 }]]);
  });

  it('cancel discards the stroke without committing', () => {
    const { machine, commits, cancels } = recorder();
    machine.begin('a', { x: 1, y: 1 });
    machine.move('a', { x: 2, y: 2 });
    machine.cancel();
    expect(cancels()).toBe(1);
    expect(commits).toEqual([]);
    expect(machine.isActive()).toBe(false);
    machine.end('a'); // stale end after cancel: nothing happens
    expect(commits).toEqual([]);
  });

  it('caps a stroke at the server point limit without failing', () => {
    const { machine, commits } = recorder();
    machine.begin('a', { x: 0, y: 0 });
    for (let index = 1; index < MAX_PATH_POINTS + 50; index += 1) {
      machine.move('a', { x: index % 1600, y: index % 50 });
    }
    machine.end('a');
    expect(commits[0].length).toBe(MAX_PATH_POINTS);
  });

  it('a new stroke can begin immediately after a commit', () => {
    const { machine, commits } = recorder();
    machine.begin('a', { x: 1, y: 1 });
    machine.end('a');
    machine.begin('a', { x: 50, y: 50 });
    machine.move('a', { x: 60, y: 60 });
    machine.end('a');
    expect(commits).toEqual([[{ x: 1, y: 1 }], [{ x: 50, y: 50 }, { x: 60, y: 60 }]]);
  });
});
