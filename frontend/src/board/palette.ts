/**
 * The fixed, accessible session palette.
 *
 * There is exactly one student pen and one tutor mark color per theme. Scene objects store
 * a server-assigned color *role* (never a free color), so re-entry and restoration always
 * map the same role to the same ink, and every implemented theme keeps the two roles
 * visually distinct. Author labels, not color, carry authorship for assistive technology.
 */

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
  /** Boundary of inputs and unselected choices; 3:1 against the surface (WCAG 1.4.11). */
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
    board: "#FCFBF5",
    boardEdge: "#E3DFD3",
    boardGrain: "#EFEDE4",
    studentInk: "#1D4ED8",
    tutorInk: "#C2410C",
    highlightFill: "rgba(194, 65, 12, 0.14)",
    focusOutline: "#7C3AED",
    labelText: "#1F2937",
    labelMuted: "#52606D",
    surface: "#FFFFFF",
    surfaceEdge: "#D9DDE1",
    controlEdge: "#6B7785",
    controlBackground: "#2F4858",
    controlText: "#FFFFFF",
    controlDisabled: "#9AA5AF",
    danger: "#B3261E",
  },
  slate: {
    name: "slate",
    label: "Chalkboard",
    board: "#23343B",
    boardEdge: "#3D545E",
    boardGrain: "#2C424B",
    studentInk: "#8FD0FF",
    tutorInk: "#FFB84D",
    highlightFill: "rgba(255, 184, 77, 0.22)",
    focusOutline: "#C4B5FD",
    labelText: "#F4F1E8",
    labelMuted: "#C3CED6",
    surface: "#1B2830",
    surfaceEdge: "#3D545E",
    controlEdge: "#8FA3AE",
    controlBackground: "#8FD0FF",
    controlText: "#12212B",
    controlDisabled: "#5B6E77",
    danger: "#FF8A80",
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
