/**
 * First-run onboarding: choose a companion look and a teaching style, independently.
 *
 * Three original appearances (animal, older adult, younger adult) and four personalities
 * (gentle, matter-of-fact, playful, mildly sassy) are separate axes — every one of the
 * twelve pairs is valid, and no appearance is worded or styled as more capable than
 * another. Every personality stays kind and respectful, including the sassy one.
 */

import React, { useState } from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import type { Appearance, Personality } from '../api/contracts';
import { APPEARANCES, PERSONALITIES } from '../api/contracts';
import { getTheme } from '../board/palette';

import { AvatarFigure } from '../components/AvatarFigure';

export const APPEARANCE_INFO: Record<Appearance, { name: string; blurb: string }> = {
  animal: {
    name: 'Sunny the duck',
    blurb: 'A cheerful duck who floats along beside you.',
  },
  older_adult: {
    name: 'Rowan',
    blurb: 'A calm, unhurried companion with warm glasses.',
  },
  younger_adult: {
    name: 'Kai',
    blurb: 'An easygoing study buddy in a comfy hoodie.',
  },
};

export const PERSONALITY_INFO: Record<Personality, { name: string; blurb: string }> = {
  gentle: {
    name: 'Gentle',
    blurb: 'Soft-spoken and patient, with plenty of room to think.',
  },
  matter_of_fact: {
    name: 'Matter-of-fact',
    blurb: 'Clear, direct and steady. Says exactly what matters.',
  },
  playful: {
    name: 'Playful',
    blurb: 'Curious and light-hearted. Problems are puzzles here.',
  },
  mildly_sassy: {
    name: 'Mildly sassy',
    blurb: 'A little cheeky about the problem — always kind to you.',
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

const theme = getTheme('paper');

export function OnboardingScreen({
  submitting,
  errorMessage,
  showNameField,
  onComplete,
}: OnboardingScreenProps) {
  const [displayName, setDisplayName] = useState('');
  const [appearance, setAppearance] = useState<Appearance | null>(null);
  const [personality, setPersonality] = useState<Personality | null>(null);

  const ready = appearance !== null && personality !== null && !submitting;

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.page}>
      <Text role="heading" style={styles.title}>
        Welcome to Rubberducky
      </Text>
      <Text style={styles.subtitle}>
        Pick a companion and a teaching style. They are separate choices, every mix works,
        and every style is kind and respectful.
      </Text>

      {showNameField ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>What should your tutor call you?</Text>
          <TextInput
            testID="onboarding-name"
            accessibilityLabel="Your name or nickname"
            value={displayName}
            onChangeText={setDisplayName}
            placeholder="Your name or nickname"
            placeholderTextColor={theme.labelMuted}
            maxLength={60}
            style={[styles.nameInput, { borderColor: theme.surfaceEdge, color: theme.labelText }]}
          />
        </View>
      ) : null}

      <View style={styles.section}>
        <Text style={styles.sectionTitle} accessibilityRole="header">
          1. Choose a companion
        </Text>
        <View style={styles.cardRow} accessibilityRole="radiogroup" accessibilityLabel="Companion appearance">
          {APPEARANCES.map((option) => {
            const info = APPEARANCE_INFO[option];
            const selected = appearance === option;
            return (
              <Pressable
                key={option}
                testID={`appearance-${option}`}
                accessibilityRole="radio"
                accessibilityLabel={`${info.name}. ${info.blurb}`}
                accessibilityState={{ selected, checked: selected }}
                onPress={() => setAppearance(option)}
                style={[
                  styles.card,
                  {
                    borderColor: selected ? theme.controlBackground : theme.surfaceEdge,
                    backgroundColor: selected ? '#EEF4FB' : theme.surface,
                  },
                ]}
              >
                <AvatarFigure appearance={option} size={72} label={info.name} />
                <Text style={[styles.cardTitle, { color: theme.labelText }]}>{info.name}</Text>
                <Text style={[styles.cardBlurb, { color: theme.labelMuted }]}>{info.blurb}</Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle} accessibilityRole="header">
          2. Choose a teaching style
        </Text>
        <Text style={styles.sectionNote}>
          Style changes how your tutor talks, never what it thinks you can do.
        </Text>
        <View style={styles.cardRow} accessibilityRole="radiogroup" accessibilityLabel="Teaching style">
          {PERSONALITIES.map((option) => {
            const info = PERSONALITY_INFO[option];
            const selected = personality === option;
            return (
              <Pressable
                key={option}
                testID={`personality-${option}`}
                accessibilityRole="radio"
                accessibilityLabel={`${info.name}. ${info.blurb}`}
                accessibilityState={{ selected, checked: selected }}
                onPress={() => setPersonality(option)}
                style={[
                  styles.card,
                  styles.personalityCard,
                  {
                    borderColor: selected ? theme.controlBackground : theme.surfaceEdge,
                    backgroundColor: selected ? '#EEF4FB' : theme.surface,
                  },
                ]}
              >
                <Text style={[styles.cardTitle, { color: theme.labelText }]}>{info.name}</Text>
                <Text style={[styles.cardBlurb, { color: theme.labelMuted }]}>{info.blurb}</Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      {errorMessage !== null ? (
        <Text testID="onboarding-error" style={[styles.error, { color: theme.danger }]}>
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
              displayName: displayName.trim() || 'Learner',
              appearance,
              personality,
            });
          }
        }}
        style={[
          styles.startButton,
          { backgroundColor: theme.controlBackground, opacity: ready ? 1 : 0.5 },
        ]}
      >
        <Text style={[styles.startText, { color: theme.controlText }]}>
          {submitting ? 'Setting up…' : 'Start learning'}
        </Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: '#FCFCFA' },
  page: {
    padding: 24,
    gap: 20,
    alignItems: 'stretch',
    maxWidth: 900,
    width: '100%',
    alignSelf: 'center',
  },
  title: { fontSize: 30, fontWeight: '700', color: '#1F2937' },
  subtitle: { fontSize: 16, lineHeight: 23, color: '#52606D' },
  section: { gap: 10 },
  sectionTitle: { fontSize: 19, fontWeight: '700', color: '#1F2937' },
  sectionNote: { fontSize: 14, color: '#52606D' },
  cardRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  card: {
    width: 180,
    minHeight: 44,
    padding: 14,
    gap: 8,
    borderRadius: 14,
    borderWidth: 2,
    alignItems: 'center',
  },
  personalityCard: { alignItems: 'flex-start' },
  cardTitle: { fontSize: 17, fontWeight: '700' },
  cardBlurb: { fontSize: 14, lineHeight: 20, textAlign: 'center' },
  nameInput: {
    minHeight: 48,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    fontSize: 16,
    backgroundColor: '#FFFFFF',
    maxWidth: 360,
  },
  error: { fontSize: 15 },
  startButton: {
    minHeight: 52,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'flex-start',
    paddingHorizontal: 28,
  },
  startText: { fontSize: 17, fontWeight: '700' },
});
