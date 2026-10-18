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
} from "react-native";

import type { Appearance, Personality } from "../api/contracts";
import { PERSONALITIES } from "../api/contracts";
import { getTheme } from "../board/palette";

import { RadioCard } from "../components/ChoiceControls";
import { DuckPortrait } from "../components/DuckPortrait";

/** Kept for the board header until that screen stops naming the old companions. */
export const APPEARANCE_INFO: Record<
  Appearance,
  { name: string; blurb: string }
> = {
  animal: {
    name: "Sunny the duck",
    blurb: "A cheerful duck who floats along beside you.",
  },
  older_adult: {
    name: "Rowan",
    blurb: "A calm, unhurried companion with warm glasses.",
  },
  younger_adult: {
    name: "Kai",
    blurb: "An easygoing study buddy in a comfy hoodie.",
  },
};

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
  const [displayName, setDisplayName] = useState("");
  const [personality, setPersonality] = useState<Personality | null>(null);

  const ready = personality !== null && !submitting;

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.page}>
      <View style={styles.column}>
      <Text role="heading" style={styles.title}>
        Welcome to Rubberducky
      </Text>
      <Text style={styles.subtitle}>
        Pick a rubber duck. Every duck stays respectful of you.
      </Text>

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
                style={[styles.card, styles.personalityCard]}
              >
                <View style={styles.portrait}>
                  <DuckPortrait personality={option} size={104} />
                </View>
                <Text style={[styles.cardTitle, { color: theme.labelText }]}>
                  {info.name}
                </Text>
                <Text style={[styles.cardBlurb, { color: theme.labelMuted }]}>
                  {info.blurb}
                </Text>
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
    padding: 24,
    gap: 20,
    alignItems: "stretch",
    maxWidth: 900,
    width: "100%",
    alignSelf: "center",
  },
  title: { fontSize: 30, fontWeight: "700", color: theme.labelText },
  subtitle: { fontSize: 16, lineHeight: 23, color: theme.labelMuted },
  section: { gap: 10 },
  sectionTitle: { fontSize: 19, fontWeight: "700", color: theme.labelText },
  sectionNote: { fontSize: 14, color: theme.labelMuted },
  cardRow: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  card: {
    width: 180,
    alignItems: "center",
  },
  personalityCard: { alignItems: "flex-start" },
  portrait: { alignSelf: "center" },
  cardTitle: { fontSize: 17, fontWeight: "700" },
  cardBlurb: { fontSize: 14, lineHeight: 20, textAlign: "center" },
  nameInput: {
    minHeight: 48,
    borderWidth: 2,
    borderRadius: 28,
    paddingHorizontal: 14,
    fontSize: 16,
    backgroundColor: "#FFFFFF",
    maxWidth: 360,
  },
  error: { fontSize: 15 },
  startButton: {
    minHeight: 52,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "flex-start",
    paddingHorizontal: 28,
  },
  startText: { fontSize: 17, fontWeight: "700" },
});
