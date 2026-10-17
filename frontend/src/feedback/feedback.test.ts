import type { AccessibilityPreferences } from "../api/contracts";
import { ACCESSIBILITY_DEFAULTS } from "../testing/agencyFixtures";
import { accessibilityPreferencesSchema } from "../api/contracts";

import { pulseHaptic, type HapticDriver } from "./haptics";
import { resolveFeedback, resolveMotion } from "./preferences";

const defaults = accessibilityPreferencesSchema.parse(ACCESSIBILITY_DEFAULTS);
const prefs = (
  patch: Partial<AccessibilityPreferences>,
): AccessibilityPreferences => ({
  ...defaults,
  ...patch,
});

describe("resolveMotion", () => {
  it('follows the device setting for "system"', () => {
    expect(resolveMotion("system", false)).toBe("full");
    expect(resolveMotion("system", true)).toBe("reduced");
  });
  it("honors an explicit choice over the device setting", () => {
    expect(resolveMotion("full", true)).toBe("full");
    expect(resolveMotion("reduced", false)).toBe("reduced");
    expect(resolveMotion("off", false)).toBe("reduced");
  });
});

describe("resolveFeedback", () => {
  it("allows sound, haptics and captions by default", () => {
    expect(resolveFeedback(defaults)).toEqual({
      sound: true,
      haptics: true,
      captions: true,
      textOnly: false,
    });
  });
  it("mute prevents sound but leaves captions and text", () => {
    const feedback = resolveFeedback(prefs({ sound_enabled: false }));
    expect(feedback.sound).toBe(false);
    expect(feedback.captions).toBe(true);
  });
  it("text-only turns off sound without changing the haptics choice", () => {
    const feedback = resolveFeedback(prefs({ text_only: true }));
    expect(feedback.sound).toBe(false);
    expect(feedback.textOnly).toBe(true);
    expect(feedback.haptics).toBe(true);
  });
  it("keeps captions available in text-only mode so instruction stays readable", () => {
    expect(
      resolveFeedback(prefs({ text_only: true, captions_enabled: false }))
        .captions,
    ).toBe(true);
  });
});

describe("pulseHaptic", () => {
  const driver = (): HapticDriver & { calls: string[] } => {
    const calls: string[] = [];
    return {
      calls,
      supported: () => true,
      async pulse(kind) {
        calls.push(kind);
      },
    };
  };

  it("makes no haptic call when haptics are disabled", async () => {
    const d = driver();
    await expect(
      pulseHaptic(prefs({ haptics_enabled: false }), "tutor_reply", d),
    ).resolves.toBe("disabled");
    expect(d.calls).toEqual([]);
  });

  it("plays one pulse when enabled and supported", async () => {
    const d = driver();
    await expect(pulseHaptic(defaults, "tutor_reply", d)).resolves.toBe(
      "played",
    );
    expect(d.calls).toEqual(["tutor_reply"]);
  });

  it("is a safe no-op on platforms without haptics", async () => {
    const d = { ...driver(), supported: () => false };
    await expect(pulseHaptic(defaults, "tutor_reply", d)).resolves.toBe(
      "unsupported",
    );
    expect(d.calls).toEqual([]);
  });

  it("swallows a driver failure instead of breaking the lesson", async () => {
    const d: HapticDriver = {
      supported: () => true,
      pulse: () => Promise.reject(new Error("Taptic engine unavailable")),
    };
    await expect(pulseHaptic(defaults, "tutor_reply", d)).resolves.toBe(
      "unsupported",
    );
  });
});
