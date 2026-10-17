import { pointsToPathData } from './pathData';

describe('pointsToPathData', () => {
  it('draws two points as a straight segment', () => {
    expect(pointsToPathData([{ x: 1, y: 2 }, { x: 4, y: 6 }])).toBe('M 1 2 L 4 6');
  });

  it('rounds corners of a longer stroke with quadratic segments', () => {
    const path = pointsToPathData([
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 10, y: 10 },
    ]);
    expect(path).toBe('M 0 0 Q 10 0 10 5 L 10 10');
  });

  it('returns null for a dot', () => {
    expect(pointsToPathData([{ x: 1, y: 1 }])).toBeNull();
  });
});
