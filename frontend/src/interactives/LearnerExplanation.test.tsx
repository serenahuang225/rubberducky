import { fireEvent, render, screen } from "@testing-library/react-native";
import React from "react";
import { Text } from "react-native";

import { getTheme } from "../board/palette";

import fallbackDistribution from "./fixtures/released-fallback-distribution.json";
import fallbackGrouping from "./fixtures/released-fallback-grouping.json";
import verifiedGrouping from "./fixtures/released-verified-grouping.json";
import { LearnerExplanation } from "./LearnerExplanation";
import {
  fetchLearnerExplanation,
  readLearnerExplanation,
  requestForConcept,
  UNAVAILABLE_EXPLANATION,
} from "./learnerRelease";

const theme = getTheme("paper");
const NOTICE =
  "Factory and Daytona were not contacted. This is the app's pre-vetted explanation, not a generated release.";

function envelope(release: unknown, live = false) {
  return {
    schema_version: "learner-explanation.v1",
    live_services_contacted: live,
    notice: NOTICE,
    release,
  };
}

function readout(): string {
  const node = screen.getByTestId("manipulative-readout");
  return [node.props.children].flat().join("");
}

describe("learner explanation path", () => {
  it("parses a disabled fallback, labels it, and updates the distribution total", () => {
    render(
      <LearnerExplanation theme={theme} payload={envelope(fallbackDistribution)}>
        <Text testID="student-board">2x + 6 = 14</Text>
      </LearnerExplanation>,
    );
    expect(screen.getByTestId("student-board").props.children).toBe("2x + 6 = 14");
    expect(screen.getByTestId("learner-explanation-notice").props.children).toBe(NOTICE);
    expect(screen.getByTestId("factory-state-label").props.children).toBe("Factory: disabled");
    expect(screen.getByTestId("daytona-state-label").props.children).toBe("Daytona: disabled");
    expect(screen.getByTestId("explanation-source-label").props.children).toMatch(
      /pre-vetted.*not generated/i,
    );
    expect(screen.getByTestId("explanation-fallback-note").props.children).toMatch(/not turned on/i);
    expect(readout()).toBe("3 × (4 + 2) = 18\n3 × 4 + 3 × 2 = 12 + 6 = 18");
    fireEvent.press(screen.getByTestId("outer-more"));
    expect(readout()).toBe("4 × (4 + 2) = 24\n4 × 4 + 4 × 2 = 16 + 8 = 24");
    expect(screen.getByTestId("student-board").props.children).toBe("2x + 6 = 14");
  });

  it("labels a configured but uncontacted release as a fallback, not a generated one", () => {
    const release = JSON.parse(JSON.stringify(fallbackGrouping));
    release.fallback_reason = "checks_unavailable";
    release.factory_state = "configured_unverified";
    release.daytona_state = "configured_unverified";
    render(<LearnerExplanation theme={theme} payload={envelope(release)} />);
    expect(screen.getByTestId("explanation-source-label").props.children).toMatch(/not generated/i);
    expect(screen.getByTestId("explanation-fallback-note").props.children).toMatch(
      /could not be released/i,
    );
    expect(screen.queryByText(/generated explanation that passed/i)).toBeNull();
    expect(screen.getByTestId("factory-state-label").props.children).toBe(
      "Factory: configured, unverified",
    );
    expect(screen.getByTestId("daytona-state-label").props.children).toBe(
      "Daytona: configured, unverified",
    );
    expect(screen.getByTestId("learner-explanation-notice").props.children).toMatch(
      /not contacted/i,
    );
  });

  it("labels a trusted release as generated and still says the integrations are unverified", () => {
    render(<LearnerExplanation theme={theme} payload={envelope(verifiedGrouping)} />);
    expect(screen.getByTestId("explanation-source-label").props.children).toMatch(
      /generated explanation that passed/i,
    );
    expect(screen.queryByTestId("explanation-fallback-note")).toBeNull();
    expect(screen.getByTestId("factory-state-label").props.children).toBe(
      "Factory: configured, unverified",
    );
    expect(screen.getByTestId("daytona-state-label").props.children).toBe(
      "Daytona: configured, unverified",
    );
    expect(screen.getByTestId("learner-explanation-notice").props.children).toMatch(/not contacted/i);
  });

  it("keeps the board and skips the manipulative when the release cannot be parsed", () => {
    render(
      <LearnerExplanation theme={theme} payload={envelope({ schema_version: "nope" })}>
        <Text testID="student-board">saved work</Text>
      </LearnerExplanation>,
    );
    expect(screen.getByTestId("student-board").props.children).toBe("saved work");
    expect(screen.getByTestId("learner-explanation-error").props.children).toBe(
      "This explanation could not be shown safely.",
    );
    expect(screen.queryByTestId("explanation-manipulative")).toBeNull();
    expect(JSON.stringify(screen.getByTestId("learner-explanation-error").props.children)).not.toContain(
      "schema_version",
    );
  });

  it("refuses an envelope that claims a live call, and keeps the board", () => {
    render(
      <LearnerExplanation theme={theme} payload={envelope(verifiedGrouping, true)}>
        <Text testID="student-board">saved work</Text>
      </LearnerExplanation>,
    );
    expect(screen.getByTestId("student-board")).toBeTruthy();
    expect(screen.queryByTestId("explanation-manipulative")).toBeNull();
    expect(screen.queryByText(/generated explanation that passed/i)).toBeNull();
    expect(readLearnerExplanation(envelope(verifiedGrouping, true)).ok).toBe(false);
  });

  it("keeps the board when the explanation cannot be loaded", async () => {
    render(
      <LearnerExplanation
        theme={theme}
        load={async () => {
          throw new Error("offline");
        }}
      >
        <Text testID="student-board">2x + 6 = 14</Text>
      </LearnerExplanation>,
    );
    expect((await screen.findByTestId("learner-explanation-error")).props.children).toBe(
      UNAVAILABLE_EXPLANATION,
    );
    expect(screen.getByTestId("student-board").props.children).toBe("2x + 6 = 14");
    expect(screen.queryByTestId("explanation-manipulative")).toBeNull();
  });
});

describe("fetchLearnerExplanation", () => {
  it("posts the bounded request without a credential", async () => {
    const calls: { url: string; init?: { method?: string; headers?: Record<string, string>; body?: string } }[] =
      [];
    const body = await fetchLearnerExplanation(
      "http://example.test",
      requestForConcept("concept.grouping"),
      async (url, init) => {
        calls.push({ url, init });
        return { ok: true, status: 200, json: async () => envelope(fallbackDistribution) };
      },
    );
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("http://example.test/explanations/learner");
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[0].init?.headers).toEqual({ "Content-Type": "application/json" });
    expect(calls[0].init?.headers).not.toHaveProperty("Authorization");
    expect(JSON.parse(calls[0].init?.body ?? "{}")).toMatchObject({
      concept_id: "concept.grouping",
      misconception: "Needs a concrete picture of this idea",
    });
    expect(readLearnerExplanation(body).ok).toBe(true);
  });
});
