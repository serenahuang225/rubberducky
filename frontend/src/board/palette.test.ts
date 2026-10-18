import {
  BOARD_THEMES,
  BRAND,
  colorForRole,
  contrastRatio,
  getTheme,
  type BoardThemeName,
} from "./palette";

const THEME_NAMES = Object.keys(BOARD_THEMES) as BoardThemeName[];
const BRAND_COLORS = new Set<string>([BRAND.white, BRAND.blue, BRAND.yellow]);

describe("session palette", () => {
  it("exposes exactly the implemented themes, all with distinct student/tutor ink", () => {
    expect(THEME_NAMES.sort()).toEqual(["paper", "slate"]);
    for (const name of THEME_NAMES) {
      const theme = getTheme(name);
      expect(theme.studentInk).not.toEqual(theme.tutorInk);
    }
  });

  it("uses only white, blue, and yellow for solid colors", () => {
    for (const theme of Object.values(BOARD_THEMES)) {
      for (const [key, value] of Object.entries(theme)) {
        if (key === "name" || key === "label" || key === "highlightFill") continue;
        expect(BRAND_COLORS.has(value)).toBe(true);
      }
    }
    expect(BOARD_THEMES.paper.board).toBe(BRAND.white);
    expect(BOARD_THEMES.paper.studentInk).toBe(BRAND.blue);
    expect(BOARD_THEMES.paper.tutorInk).toBe(BRAND.yellow);
    expect(BOARD_THEMES.slate.board).toBe(BRAND.blue);
    expect(BOARD_THEMES.slate.studentInk).toBe(BRAND.white);
    expect(BOARD_THEMES.slate.tutorInk).toBe(BRAND.yellow);
  });

  it("maps color roles deterministically so restoration never collides", () => {
    for (const name of THEME_NAMES) {
      const theme = getTheme(name);
      expect(colorForRole(theme, "student")).toBe(theme.studentInk);
      expect(colorForRole(theme, "tutor")).toBe(theme.tutorInk);
      expect(colorForRole(theme, "student")).not.toBe(
        colorForRole(theme, "tutor"),
      );
    }
  });

  it("keeps the blue and white pair as the readable combination", () => {
    expect(contrastRatio(BRAND.blue, BRAND.white)).toBeGreaterThanOrEqual(3);
    expect(
      contrastRatio(BOARD_THEMES.paper.labelText, BOARD_THEMES.paper.board),
    ).toBeGreaterThanOrEqual(3);
    expect(
      contrastRatio(BOARD_THEMES.slate.labelText, BOARD_THEMES.slate.board),
    ).toBeGreaterThanOrEqual(3);
  });

  it("names the dark theme for what it looks like", () => {
    expect(BOARD_THEMES.slate.label).toBe("Chalkboard");
  });

  it("computes WCAG contrast ratios correctly", () => {
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 1);
    expect(contrastRatio("#FFFFFF", "#FFFFFF")).toBeCloseTo(1, 5);
  });

  it("keeps the tutor accent warm and the paper student ink blue", () => {
    const channel = (hex: string, offset: number) =>
      parseInt(hex.slice(offset, offset + 2), 16);
    expect(channel(BOARD_THEMES.paper.studentInk, 5)).toBeGreaterThan(
      channel(BOARD_THEMES.paper.studentInk, 1),
    );
    for (const theme of Object.values(BOARD_THEMES)) {
      expect(channel(theme.tutorInk, 1)).toBeGreaterThan(
        channel(theme.tutorInk, 5),
      );
    }
  });
});
