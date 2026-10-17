/**
 * Optional haptic feedback. A pulse is only ever a nicety: the lesson never depends on it,
 * disabled haptics make no call at all, and a platform without haptics (the web, a device
 * without a Taptic engine) or a driver failure is a quiet no-op.
 */

import * as Haptics from "expo-haptics";
import { Platform } from "react-native";

import type { AccessibilityPreferences } from "../api/contracts";

export type HapticKind = "tutor_reply";
export type HapticOutcome = "played" | "disabled" | "unsupported";

export type HapticDriver = {
  supported: () => boolean;
  pulse: (kind: HapticKind) => Promise<void>;
};

export const expoHapticDriver: HapticDriver = {
  supported: () => Platform.OS === "ios" || Platform.OS === "android",
  pulse: () => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light),
};

export async function pulseHaptic(
  prefs: Pick<AccessibilityPreferences, "haptics_enabled">,
  kind: HapticKind,
  driver: HapticDriver = expoHapticDriver,
): Promise<HapticOutcome> {
  if (!prefs.haptics_enabled) return "disabled";
  if (!driver.supported()) return "unsupported";
  try {
    await driver.pulse(kind);
    return "played";
  } catch {
    return "unsupported";
  }
}
