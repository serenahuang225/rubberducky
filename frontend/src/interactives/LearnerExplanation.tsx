/**
 * Reachable learner control for a released explanation.
 *
 * The payload is parsed with the existing parser before the native manipulative mounts.
 * A missing or rejected payload leaves `children` (the board) in place and does not draw
 * the manipulative. Factory and Daytona states are named from the release; a fallback is
 * never given the generated label.
 */

import React, { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import type { BoardTheme } from "../board/palette";
import { getApiBaseUrl } from "../config/apiBaseUrl";
import { type } from "../theme/tokens";

import { ExplanationManipulative } from "./ExplanationManipulative";
import {
  fetchLearnerExplanation,
  integrationStateLabel,
  readLearnerExplanation,
  requestForConcept,
  UNAVAILABLE_EXPLANATION,
  type LearnerExplanationRequest,
  type ReleasedExplanation,
} from "./learnerRelease";

export type LoadLearnerExplanation = (request: LearnerExplanationRequest) => Promise<unknown>;

type ViewState =
  | { kind: "loading" }
  | { kind: "ready"; notice: string; release: ReleasedExplanation }
  | { kind: "error"; message: string };

function readyState(input: unknown): ViewState {
  const read = readLearnerExplanation(input);
  if (!read.ok) {
    return { kind: "error", message: read.error };
  }
  return { kind: "ready", notice: read.notice, release: read.release };
}

export type LearnerExplanationProps = {
  theme: BoardTheme;
  conceptId?: string | null;
  load?: LoadLearnerExplanation;
  payload?: unknown;
  children?: React.ReactNode;
};

export function LearnerExplanation({
  theme,
  conceptId,
  load,
  payload,
  children,
}: LearnerExplanationProps) {
  const [state, setState] = useState<ViewState>(() =>
    payload !== undefined ? readyState(payload) : { kind: "loading" },
  );

  useEffect(() => {
    if (payload !== undefined) {
      setState(readyState(payload));
      return;
    }
    let active = true;
    const request = requestForConcept(conceptId);
    const loader =
      load ??
      ((next: LearnerExplanationRequest) => fetchLearnerExplanation(getApiBaseUrl(), next));
    setState({ kind: "loading" });
    loader(request)
      .then((body) => {
        if (active) {
          setState(readyState(body));
        }
      })
      .catch(() => {
        if (active) {
          setState({ kind: "error", message: UNAVAILABLE_EXPLANATION });
        }
      });
    return () => {
      active = false;
    };
  }, [conceptId, load, payload]);

  const muted = { color: theme.labelMuted };
  const text = { color: theme.labelText };

  return (
    <View testID="learner-explanation" style={styles.block}>
      {children}
      {state.kind === "loading" ? (
        <Text testID="learner-explanation-status" style={[styles.note, muted]}>
          Loading the explanation…
        </Text>
      ) : null}
      {state.kind === "error" ? (
        <Text testID="learner-explanation-error" style={[styles.note, { color: theme.danger }]}>
          {state.message}
        </Text>
      ) : null}
      {state.kind === "ready" ? (
        <View style={styles.block}>
          {state.notice.length > 0 ? (
            <Text testID="learner-explanation-notice" style={[styles.note, muted]}>
              {state.notice}
            </Text>
          ) : null}
          <Text testID="factory-state-label" style={[styles.note, text]}>
            {integrationStateLabel("Factory", state.release.factory_state)}
          </Text>
          <Text testID="daytona-state-label" style={[styles.note, text]}>
            {integrationStateLabel("Daytona", state.release.daytona_state)}
          </Text>
          <ExplanationManipulative released={state.release} theme={theme} />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  block: { gap: 8 },
  note: type.small,
});
