import {
  PERSONA_STATE_LOCKED,
  PERSONA_STATE_OPEN,
} from "../testing/agencyFixtures";
import { personaStateSchema } from "../api/contracts";

import { describeAvailability, formatInstant } from "./availability";

const locked = personaStateSchema.parse(PERSONA_STATE_LOCKED);
const open = personaStateSchema.parse(PERSONA_STATE_OPEN);

describe("describeAvailability", () => {
  it("states the exact UTC instant and its local rendering while the server says locked", () => {
    const view = describeAvailability(locked, {
      timeZone: "America/Los_Angeles",
      locale: "en-US",
    });
    expect(view.locked).toBe(true);
    expect(view.utc).toBe("2026-10-17 12:30 UTC");
    expect(view.local).toMatch(/Oct(ober)? 17, 2026/);
    expect(view.local).toMatch(/5:30\s?AM/);
    expect(view.summary).toContain(view.local ?? "");
    expect(view.summary).toContain("2026-10-17 12:30 UTC");
    expect(view.summary).toMatch(/comfort and accessibility/i);
  });

  it("shows the same UTC instant across time zones, including across a DST change", () => {
    // 2026-11-01T06:30:00Z is just after US daylight saving ends (06:00Z).
    const dst = { ...locked, next_change_available_at: "2026-11-01T06:30:00Z" };
    const ny = describeAvailability(dst, {
      timeZone: "America/New_York",
      locale: "en-US",
    });
    const tokyo = describeAvailability(dst, {
      timeZone: "Asia/Tokyo",
      locale: "en-US",
    });
    expect(ny.local).toMatch(/1:30\s?AM/);
    expect(tokyo.local).toMatch(/3:30\s?PM/);
    expect(ny.utc).toBe(tokyo.utc);
    expect(ny.utc).toBe("2026-11-01 06:30 UTC");
  });

  it("never derives eligibility from the device clock", () => {
    jest.useFakeTimers();
    try {
      jest.setSystemTime(new Date("2030-01-01T00:00:00Z"));
      expect(
        describeAvailability(locked, { timeZone: "UTC", locale: "en-US" })
          .locked,
      ).toBe(true);
      jest.setSystemTime(new Date("2020-01-01T00:00:00Z"));
      expect(
        describeAvailability(open, { timeZone: "UTC", locale: "en-US" }).locked,
      ).toBe(false);
    } finally {
      jest.useRealTimers();
    }
  });

  it("reports availability now when the server says the pair can change", () => {
    const view = describeAvailability(open, {
      timeZone: "UTC",
      locale: "en-US",
    });
    expect(view.locked).toBe(false);
    expect(view.local).toBeNull();
    expect(view.summary).toMatch(/can change now/i);
  });

  it("falls back to the UTC instant when local formatting is unavailable", () => {
    expect(
      formatInstant("2026-10-17T12:30:00Z", {
        timeZone: "Not/AZone",
        locale: "en-US",
      }),
    ).toEqual({
      local: null,
      utc: "2026-10-17 12:30 UTC",
    });
  });

  it("is honest when a locked state lacks a usable instant", () => {
    const view = describeAvailability(
      { ...locked, next_change_available_at: null },
      {},
    );
    expect(view.locked).toBe(true);
    expect(view.summary).toMatch(/time is not available/i);
  });
});
