/**
 * The fixed, accessible session palette.
 *
 * There is exactly one student pen and one tutor mark color per theme. Scene objects store
 * a server-assigned color *role* (never a free color), so re-entry and restoration always
 * map the same role to the same ink, and every implemented theme keeps the two roles
 * visually distinct. Author labels, not color, carry authorship for assistive technology.
 *
 * The warm canvas is near-white; the chalkboard is deep charcoal, not pure black. Controls
 * use one pine accent — deep on the canvas, pale on the chalkboard — kept off the blue
 * student ink and the sienna tutor ink.
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
    board: "#F4F0E6",
    boardEdge: "#D4CDBF",
    boardGrain: "#E7E1D4",
    studentInk: "#1A4E96",
    tutorInk: "#B4481C",
    highlightFill: "rgba(180, 72, 28, 0.14)",
    focusOutline: "#1E4538",
    labelText: "#2C2824",
    labelMuted: "#5A544C",
    surface: "#F8F5EE",
    surfaceEdge: "#D8D1C3",
    controlEdge: "#5C564E",
    controlBackground: "#1E4538",
    controlText: "#F6F2E9",
    controlDisabled: "#8A8478",
    danger: "#9C2F28",
  },
  slate: {
    name: "slate",
    label: "Chalkboard",
    board: "#2E3431",
    boardEdge: "#46504B",
    boardGrain: "#262B28",
    studentInk: "#8FCBF2",
    tutorInk: "#E7B07A",
    highlightFill: "rgba(231, 176, 122, 0.22)",
    focusOutline: "#E6D4B0",
    labelText: "#F3EEE4",
    labelMuted: "#C9C2B4",
    surface: "#383F3B",
    surfaceEdge: "#4C564F",
    controlEdge: "#B4BEB6",
    controlBackground: "#D7E3DA",
    controlText: "#1A2621",
    controlDisabled: "#6C756F",
    danger: "#FFB4AA",
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
