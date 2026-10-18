/**
 * Settings: which rubber duck teaches (server seven-day rule), comfort (always immediate),
 * and motion, sound, haptics, text-only and caption preferences (always immediate).
 *
 * The lock is whatever the server reports; this screen only renders the server's UTC instant
 * in local time beside the UTC value. Comfort and accessibility never depend on the lock, never
 * use up a style change, and work without a purchase. Every choice states its selection in
 * words, not only by color.
 */

import React, { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import {
  ANIMATION_PREFERENCES,
  PERSONALITIES,
  type AnimationPreference,
  type ComfortOverride,
  type HandholdMode,
  type Personality,
} from "../api/contracts";
import type { BoardTheme } from "../board/palette";
import type { MotionMode } from "../feedback/preferences";
import { RadioCard, ToggleRow } from "../components/ChoiceControls";
import { DuckPortrait } from "../components/DuckPortrait";
import { ScreenFrame } from "../components/ScreenFrame";
import { describeAvailability, formatInstant } from "../persona/availability";
import type { LearnerSettings } from "../state/useLearnerSettings";

import { PERSONALITY_INFO } from "./OnboardingScreen";

export type SettingsScreenProps = {
  settings: LearnerSettings;
  theme: BoardTheme;
  motion?: MotionMode;
  onClose: () => void;
  onOpenMemory: () => void;
  /** How much help the tutor gives on the current session. Applies immediately. */
  handhold?: HandholdMode;
  onChangeHandhold?: (mode: HandholdMode) => void;
  /** Overrides for deterministic tests; the device zone and locale are used otherwise. */
  timeZone?: string;
  locale?: string;
};

const HANDHOLD_OPTIONS: {
  value: HandholdMode;
  label: string;
  blurb: string;
}[] = [
  {
    value: "guided",
    label: "Guided",
    blurb: "Checks steps often and hints early.",
  },
  {
    value: "balanced",
    label: "Balanced",
    blurb: "Lets you try, then asks about a shaky assumption.",
  },
  {
    value: "hands_off",
    label: "Hands off",
    blurb: "Waits, and helps you test an idea without correcting it.",
  },
];

const COMFORT_OPTIONS: {
  value: ComfortOverride;
  label: string;
  blurb: string;
}[] = [
  {
    value: "none",
    label: "Use my chosen style",
    blurb: "Your tutor talks the way you picked.",
  },
  {
    value: "neutral_supportive",
    label: "Neutral and supportive",
    blurb: "Plain, warm wording whatever style you picked.",
  },
  {
    value: "reduced_sass",
    label: "Reduce the sass",
    blurb: "Keeps your style but takes the edge off.",
  },
];

const ANIMATION_OPTIONS: Record<
  AnimationPreference,
  { label: string; blurb: string }
> = {
  system: {
    label: "Follow my device",
    blurb: "Uses your device’s reduce-motion setting.",
  },
  full: {
    label: "Full motion",
    blurb: "Tutor marks appear one after another, briefly.",
  },
  reduced: {
    label: "Reduced motion",
    blurb: "Tutor marks appear all at once.",
  },
  off: {
    label: "No motion",
    blurb: "No animation at all; everything appears at once.",
  },
};

export function SettingsScreen({
  settings,
  theme,
  motion,
  onClose,
  onOpenMemory,
  handhold = "balanced",
  onChangeHandhold,
  timeZone,
  locale,
}: SettingsScreenProps) {
  const { persona, accessibility, refresh } = settings;
  const [pickedPersonality, setPersonality] = useState<Personality | null>(
    null,
  );

  useEffect(() => {
    void refresh();
    // Re-read the server's lock state each time this screen opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const storedPersonality = persona?.personality ?? null;
  const availability =
    persona === null
      ? null
      : describeAvailability(persona, { timeZone, locale });
  const locked = availability?.locked ?? true;
  // A pick is only shown while the server allows a change; otherwise the stored duck is.
  const personality = locked
    ? storedPersonality
    : (pickedPersonality ?? storedPersonality);
  const changed = personality !== null && personality !== storedPersonality;
  const canSave =
    persona !== null && !locked && changed && !settings.savingPair;
  const comfortUpdated =
    persona?.comfort_updated_at != null
      ? formatInstant(persona.comfort_updated_at, { timeZone, locale })
      : null;
  const text = { color: theme.labelText };
  const muted = { color: theme.labelMuted };
  const sectionCard = {
    backgroundColor: theme.surface,
    borderColor: theme.surfaceEdge,
  };

  return (
    <ScreenFrame
      theme={theme}
      motion={motion}
      testID="settings-screen"
      title="Settings"
      closeLabel="Back to board"
      onClose={onClose}
    >
      {settings.loadError !== null ? (
        <Text
          testID="settings-load-error"
          style={[styles.error, { color: theme.danger }]}
        >
          {settings.loadError}
        </Text>
      ) : null}

      <View style={[styles.section, sectionCard]}>
        <Text accessibilityRole="header" style={[styles.sectionTitle, text]}>
          Your tutor
        </Text>
        {persona === null ? (
          <Text style={[styles.note, muted]}>
            Your tutor’s settings are not available right now.
          </Text>
        ) : (
          <>
            <Text style={[styles.note, text]}>
              {PERSONALITY_INFO[persona.personality].name}
            </Text>
            <Text
              testID="persona-availability"
              accessibilityLiveRegion="polite"
              style={[styles.note, locked ? text : muted]}
            >
              {availability?.summary}
            </Text>
            <Text style={[styles.groupLabel, text]}>Rubber duck</Text>
            <View
              accessibilityRole="radiogroup"
              accessibilityLabel="Rubber duck"
              style={styles.cardRow}
            >
              {PERSONALITIES.map((option) => (
                <RadioCard
                  key={option}
                  testID={`settings-personality-${option}`}
                  label={`${PERSONALITY_INFO[option].name}. ${PERSONALITY_INFO[option].blurb}`}
                  selected={personality === option}
                  disabled={locked}
                  theme={theme}
                  onPress={() => setPersonality(option)}
                  style={styles.choiceCard}
                >
                  <View style={styles.portrait}>
                    <DuckPortrait personality={option} size={88} />
                  </View>
                  <Text style={[styles.cardTitle, text]}>
                    {PERSONALITY_INFO[option].name}
                  </Text>
                  <Text style={[styles.cardBlurb, muted]}>
                    {PERSONALITY_INFO[option].blurb}
                  </Text>
                </RadioCard>
              ))}
            </View>
            {settings.pairError !== null && !locked ? (
              <Text
                testID="settings-pair-error"
                style={[styles.error, { color: theme.danger }]}
              >
                {settings.pairError}
              </Text>
            ) : null}
            <Pressable
              testID="settings-save-persona"
              accessibilityRole="button"
              accessibilityLabel="Save rubber duck"
              accessibilityHint={
                locked
                  ? "Unavailable until the time shown above"
                  : "Uses up this week’s duck change"
              }
              accessibilityState={{ disabled: !canSave }}
              aria-disabled={!canSave}
              disabled={!canSave}
              onPress={() => {
                if (persona !== null && personality !== null) {
                  void settings.changePair(persona.appearance, personality);
                }
              }}
              style={[
                styles.button,
                {
                  backgroundColor: theme.controlBackground,
                  opacity: canSave ? 1 : 0.5,
                },
              ]}
            >
              <Text style={[styles.buttonText, { color: theme.controlText }]}>
                {settings.savingPair ? "Saving…" : "Save rubber duck"}
              </Text>
            </Pressable>
          </>
        )}
      </View>

      <View style={[styles.section, sectionCard]}>
        <Text accessibilityRole="header" style={[styles.sectionTitle, text]}>
          How much help
        </Text>
        <Text style={[styles.note, muted]}>
          Applies to the next reply. Still exploring, a question, and a hint
          stay on the chat.
        </Text>
        <View
          testID="settings-handhold-group"
          accessibilityRole="radiogroup"
          accessibilityLabel="How much help"
          style={styles.cardRow}
        >
          {HANDHOLD_OPTIONS.map((option) => (
            <RadioCard
              key={option.value}
              testID={`settings-handhold-${option.value}`}
              label={`${option.label}. ${option.blurb}`}
              selected={handhold === option.value}
              theme={theme}
              onPress={() => onChangeHandhold?.(option.value)}
              style={styles.choiceCard}
            >
              <Text style={[styles.cardTitle, text]}>{option.label}</Text>
              <Text style={[styles.cardBlurb, muted]}>{option.blurb}</Text>
            </RadioCard>
          ))}
        </View>
      </View>

      <View style={[styles.section, sectionCard]}>
        <Text accessibilityRole="header" style={[styles.sectionTitle, text]}>
          Comfort
        </Text>
        <Text style={[styles.note, muted]}>
          Applies from your tutor’s next reply. It is never locked and never
          uses up a style change.
        </Text>
        <View
          testID="settings-comfort-group"
          accessibilityRole="radiogroup"
          accessibilityLabel="Comfort"
          style={styles.cardRow}
        >
          {COMFORT_OPTIONS.map((option) => (
            <RadioCard
              key={option.value}
              testID={`settings-comfort-${option.value}`}
              label={`${option.label}. ${option.blurb}`}
              selected={persona?.comfort_override === option.value}
              disabled={persona === null}
              theme={theme}
              onPress={() => void settings.setComfort(option.value)}
              style={styles.choiceCard}
            >
              <Text style={[styles.cardTitle, text]}>{option.label}</Text>
              <Text style={[styles.cardBlurb, muted]}>{option.blurb}</Text>
            </RadioCard>
          ))}
        </View>
        {comfortUpdated !== null ? (
          <Text style={[styles.note, muted]}>
            Last changed {comfortUpdated.local ?? comfortUpdated.utc}
          </Text>
        ) : null}
        {settings.comfortError !== null ? (
          <Text
            testID="settings-comfort-error"
            style={[styles.error, { color: theme.danger }]}
          >
            {settings.comfortError}
          </Text>
        ) : null}
      </View>

      <View style={[styles.section, sectionCard]}>
        <Text accessibilityRole="header" style={[styles.sectionTitle, text]}>
          Motion, sound and text
        </Text>
        <Text style={[styles.note, muted]}>
          These save as you change them and never affect your tutor’s style or
          the lesson itself.
        </Text>
        <View
          testID="settings-motion-group"
          accessibilityRole="radiogroup"
          accessibilityLabel="Motion"
          style={styles.cardRow}
        >
          {ANIMATION_PREFERENCES.map((option) => (
            <RadioCard
              key={option}
              testID={`settings-animation-${option}`}
              label={`${ANIMATION_OPTIONS[option].label}. ${ANIMATION_OPTIONS[option].blurb}`}
              selected={accessibility.animation === option}
              theme={theme}
              onPress={() =>
                void settings.patchAccessibility({ animation: option })
              }
              style={styles.choiceCard}
            >
              <Text style={[styles.cardTitle, text]}>
                {ANIMATION_OPTIONS[option].label}
              </Text>
              <Text style={[styles.cardBlurb, muted]}>
                {ANIMATION_OPTIONS[option].blurb}
              </Text>
            </RadioCard>
          ))}
        </View>
        <ToggleRow
          testID="settings-sound"
          label="Sound"
          description="Tutor sounds. Off means nothing is ever played."
          value={accessibility.sound_enabled}
          theme={theme}
          onChange={(next) =>
            void settings.patchAccessibility({ sound_enabled: next })
          }
        />
        <ToggleRow
          testID="settings-haptics"
          label="Haptics"
          description="A gentle tap on supported devices. Devices without it do nothing."
          value={accessibility.haptics_enabled}
          theme={theme}
          onChange={(next) =>
            void settings.patchAccessibility({ haptics_enabled: next })
          }
        />
        <ToggleRow
          testID="settings-text-only"
          label="Text only"
          description="No sound, speech, microphone or camera. Everything stays in writing."
          value={accessibility.text_only}
          theme={theme}
          onChange={(next) =>
            void settings.patchAccessibility({ text_only: next })
          }
        />
        <ToggleRow
          testID="settings-captions"
          label="Captions"
          description="Show written captions for anything the tutor says aloud."
          value={accessibility.captions_enabled}
          theme={theme}
          onChange={(next) =>
            void settings.patchAccessibility({ captions_enabled: next })
          }
        />
        {settings.accessibilityError !== null ? (
          <Text
            testID="settings-accessibility-error"
            style={[styles.error, { color: theme.danger }]}
          >
            {settings.accessibilityError}
          </Text>
        ) : null}
      </View>

      <View style={[styles.section, sectionCard]}>
        <Text accessibilityRole="header" style={[styles.sectionTitle, text]}>
          Your data
        </Text>
        <Text style={[styles.note, muted]}>
          See what your tutor remembers, where it came from, and correct or
          delete it.
        </Text>
        <Pressable
          testID="settings-open-memory"
          accessibilityRole="button"
          accessibilityLabel="Open private memory"
          onPress={onOpenMemory}
          style={[styles.button, { backgroundColor: theme.controlBackground }]}
        >
          <Text style={[styles.buttonText, { color: theme.controlText }]}>
            Open private memory
          </Text>
        </Pressable>
      </View>
    </ScreenFrame>
  );
}

const styles = StyleSheet.create({
  section: { padding: 16, gap: 10, borderRadius: 28, borderWidth: 2 },
  sectionTitle: { fontSize: 20, fontWeight: "700" },
  groupLabel: { fontSize: 16, fontWeight: "700" },
  note: { fontSize: 15, lineHeight: 21 },
  error: { fontSize: 14, lineHeight: 20 },
  cardRow: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  choiceCard: { width: 200 },
  portrait: { alignSelf: "center" },
  cardTitle: { fontSize: 16, fontWeight: "700" },
  cardBlurb: { fontSize: 14, lineHeight: 19 },
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
