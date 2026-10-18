import {
  BOARD_HEIGHT,
  BOARD_WIDTH,
  computeFitTransform,
  toLogical,
  toScreen,
  transformChanged,
} from './geometry';

describe('board geometry', () => {
  it('fits the board uniformly, starting at the top of the pane', () => {
    // Portrait-ish viewport: width-limited, extra height sits below the sheet.
    const portrait = computeFitTransform(800, 1000);
    expect(portrait.scale).toBeCloseTo(800 / BOARD_WIDTH);
    expect(portrait.offsetX).toBeCloseTo(0);
    expect(portrait.offsetY).toBeCloseTo(0);
    // Landscape-ish viewport: height-limited, extra width is centered.
    const landscape = computeFitTransform(1200, 600);
    expect(landscape.scale).toBeCloseTo(600 / BOARD_HEIGHT);
    expect(landscape.offsetX).toBeGreaterThan(0);
    expect(landscape.offsetY).toBeCloseTo(0);
  });

  it('round-trips logical coordinates through screen space', () => {
    const transform = computeFitTransform(820, 1180);
    const point = { x: 400, y: 300 };
    const screen = toScreen(transform, point);
    const logical = toLogical(transform, screen.x, screen.y);
    expect(logical).not.toBeNull();
    expect(logical!.x).toBeCloseTo(point.x, 5);
    expect(logical!.y).toBeCloseTo(point.y, 5);
  });

  it('keeps stored logical geometry identical across portrait/landscape resizes', () => {
    // The durable point is logical; only the view transform changes on resize.
    const durablePoint = { x: 1234, y: 567 };
    const before = computeFitTransform(820, 1180);
    const after = computeFitTransform(1180, 820);
    expect(transformChanged(before, after)).toBe(true);
    const screenBefore = toScreen(before, durablePoint);
    const screenAfter = toScreen(after, durablePoint);
    const drawnBefore = toLogical(before, screenBefore.x, screenBefore.y);
    const drawnAfter = toLogical(after, screenAfter.x, screenAfter.y);
    expect(drawnBefore).toEqual(drawnAfter);
  });

  it('rejects non-finite screen coordinates instead of producing NaN ink', () => {
    const transform = computeFitTransform(800, 600);
    expect(toLogical(transform, Number.NaN, 10)).toBeNull();
    expect(toLogical(transform, 10, Number.POSITIVE_INFINITY)).toBeNull();
    expect(toLogical({ ...transform, scale: 0 }, 10, 10)).toBeNull();
  });

  it('clamps points dragged past the board edge into the board', () => {
    const transform = computeFitTransform(800, 600);
    const point = toLogical(transform, -500, 9999);
    expect(point).toEqual({ x: 0, y: BOARD_HEIGHT });
  });

  it('treats degenerate viewports safely', () => {
    const transform = computeFitTransform(0, 0);
    expect(transform.scale).toBeGreaterThan(0);
  });
});
