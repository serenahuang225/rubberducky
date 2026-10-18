/**
 * Logical board geometry shared by the native and web client.
 *
 * The board is a fixed logical coordinate space (1600 x 1200) owned by the server; every
 * committed stroke stores logical points. The client fits the board uniformly into its
 * measured viewport and converts screen pixels to logical coordinates only through these
 * functions, so resizing (portrait/landscape, window changes) never rewrites stored
 * geometry and new points always land where the learner intended.
 */

export const BOARD_WIDTH = 1600;
export const BOARD_HEIGHT = 1200;
export const PEN_WIDTH = 3;
/**
 * How student ink is drawn on the fitted board. The server still stores {@link PEN_WIDTH};
 * this only makes a finger or pencil readable once the 1600×1200 board is scaled into the view.
 */
export const STUDENT_INK_WIDTH = 12;
export const MAX_PATH_POINTS = 200;

export type LogicalPoint = { x: number; y: number };

/** Uniform scale plus centering offsets that map logical coordinates to screen pixels. */
export type ViewTransform = {
  scale: number;
  offsetX: number;
  offsetY: number;
  viewWidth: number;
  viewHeight: number;
};

export function isFiniteNumber(value: number): boolean {
  return typeof value === 'number' && Number.isFinite(value);
}

export function isFinitePoint(point: LogicalPoint): boolean {
  return isFiniteNumber(point.x) && isFiniteNumber(point.y);
}

/**
 * Fit the logical board into a measured viewport without distorting the aspect ratio.
 * The sheet starts at the top. Extra space below stays the paper color, so a tall
 * pane does not float the writing between two bands.
 */
export function computeFitTransform(viewWidth: number, viewHeight: number): ViewTransform {
  const safeWidth = isFiniteNumber(viewWidth) && viewWidth > 0 ? viewWidth : 1;
  const safeHeight = isFiniteNumber(viewHeight) && viewHeight > 0 ? viewHeight : 1;
  const scale = Math.min(safeWidth / BOARD_WIDTH, safeHeight / BOARD_HEIGHT);
  return {
    scale,
    offsetX: (safeWidth - BOARD_WIDTH * scale) / 2,
    offsetY: 0,
    viewWidth: safeWidth,
    viewHeight: safeHeight,
  };
}

/** True when two transforms would map the same logical point to different pixels. */
export function transformChanged(a: ViewTransform, b: ViewTransform): boolean {
  return (
    Math.abs(a.scale - b.scale) > 0.0001 ||
    Math.abs(a.offsetX - b.offsetX) > 0.5 ||
    Math.abs(a.offsetY - b.offsetY) > 0.5
  );
}

/** Screen pixels to logical board coordinates, clamped inside the board. */
export function toLogical(transform: ViewTransform, x: number, y: number): LogicalPoint | null {
  if (!isFiniteNumber(x) || !isFiniteNumber(y) || transform.scale <= 0) {
    return null;
  }
  const logicalX = (x - transform.offsetX) / transform.scale;
  const logicalY = (y - transform.offsetY) / transform.scale;
  if (!isFiniteNumber(logicalX) || !isFiniteNumber(logicalY)) {
    return null;
  }
  return {
    x: Math.min(BOARD_WIDTH, Math.max(0, logicalX)),
    y: Math.min(BOARD_HEIGHT, Math.max(0, logicalY)),
  };
}

/** Logical board coordinates to screen pixels. */
export function toScreen(transform: ViewTransform, point: LogicalPoint): LogicalPoint {
  return {
    x: point.x * transform.scale + transform.offsetX,
    y: point.y * transform.scale + transform.offsetY,
  };
}
