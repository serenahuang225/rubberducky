/**
 * Shared measure for the learning workspace.
 *
 * Quicksand is the one face: a rounded sans for headings, controls, conversation, and
 * mathematical text. Corners are round. Motion durations are short and shared so panels,
 * tools, and tutor marks move the same way.
 */

import { Platform, type TextStyle } from "react-native";

const roundedFamily = "Quicksand";

export const font = {
  display: roundedFamily,
  sans: roundedFamily,
  mono: Platform.OS === "ios" ? "Menlo" : "monospace",
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

/** Round corners for controls, cards, and pills. */
export const radius = {
  sm: 14,
  md: 20,
  lg: 28,
  pill: 999,
} as const;

export const motionMs = {
  fast: 120,
  base: 180,
  enter: 200,
} as const;

const display = (size: number, lineHeight: number): TextStyle => ({
  fontFamily: font.display,
  fontSize: size,
  lineHeight,
  fontWeight: "700",
});

const sans = (
  size: number,
  lineHeight: number,
  weight: TextStyle["fontWeight"] = "500",
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
  name: display(16, 22),
  body: sans(16, 22),
  control: sans(15, 20, "700"),
  small: sans(13, 18, "600"),
  meta: sans(12, 16, "700"),
  math: {
    ...sans(16, 22, "700"),
    fontVariant: ["tabular-nums"],
  } satisfies TextStyle,
};
