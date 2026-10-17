/**
 * Turns stored accessibility choices into the decisions the UI actually needs.
 *
 * Motion: "system" follows the device's reduce-motion setting; an explicit choice wins.
 * Feedback: mute and text-only silence audio; captions stay on in text-only mode because the
 * written words are then the only channel. Nothing here changes what the tutor teaches.
 */

import type {
  AccessibilityPreferences,
  AnimationPreference,
} from "../api/contracts";

export type MotionMode = "full" | "reduced";

export type FeedbackPermissions = {
  sound: boolean;
  haptics: boolean;
  captions: boolean;
  textOnly: boolean;
};

export function resolveMotion(
  animation: AnimationPreference,
  systemReducedMotion: boolean,
): MotionMode {
  switch (animation) {
    case "full":
      return "full";
    case "reduced":
    case "off":
      return "reduced";
    default:
      return systemReducedMotion ? "reduced" : "full";
  }
}

export function resolveFeedback(
  prefs: AccessibilityPreferences,
): FeedbackPermissions {
  return {
    sound: prefs.sound_enabled && !prefs.text_only,
    haptics: prefs.haptics_enabled,
    captions: prefs.captions_enabled || prefs.text_only,
    textOnly: prefs.text_only,
  };
}
