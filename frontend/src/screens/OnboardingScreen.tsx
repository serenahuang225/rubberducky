/**
 * First-run onboarding: choose a companion look and a teaching style, independently.
 *
 * Three original appearances (animal, older adult, younger adult) and five rubber ducks
 * (Vincent, Zeeshan, Tony, Janelle, Mary) are separate axes — every pair is valid, and
 * no appearance is worded or styled as more capable than another. Each duck teaches
 * differently and stays respectful of the learner.
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
import { APPEARANCES, PERSONALITIES } from "../api/contracts";
import { getTheme } from "../board/palette";

import { AvatarFigure } from "../components/AvatarFigure";
import { RadioCard } from "../components/ChoiceControls";
import { DuckPortrait } from "../components/DuckPortrait";

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
    appearance: Appearance;
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
  const [appearance, setAppearance] = useState<Appearance | null>(null);
  const [personality, setPersonality] = useState<Personality | null>(null);

  const ready = appearance !== null && personality !== null && !submitting;

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.page}>
      <Text role="heading" style={styles.title}>
        Welcome to Rubberducky
      </Text>
      <Text style={styles.subtitle}>
        Pick a companion and a rubber duck. They are separate choices, every
        mix works, and every duck stays respectful of you.
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
          1. Choose a companion
        </Text>
        <View
          style={styles.cardRow}
          accessibilityRole="radiogroup"
          accessibilityLabel="Companion appearance"
        >
          {APPEARANCES.map((option) => {
            const info = APPEARANCE_INFO[option];
            const selected = appearance === option;
            return (
              <RadioCard
                key={option}
                testID={`appearance-${option}`}
                label={`${info.name}. ${info.blurb}`}
                selected={selected}
                theme={theme}
                onPress={() => setAppearance(option)}
                style={styles.card}
              >
                <AvatarFigure appearance={option} size={72} label={info.name} />
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

      <View style={styles.section}>
        <Text style={styles.sectionTitle} accessibilityRole="header">
          2. Choose a rubber duck
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
          if (appearance !== null && personality !== null) {
            onComplete({
              displayName: displayName.trim() || "Learner",
              appearance,
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
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: theme.board },
  page: {
    padding: 24,
    gap: 20,
    alignItems: "stretch",
    maxWidth: 900,
    width: "100%",
    alignSelf: "center",
  },
  title: { fontSize: 30, fontWeight: "700", color: "#1F2937" },
  subtitle: { fontSize: 16, lineHeight: 23, color: "#52606D" },
  section: { gap: 10 },
  sectionTitle: { fontSize: 19, fontWeight: "700", color: "#1F2937" },
  sectionNote: { fontSize: 14, color: "#52606D" },
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
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    fontSize: 16,
    backgroundColor: "#FFFFFF",
    maxWidth: 360,
  },
  error: { fontSize: 15 },
  startButton: {
    minHeight: 52,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "flex-start",
    paddingHorizontal: 28,
  },
  startText: { fontSize: 17, fontWeight: "700" },
});
