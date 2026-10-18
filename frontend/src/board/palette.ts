/**
 * The session palette is three colors: white, blue, and yellow.
 *
 * Scene objects store a color *role* (never a free color), so re-entry always maps the same
 * role to the same ink. Paper is a white board with blue writing and yellow accents. The
 * other theme flips the board to blue, with white writing and the same yellow accent.
 * Author labels, not color alone, carry authorship.
 */

export const BRAND = {
  white: "#FFFFFF",
  blue: "#1985d0",
  yellow: "#fdc92a",
} as const;

export type ColorRole = "student" | "tutor";
export type BoardThemeName = "paper" | "slate";

export type BoardTheme = {
  name: BoardThemeName;
  /** Human-facing label for the theme toggle. */
  label: string;
  /** Almost-white (or calm dark) board surface. */
  board: string;
  boardEdge: string;
  boardGrain: string;
  studentInk: string;
  tutorInk: string;
  /** Translucent wash used behind highlighted work. */
  highlightFill: string;
  /** Dashed focus-region outline. */
  focusOutline: string;
  /** Text colors that must stay readable on the board/surfaces. */
  labelText: string;
  labelMuted: string;
  surface: string;
  surfaceEdge: string;
  /** Boundary of inputs and unselected choices. */
  controlEdge: string;
  controlBackground: string;
  controlText: string;
  controlDisabled: string;
  danger: string;
};

export const BOARD_THEMES: Record<BoardThemeName, BoardTheme> = {
  paper: {
    name: "paper",
    label: "Paper",
    board: BRAND.white,
    boardEdge: BRAND.blue,
    boardGrain: BRAND.yellow,
    studentInk: BRAND.blue,
    tutorInk: BRAND.yellow,
    highlightFill: "rgba(253, 201, 42, 0.45)",
    focusOutline: BRAND.blue,
    labelText: BRAND.blue,
    labelMuted: BRAND.blue,
    surface: BRAND.white,
    surfaceEdge: BRAND.blue,
    controlEdge: BRAND.blue,
    controlBackground: BRAND.blue,
    controlText: BRAND.white,
    controlDisabled: BRAND.blue,
    danger: BRAND.blue,
  },
  slate: {
    name: "slate",
    label: "Chalkboard",
    board: BRAND.blue,
    boardEdge: BRAND.white,
    boardGrain: BRAND.white,
    studentInk: BRAND.white,
    tutorInk: BRAND.yellow,
    highlightFill: "rgba(253, 201, 42, 0.55)",
    focusOutline: BRAND.yellow,
    labelText: BRAND.white,
    labelMuted: BRAND.white,
    surface: BRAND.blue,
    surfaceEdge: BRAND.white,
    controlEdge: BRAND.white,
    controlBackground: BRAND.yellow,
    controlText: BRAND.blue,
    controlDisabled: BRAND.white,
    danger: BRAND.yellow,
  },
};

export const DEFAULT_THEME: BoardThemeName = "paper";

export function getTheme(name: BoardThemeName): BoardTheme {
  return BOARD_THEMES[name] ?? BOARD_THEMES[DEFAULT_THEME];
}

/** The locked ink color for an author role. Roles, not raw colors, persist in the scene. */
export function colorForRole(theme: BoardTheme, role: ColorRole): string {
  return role === "student" ? theme.studentInk : theme.tutorInk;
}

function channelLuminance(channel: number): number {
  const c = channel / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** WCAG relative luminance of a #RRGGBB color. */
export function relativeLuminance(hex: string): number {
  const match = /^#([0-9a-fA-F]{6})$/.exec(hex);
  if (!match) {
    throw new Error(`Expected a #RRGGBB color, got ${hex}`);
  }
  const value = match[1];
  const r = channelLuminance(parseInt(value.slice(0, 2), 16));
  const g = channelLuminance(parseInt(value.slice(2, 4), 16));
  const b = channelLuminance(parseInt(value.slice(4, 6), 16));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio between two #RRGGBB colors, in [1, 21]. */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}
