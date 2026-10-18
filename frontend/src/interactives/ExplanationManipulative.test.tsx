import { fireEvent, render, screen } from "@testing-library/react-native";
import React from "react";

import { getTheme } from "../board/palette";

import { ExplanationManipulative } from "./ExplanationManipulative";
import {
  parseReleasedExplanation,
  type ReleasedExplanation,
} from "./explanationSpec";
import fallbackDistribution from "./fixtures/released-fallback-distribution.json";
import fallbackGrouping from "./fixtures/released-fallback-grouping.json";
import verifiedDistribution from "./fixtures/released-verified-distribution.json";
import verifiedGrouping from "./fixtures/released-verified-grouping.json";

const theme = getTheme("paper");

function released(raw: unknown): ReleasedExplanation {
  const parsed = parseReleasedExplanation(raw);
  if (!parsed.ok) {
    throw new Error(parsed.error);
  }
  return parsed.value;
}

function clone(raw: unknown): Record<string, any> {
  return JSON.parse(JSON.stringify(raw));
}

function cellCount(testID: string): number {
  return screen.queryAllByTestId(`${testID}-cell`).length;
}

function readout(): string {
  const node = screen.getByTestId("manipulative-readout");
  return [node.props.children].flat().join("");
}

describe("backend release fixtures", () => {
  it.each([
    ["fallback distribution", fallbackDistribution],
    ["fallback grouping", fallbackGrouping],
    ["verified distribution", verifiedDistribution],
    ["verified grouping", verifiedGrouping],
  ])("parse: %s", (_name, raw) => {
    expect(parseReleasedExplanation(raw).ok).toBe(true);
  });
});

describe("untrusted payloads never parse into something renderable", () => {
  const mutations: [string, (data: Record<string, any>) => void][] = [
    ["unknown component", (d) => (d.spec.manipulative.component = "iframe")],
    ["script field on the component", (d) => (d.spec.manipulative.script = "alert(1)")],
    ["extra spec field", (d) => (d.spec.html = "<b>x</b>")],
    ["markup in the title", (d) => (d.spec.title = "<b>Bold</b>")],
    ["link in the caption", (d) => (d.spec.caption = "See https://evil.test now")],
    ["scheme in the prompt", (d) => (d.spec.prompt = "javascript:alert(1)")],
    ["oversize title", (d) => (d.spec.title = "x".repeat(81))],
    ["range above the cap", (d) => (d.spec.manipulative.groups.max = 13)],
    ["initial out of range", (d) => (d.spec.manipulative.groups.initial = 0)],
    ["non-integer range", (d) => (d.spec.manipulative.groups.max = 4.5)],
    ["unknown concept", (d) => (d.spec.concept_id = "concept.other")],
    ["fallback without a reason", (d) => (d.fallback_reason = null)],
    ["verified claiming a reason", (d) => (d.source = "generated_verified")],
  ];

  it.each(mutations)("rejects %s", (_name, mutate) => {
    const data = clone(fallbackGrouping);
    mutate(data);
    const parsed = parseReleasedExplanation(data);
    expect(parsed.ok).toBe(false);
  });

  it("rejects a verified release whose created sandbox was not confirmed deleted", () => {
    const data = clone(verifiedGrouping);
    data.sandbox_ids_deleted = [];
    expect(data.sandbox_ids_created.length).toBeGreaterThan(0);
    expect(parseReleasedExplanation(data).ok).toBe(false);
  });

  it.each([null, undefined, 3, "text", [], {}])("rejects non-objects like %p", (input) => {
    expect(parseReleasedExplanation(input).ok).toBe(false);
  });

  it("returns a generic message without echoing the payload", () => {
    const data = clone(fallbackGrouping);
    data.spec.title = "<script>alert('leak-me')</script>";
    const parsed = parseReleasedExplanation(data);
    expect(parsed.ok).toBe(false);
    expect(JSON.stringify(parsed)).not.toContain("leak-me");
  });
});

describe("grouping manipulative", () => {
  const renderGrouping = () =>
    render(<ExplanationManipulative released={released(fallbackGrouping)} theme={theme} />);

  it("starts from the spec's initial values and draws that many items", () => {
    renderGrouping();
    expect(readout()).toBe("3 groups \u00d7 4 counters each = 12 counters");
    expect(screen.getAllByTestId("grouping-group")).toHaveLength(3);
    expect(
      [0, 1, 2].reduce((sum, index) => sum + cellCount(`grouping-group-${index}`), 0),
    ).toBe(12);
  });

  it("changes the groups and the total when the learner adds and removes a group", () => {
    renderGrouping();
    fireEvent.press(screen.getByTestId("groups-more"));
    expect(screen.getByTestId("groups-value").props.children).toBe(4);
    expect(readout()).toBe("4 groups \u00d7 4 counters each = 16 counters");
    expect(screen.getAllByTestId("grouping-group")).toHaveLength(4);
    fireEvent.press(screen.getByTestId("groups-less"));
    fireEvent.press(screen.getByTestId("groups-less"));
    expect(readout()).toBe("2 groups \u00d7 4 counters each = 8 counters");
    expect(screen.getAllByTestId("grouping-group")).toHaveLength(2);
  });

  it("changes the items per group independently", () => {
    renderGrouping();
    fireEvent.press(screen.getByTestId("per-group-more"));
    expect(readout()).toBe("3 groups \u00d7 5 counters each = 15 counters");
    expect(cellCount("grouping-group-0")).toBe(5);
  });

  it("stops at the spec's own bounds and disables the control there", () => {
    renderGrouping();
    for (let press = 0; press < 20; press += 1) {
      fireEvent.press(screen.getByTestId("groups-more"));
    }
    expect(screen.getByTestId("groups-value").props.children).toBe(8);
    expect(screen.getByTestId("groups-more").props.accessibilityState.disabled).toBe(true);
    for (let press = 0; press < 20; press += 1) {
      fireEvent.press(screen.getByTestId("groups-less"));
    }
    expect(screen.getByTestId("groups-value").props.children).toBe(1);
    expect(readout()).toBe("1 group \u00d7 4 counters each = 4 counters");
    expect(screen.getByTestId("groups-less").props.accessibilityState.disabled).toBe(true);
  });

  it("gives every control a spoken name and a touch target of at least 44 points", () => {
    renderGrouping();
    const button = screen.getByLabelText("Increase Groups");
    expect(button.props.accessibilityRole).toBe("button");
    const style = [button.props.style].flat(2).reduce((all, part) => ({ ...all, ...part }), {});
    expect(style.minWidth).toBeGreaterThanOrEqual(44);
    expect(style.minHeight).toBeGreaterThanOrEqual(44);
    expect(screen.getByLabelText("Groups: 3 groups")).toBeTruthy();
  });
});

describe("distribution manipulative", () => {
  const renderDistribution = () =>
    render(<ExplanationManipulative released={released(fallbackDistribution)} theme={theme} />);

  it("draws two rectangles whose cells add up to the whole", () => {
    renderDistribution();
    expect(cellCount("distribution-left")).toBe(12);
    expect(cellCount("distribution-right")).toBe(6);
    expect(readout()).toBe("3 \u00d7 (4 + 2) = 18\n3 \u00d7 4 + 3 \u00d7 2 = 12 + 6 = 18");
  });

  it("keeps a(b + c) equal to ab + ac whichever quantity the learner changes", () => {
    renderDistribution();
    fireEvent.press(screen.getByTestId("outer-more"));
    expect(cellCount("distribution-left")).toBe(16);
    expect(cellCount("distribution-right")).toBe(8);
    fireEvent.press(screen.getByTestId("left-more"));
    fireEvent.press(screen.getByTestId("right-more"));
    expect(cellCount("distribution-left")).toBe(20);
    expect(cellCount("distribution-right")).toBe(12);
    expect(readout()).toBe("4 \u00d7 (5 + 3) = 32\n4 \u00d7 5 + 4 \u00d7 3 = 20 + 12 = 32");
  });

  it("respects each quantity's own range", () => {
    renderDistribution();
    for (let press = 0; press < 20; press += 1) {
      fireEvent.press(screen.getByTestId("right-less"));
    }
    expect(screen.getByTestId("right-value").props.children).toBe(1);
    expect(screen.getByTestId("right-less").props.accessibilityState.disabled).toBe(true);
  });
});

describe("source label", () => {
  it("says a fallback is pre-vetted and not generated, with the reason in plain words", () => {
    render(<ExplanationManipulative released={released(fallbackGrouping)} theme={theme} />);
    expect(screen.getByTestId("explanation-source-label").props.children).toBe(
      fallbackGrouping.label,
    );
    expect(screen.getByTestId("explanation-source-label").props.children).toMatch(
      /pre-vetted.*not generated/i,
    );
    expect(screen.getByTestId("explanation-fallback-note").props.children).toMatch(/not turned on/i);
  });

  it("labels a verified release as generated and shows no fallback note", () => {
    render(<ExplanationManipulative released={released(verifiedGrouping)} theme={theme} />);
    expect(screen.getByTestId("explanation-source-label").props.children).toMatch(
      /generated explanation that passed/i,
    );
    expect(screen.queryByTestId("explanation-fallback-note")).toBeNull();
  });

  it("explains a failed generation differently from a disabled one", () => {
    const data = clone(fallbackGrouping);
    data.fallback_reason = "checks_failed";
    render(<ExplanationManipulative released={released(data)} theme={theme} />);
    expect(screen.getByTestId("explanation-fallback-note").props.children).toMatch(
      /could not be released/i,
    );
  });
});

describe("rendering a different explanation", () => {
  it("starts the new spec from its own initial values", () => {
    const view = render(
      <ExplanationManipulative released={released(fallbackGrouping)} theme={theme} />,
    );
    fireEvent.press(screen.getByTestId("groups-more"));
    const other = clone(fallbackGrouping);
    other.spec.manipulative.groups.initial = 2;
    view.rerender(<ExplanationManipulative released={released(other)} theme={theme} />);
    expect(readout()).toBe("2 groups \u00d7 4 counters each = 8 counters");
  });
});
