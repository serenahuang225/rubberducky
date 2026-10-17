import {
  BOARD_THEMES,
  colorForRole,
  contrastRatio,
  getTheme,
  type BoardThemeName,
} from "./palette";

const THEME_NAMES = Object.keys(BOARD_THEMES) as BoardThemeName[];

describe("session palette", () => {
  it("exposes exactly the implemented themes, all with distinct student/tutor ink", () => {
    expect(THEME_NAMES.sort()).toEqual(["paper", "slate"]);
    for (const name of THEME_NAMES) {
      const theme = getTheme(name);
      expect(theme.studentInk).not.toEqual(theme.tutorInk);
    }
  });

  it("maps color roles deterministically so restoration never collides", () => {
    for (const name of THEME_NAMES) {
      const theme = getTheme(name);
      // Restoration is a pure role -> ink lookup; the same role always re-renders the
      // same ink, and the two roles never share one, in any theme mapping.
      expect(colorForRole(theme, "student")).toBe(theme.studentInk);
      expect(colorForRole(theme, "tutor")).toBe(theme.tutorInk);
      expect(colorForRole(theme, "student")).not.toBe(
        colorForRole(theme, "tutor"),
      );
    }
  });

  it("keeps both inks at or above the 3:1 non-text contrast bar on the board", () => {
    for (const name of THEME_NAMES) {
      const theme = getTheme(name);
      expect(
        contrastRatio(theme.studentInk, theme.board),
      ).toBeGreaterThanOrEqual(3);
      expect(contrastRatio(theme.tutorInk, theme.board)).toBeGreaterThanOrEqual(
        3,
      );
    }
  });

  it("keeps label text at or above the 4.5:1 text contrast bar", () => {
    for (const name of THEME_NAMES) {
      const theme = getTheme(name);
      expect(
        contrastRatio(theme.labelText, theme.board),
      ).toBeGreaterThanOrEqual(4.5);
      expect(
        contrastRatio(theme.labelText, theme.surface),
      ).toBeGreaterThanOrEqual(4.5);
      expect(
        contrastRatio(theme.controlText, theme.controlBackground),
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps muted and danger text readable on every surface the screens use", () => {
    for (const theme of Object.values(BOARD_THEMES)) {
      for (const background of [theme.board, theme.surface, theme.boardGrain]) {
        expect(
          contrastRatio(theme.labelMuted, background),
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          contrastRatio(theme.labelText, background),
        ).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(theme.danger, background)).toBeGreaterThanOrEqual(
          4.5,
        );
      }
    }
  });

  it("draws input and unselected-choice boundaries at 3:1 or better, and keeps the focus ring visible", () => {
    for (const theme of Object.values(BOARD_THEMES)) {
      for (const background of [theme.surface, theme.boardGrain]) {
        expect(
          contrastRatio(theme.controlEdge, background),
        ).toBeGreaterThanOrEqual(3);
        expect(
          contrastRatio(theme.controlBackground, background),
        ).toBeGreaterThanOrEqual(3);
        expect(
          contrastRatio(theme.focusOutline, background),
        ).toBeGreaterThanOrEqual(3);
      }
    }
  });

  it("names the dark theme for what it looks like", () => {
    expect(BOARD_THEMES.slate.label).toBe("Chalkboard");
  });

  it("computes WCAG contrast ratios correctly", () => {
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 1);
    expect(contrastRatio("#FFFFFF", "#FFFFFF")).toBeCloseTo(1, 5);
  });

  it("keeps the two roles in distinct hue families across themes", () => {
    // Student ink is always blue-dominant, tutor ink always warm/red-dominant; the test
    // pins the intended pairing so a future palette edit cannot quietly merge them.
    const channel = (hex: string, offset: number) =>
      parseInt(hex.slice(offset, offset + 2), 16);
    for (const name of THEME_NAMES) {
      const theme = getTheme(name);
      expect(channel(theme.studentInk, 5)).toBeGreaterThan(
        channel(theme.studentInk, 1),
      );
      expect(channel(theme.tutorInk, 1)).toBeGreaterThan(
        channel(theme.tutorInk, 5),
      );
    }
  });
});
