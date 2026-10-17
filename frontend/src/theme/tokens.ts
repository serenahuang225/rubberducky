/**
 * Shared measure for the learning workspace.
 *
 * Two families only: an editorial serif for short headings, and one sans for controls,
 * conversation, instructions, and mathematical text. Corners stay square. Motion durations
 * are short and shared so panels, tools, and tutor marks move the same way.
 */

import { Platform, type TextStyle } from "react-native";

const displayFamily =
  Platform.OS === "web"
    ? '"Newsreader", "Iowan Old Style", Palatino, "Palatino Linotype", Georgia, serif'
    : Platform.OS === "ios"
      ? "Iowan Old Style"
      : "serif";

const sansFamily =
  Platform.OS === "web"
    ? '"Source Sans 3", "Avenir Next", "Segoe UI", sans-serif'
    : Platform.OS === "ios"
      ? "Avenir Next"
      : "sans-serif";

export const font = {
  display: displayFamily,
  sans: sansFamily,
};

export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
} as const;

/** Every control and surface uses square corners. */
export const radius = 0;

export const motionMs = {
  fast: 120,
  base: 180,
  enter: 200,
} as const;

const display = (size: number, lineHeight: number): TextStyle => ({
  fontFamily: font.display,
  fontSize: size,
  lineHeight,
  fontWeight: "500",
});

const sans = (
  size: number,
  lineHeight: number,
  weight: TextStyle["fontWeight"] = "400",
): TextStyle => ({
  fontFamily: font.sans,
  fontSize: size,
  lineHeight,
  fontWeight: weight,
});

export const type = {
  display: display(28, 34),
  title: display(22, 28),
  heading: display(18, 24),
  prompt: display(20, 26),
  name: display(16, 20),
  body: sans(16, 22),
  control: sans(15, 20, "500"),
  small: sans(13, 18),
  meta: sans(12, 16, "500"),
  math: {
    ...sans(16, 22),
    fontVariant: ["tabular-nums"],
  } satisfies TextStyle,
};
