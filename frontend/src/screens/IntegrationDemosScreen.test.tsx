import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import React from "react";

import type { IntegrationDemos } from "../api/integrationDemos";
import { getTheme } from "../board/palette";

import { IntegrationDemosScreen } from "./IntegrationDemosScreen";

const DEMOS: IntegrationDemos = {
  schema_version: "fictional-integration-demos.v1",
  is_fictional: true,
  live_services_contacted: false,
  notice: "Invented walkthrough. Nothing was uploaded.",
  chalk: {
    title: "Chalk tutoring evaluation",
    notice: "Scores come from the local rubric.",
    dataset_name: "rubberducky-tutoring-replay",
    dataset_rows: 8,
    uploaded: false,
    trained_model_result: false,
    learning_gain_claim: false,
    candidates: [
      {
        candidate_name: "fixture:good",
        note: "Scripted replies for a careful tutor.",
        errors: 0,
        dimensions: [
          { dimension: "math", mean: 1, scored_rows: 8, missing_rows: 0 },
          { dimension: "respect", mean: 1, scored_rows: 8, missing_rows: 0 },
        ],
        turns: [
          {
            scenario: "partial_distribution",
            learner_message: "My next line is 2x + 3 = 14.",
            reply: "What does the 2 outside multiply?",
            scores: [
              { dimension: "math", value: 1 },
              { dimension: "respect", value: 1 },
            ],
          },
        ],
      },
      {
        candidate_name: "fixture:leaky",
        note: "Gives the answer and blames the learner.",
        errors: 0,
        dimensions: [{ dimension: "respect", mean: 0, scored_rows: 8, missing_rows: 0 }],
        turns: [],
      },
    ],
  },
  droid: {
    title: "Factory Droid explanation",
    notice: "Factory Droid was not started.",
    misconception: "Multiplies only the first term inside brackets",
    context_note: "Fictional learner Ada wrote 3(x + 2) as 3x + 2.",
    self_check_notes: ["Fictional note."],
    factory_contacted: false,
    credits_spent: 0,
    picture_label: "Fictional demo picture. Factory and Daytona were not contacted.",
    spec: {
      schema_version: "explanation-spec.v1",
      concept_id: "concept.distribution",
      title: "The outside number reaches both parts",
      prompt: "Change the outside number. What happens to both rectangles?",
      caption: "The outside number multiplies both parts.",
      manipulative: {
        component: "distribution",
        outer: { min: 1, max: 6, initial: 3 },
        left: { min: 1, max: 8, initial: 1 },
        right: { min: 1, max: 8, initial: 2 },
      },
    },
  },
  daytona: {
    title: "Daytona sandbox check",
    notice: "No Daytona sandbox was created.",
    sandbox_id: "sbx-fictional-demo",
    sandbox_created: false,
    passed: true,
    checks: [{ name: "layout_math", passed: true, detail: "a(b + c) equals ab + ac" }],
  },
};

describe("IntegrationDemosScreen", () => {
  it("shows the three fictional demos and lets the picture change", async () => {
    render(
      <IntegrationDemosScreen
        theme={getTheme("paper")}
        onClose={() => undefined}
        loadDemos={async () => DEMOS}
      />,
    );
    expect(await screen.findByText("Chalk tutoring evaluation")).toBeTruthy();
    expect(screen.getByTestId("demo-notice")).toHaveTextContent(/Nothing was uploaded/);
    expect(screen.getByText(/8 fictional rows/)).toBeTruthy();
    expect(screen.getByText(/fixture:good/)).toBeTruthy();
    expect(screen.getByText(/What does the 2 outside multiply/)).toBeTruthy();
    expect(screen.getByText("Factory Droid explanation")).toBeTruthy();
    expect(screen.getByText(/Factory Droid was not started/)).toBeTruthy();
    expect(screen.getByTestId("manipulative-readout")).toHaveTextContent(
      /3 × \(1 \+ 2\) = 9/,
    );
    fireEvent.press(screen.getByTestId("outer-more"));
    expect(screen.getByTestId("manipulative-readout")).toHaveTextContent(
      /4 × \(1 \+ 2\) = 12/,
    );
    expect(screen.getByText(/No Daytona sandbox was created/)).toBeTruthy();
    expect(screen.getByText(/layout_math: passed/)).toBeTruthy();
  });

  it("says when the demos cannot be loaded and retries", async () => {
    const loadDemos = jest
      .fn<Promise<IntegrationDemos>, []>()
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce(DEMOS);
    render(
      <IntegrationDemosScreen
        theme={getTheme("paper")}
        onClose={() => undefined}
        loadDemos={loadDemos}
      />,
    );
    expect(await screen.findByText(/could not be loaded/)).toBeTruthy();
    fireEvent.press(screen.getByRole("button", { name: "Try loading the demos again" }));
    await waitFor(() => expect(screen.getByText("Chalk tutoring evaluation")).toBeTruthy());
    expect(loadDemos).toHaveBeenCalledTimes(2);
  });
});
