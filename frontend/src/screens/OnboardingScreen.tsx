/**
 * First-run onboarding: choose which rubber duck teaches.
 *
 * Vincent, Zeeshan, Tony, Janelle, and Mary each teach differently and stay
 * respectful of the learner. The duck never implies what the learner can do.
 */

import React, { useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  useWindowDimensions,
} from "react-native";

import type { Personality } from "../api/contracts";
import { PERSONALITIES } from "../api/contracts";
import { getTheme } from "../board/palette";

import { font } from "../theme/tokens";

import { RadioCard } from "../components/ChoiceControls";
import { DuckPortrait } from "../components/DuckPortrait";

export const PERSONALITY_INFO: Record<
  Personality,
  { name: string; blurb: string }
> = {
  vincent: {
    name: "Vincent",
    blurb: "Walks the problem one step at a time. You say what comes next.",
  },
  zeeshan: {
    name: "Zeeshan",
    blurb:
      "Hard mode. He will not answer until you ask, and he needles you first. Helpful once you do.",
  },
  tony: {
    name: "Tony",
    blurb: "Follows your idea and keeps going with it, even after the track runs out.",
  },
  janelle: {
    name: "Janelle",
    blurb: "Guides you fully and asks questions that make you think.",
  },
  mary: {
    name: "Mary",
    blurb: "Less guidance and no direct hints. She tells you where you are, like a navigator.",
  },
};

export type OnboardingScreenProps = {
  submitting: boolean;
  errorMessage: string | null;
  /** Preselected values when the learner is paired but has no persona yet. */
  showNameField: boolean;
  onComplete: (choices: {
    displayName: string;
    personality: Personality;
  }) => void;
};

const theme = getTheme("paper");

export function OnboardingScreen({
  submitting,
  errorMessage,
  showNameField,
  onComplete,
}: OnboardingScreenProps) {
  const { width } = useWindowDimensions();
  const compact = width < 700;
  const [displayName, setDisplayName] = useState("");
  const [personality, setPersonality] = useState<Personality | null>(null);

  const ready = personality !== null && !submitting;

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.page}>
      <View style={[styles.column, compact && styles.compactColumn]}>
      <View style={styles.header}>
      <Text role="heading" style={styles.title}>
        Welcome to Rubber Ducky
      </Text>
      <Text style={styles.subtitle}>
        Pick a rubber duck. Every duck stays respectful of you.
      </Text>

      </View>

      {showNameField ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>
            What should your tutor call you?
          </Text>
          <TextInput
            testID="onboarding-name"
            accessibilityLabel="Your name or nickname"
            value={displayName}
            onChangeText={setDisplayName}
            placeholder="Your name or nickname"
            placeholderTextColor={theme.labelMuted}
            maxLength={60}
            style={[
              styles.nameInput,
              { borderColor: theme.controlEdge, color: theme.labelText },
            ]}
          />
        </View>
      ) : null}

      <View style={styles.section}>
        <Text style={styles.sectionTitle} accessibilityRole="header">
          Choose a rubber duck
        </Text>
        <Text style={styles.sectionNote}>
          Style changes how your tutor talks, never what it thinks you can do.
        </Text>
        <View
          style={styles.cardRow}
          accessibilityRole="radiogroup"
          accessibilityLabel="Rubber duck"
        >
          {PERSONALITIES.map((option) => {
            const info = PERSONALITY_INFO[option];
            const selected = personality === option;
            return (
              <RadioCard
                key={option}
                testID={`personality-${option}`}
                label={`${info.name}. ${info.blurb}`}
                selected={selected}
                theme={theme}
                onPress={() => setPersonality(option)}
                style={[styles.card, compact && styles.compactCard, {
                  backgroundColor: selected ? "#EDF6FF" : "#FFFFFF",
                  borderColor: selected ? theme.controlBackground : "#DCE6EF",
                  borderWidth: 2,
                }]}
              >
                <View style={styles.cardContent}>
                <View style={styles.portrait}>
                  <DuckPortrait personality={option} size={compact ? 80 : 96} />
                </View>
                <View style={styles.cardCopy}>
                <Text style={[styles.cardTitle, { color: theme.labelText }]}>
                  {info.name}
                </Text>
                <Text style={[styles.cardBlurb, { color: theme.labelMuted }]}>
                  {info.blurb}
                </Text>
                </View>
                </View>
              </RadioCard>
            );
          })}
        </View>
      </View>

      {errorMessage !== null ? (
        <Text
          testID="onboarding-error"
          style={[styles.error, { color: theme.danger }]}
        >
          {errorMessage}
        </Text>
      ) : null}

      <Pressable
        testID="onboarding-start"
        accessibilityRole="button"
        accessibilityLabel="Start learning"
        accessibilityState={{ disabled: !ready }}
        disabled={!ready}
        onPress={() => {
          if (personality !== null) {
            onComplete({
              displayName: displayName.trim() || "Learner",
              personality,
            });
          }
        }}
        style={[
          styles.startButton,
          {
            backgroundColor: theme.controlBackground,
            opacity: ready ? 1 : 0.5,
          },
        ]}
      >
        <Text style={[styles.startText, { color: theme.controlText }]}>
          {submitting ? "Setting up…" : "Start learning"}
        </Text>
      </Pressable>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, alignSelf: "stretch", backgroundColor: theme.board },
  page: { width: "100%", flexGrow: 1 },
  column: {
    paddingHorizontal: 40,
    paddingTop: 56,
    paddingBottom: 48,
    gap: 36,
    alignItems: "stretch",
    maxWidth: 1080,
    width: "100%",
    alignSelf: "center",
  },
  compactColumn: { paddingHorizontal: 20, paddingTop: 32, gap: 28 },
  header: { gap: 12 },
  title: { fontFamily: font.display, fontSize: 36, lineHeight: 44, fontWeight: "700", color: theme.labelText },
  subtitle: { fontFamily: font.sans, fontSize: 17, lineHeight: 26, color: theme.labelMuted },
  section: { gap: 14 },
  sectionTitle: { fontFamily: font.display, fontSize: 21, lineHeight: 28, fontWeight: "700", color: theme.labelText },
  sectionNote: { fontFamily: font.sans, fontSize: 15, lineHeight: 22, color: theme.labelMuted, marginBottom: 8 },
  cardRow: { flexDirection: "row", flexWrap: "wrap", gap: 16 },
  card: {
    flexBasis: "47%",
    flexGrow: 1,
    maxWidth: "49%",
    padding: 20,
    gap: 12,
    borderRadius: 24,
    justifyContent: "space-between",
  },
  compactCard: { flexBasis: "100%", maxWidth: "100%", padding: 16 },
  cardContent: { flexDirection: "row", alignItems: "center", gap: 18 },
  portrait: { flexShrink: 0 },
  cardCopy: { flex: 1, gap: 8 },
  cardTitle: { fontFamily: font.display, fontSize: 20, lineHeight: 26, fontWeight: "700", textAlign: "left" },
  cardBlurb: { fontFamily: font.sans, fontSize: 14, lineHeight: 22, textAlign: "left" },
  nameInput: {
    fontFamily: font.sans,
    minHeight: 54,
    borderWidth: 2,
    borderRadius: 28,
    paddingHorizontal: 14,
    fontSize: 16,
    backgroundColor: "#FFFFFF",
    maxWidth: 360,
  },
  error: { fontFamily: font.sans, fontSize: 15 },
  startButton: {
    minHeight: 52,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "flex-start",
    paddingHorizontal: 28,
  },
  startText: { fontFamily: font.sans, fontSize: 17, fontWeight: "700" },
});
