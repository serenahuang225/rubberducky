/**
 * Fictional Chalk, Droid, and Daytona walkthrough.
 *
 * The tutor service builds this from scripted replies, repository text, and the local
 * trusted checks. The screen says so, and it never treats the result as a live run.
 */

import React, { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import {
  fetchIntegrationDemos,
  type IntegrationDemos,
} from "../api/integrationDemos";
import type { BoardTheme } from "../board/palette";
import { ScreenFrame } from "../components/ScreenFrame";
import { getApiBaseUrl } from "../config/apiBaseUrl";
import type { MotionMode } from "../feedback/preferences";
import { ExplanationManipulative } from "../interactives/ExplanationManipulative";
import { parseReleasedExplanation } from "../interactives/explanationSpec";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; demos: IntegrationDemos }
  | { kind: "error" };

export type IntegrationDemosScreenProps = {
  theme: BoardTheme;
  motion?: MotionMode;
  onClose: () => void;
  loadDemos?: () => Promise<IntegrationDemos>;
};

const defaultLoadDemos = () => fetchIntegrationDemos(getApiBaseUrl());

function formatScore(value: number | null): string {
  return value === null ? "n/a" : value.toFixed(2);
}

export function IntegrationDemosScreen({
  theme,
  motion,
  onClose,
  loadDemos = defaultLoadDemos,
}: IntegrationDemosScreenProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const text = { color: theme.labelText };
  const muted = { color: theme.labelMuted };
  const card = {
    backgroundColor: theme.surface,
    borderColor: theme.surfaceEdge,
  };

  useEffect(() => {
    let active = true;
    loadDemos()
      .then((demos) => active && setState({ kind: "ready", demos }))
      .catch(() => active && setState({ kind: "error" }));
    return () => {
      active = false;
    };
  }, [loadDemos, attempt]);

  const retry = useCallback(() => {
    setState({ kind: "loading" });
    setAttempt((previous) => previous + 1);
  }, []);

  return (
    <ScreenFrame
      theme={theme}
      motion={motion}
      testID="integration-demos-screen"
      title="Fictional demos"
      closeLabel="Back to settings"
      onClose={onClose}
    >
      {state.kind === "loading" ? (
        <Text testID="demo-status" style={[styles.note, muted]}>
          Loading the fictional demos…
        </Text>
      ) : null}
      {state.kind === "error" ? (
        <View style={styles.block}>
          <Text testID="demo-status" style={[styles.note, { color: theme.danger }]}>
            The fictional demos could not be loaded.
          </Text>
          <Pressable
            testID="demo-retry"
            accessibilityRole="button"
            accessibilityLabel="Try loading the demos again"
            onPress={retry}
            style={[styles.button, { backgroundColor: theme.controlBackground }]}
          >
            <Text style={[styles.buttonText, { color: theme.controlText }]}>
              Try again
            </Text>
          </Pressable>
        </View>
      ) : null}
      {state.kind === "ready" ? (
        <ReadyDemos demos={state.demos} theme={theme} text={text} muted={muted} card={card} />
      ) : null}
    </ScreenFrame>
  );
}

function ReadyDemos({
  demos,
  theme,
  text,
  muted,
  card,
}: {
  demos: IntegrationDemos;
  theme: BoardTheme;
  text: { color: string };
  muted: { color: string };
  card: { backgroundColor: string; borderColor: string };
}) {
  const picture = parseReleasedExplanation({
    schema_version: "released-explanation.v1",
    source: "generated_verified",
    label: demos.droid.picture_label,
    spec: demos.droid.spec,
    fallback_reason: null,
    factory_state: "disabled",
    daytona_state: "disabled",
    sandbox_ids_created: [],
    sandbox_ids_deleted: [],
  });

  return (
    <View style={styles.stack}>
      <Text testID="demo-notice" style={[styles.note, muted]}>
        {demos.notice}
      </Text>

      <View testID="demo-chalk" style={[styles.section, card]}>
        <Text accessibilityRole="header" style={[styles.sectionTitle, text]}>
          {demos.chalk.title}
        </Text>
        <Text style={[styles.note, muted]}>{demos.chalk.notice}</Text>
        <Text style={[styles.note, text]}>
          {`${demos.chalk.dataset_rows} fictional rows in ${demos.chalk.dataset_name}. Nothing was uploaded.`}
        </Text>
        {demos.chalk.candidates.map((candidate) => (
          <View key={candidate.candidate_name} style={styles.block}>
            <Text style={[styles.groupTitle, text]}>{candidate.candidate_name}</Text>
            <Text style={[styles.note, muted]}>{candidate.note}</Text>
            <Text style={[styles.note, text]}>
              {candidate.dimensions
                .map((item) => `${item.dimension} ${formatScore(item.mean)}`)
                .join("  ·  ")}
            </Text>
            {candidate.turns.map((turn) => (
              <View key={`${turn.scenario}-${turn.learner_message}`} style={styles.turn}>
                <Text style={[styles.groupTitle, text]}>{turn.scenario}</Text>
                <Text style={[styles.note, text]}>{`Learner: ${turn.learner_message}`}</Text>
                <Text style={[styles.note, text]}>{`Tutor: ${turn.reply}`}</Text>
              </View>
            ))}
          </View>
        ))}
      </View>

      <View testID="demo-droid" style={[styles.section, card]}>
        <Text accessibilityRole="header" style={[styles.sectionTitle, text]}>
          {demos.droid.title}
        </Text>
        <Text style={[styles.note, muted]}>{demos.droid.notice}</Text>
        <Text style={[styles.note, text]}>{`Misconception: ${demos.droid.misconception}`}</Text>
        <Text style={[styles.note, muted]}>{demos.droid.context_note}</Text>
        {picture.ok ? (
          <ExplanationManipulative released={picture.value} theme={theme} />
        ) : (
          <Text style={[styles.note, { color: theme.danger }]}>{picture.error}</Text>
        )}
      </View>

      <View testID="demo-daytona" style={[styles.section, card]}>
        <Text accessibilityRole="header" style={[styles.sectionTitle, text]}>
          {demos.daytona.title}
        </Text>
        <Text style={[styles.note, muted]}>{demos.daytona.notice}</Text>
        <Text style={[styles.note, text]}>
          {demos.daytona.passed
            ? "Every local check passed. No sandbox was created."
            : "A local check failed. No sandbox was created."}
        </Text>
        {demos.daytona.checks.map((check) => (
          <Text key={check.name} style={[styles.note, text]}>
            {`${check.name}: ${check.passed ? "passed" : "failed"}. ${check.detail}`}
          </Text>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: 16 },
  section: { padding: 24, gap: 16, borderRadius: 28, borderWidth: 2 },
  sectionTitle: { fontSize: 20, fontWeight: "700" },
  groupTitle: { fontSize: 16, fontWeight: "700" },
  note: { fontSize: 15, lineHeight: 21 },
  block: { gap: 6 },
  turn: { gap: 4, marginTop: 8 },
  button: {
    minHeight: 48,
    paddingHorizontal: 20,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "flex-start",
  },
  buttonText: { fontSize: 16, fontWeight: "700" },
});
