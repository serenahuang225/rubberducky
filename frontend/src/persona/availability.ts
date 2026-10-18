/**
 * Local rendering of the server's persona-change availability.
 *
 * Eligibility is decided only by the server (`persona_locked`, evaluated against its own UTC
 * clock). This module never compares an instant with the device clock; it only shows the
 * server's UTC instant in the learner's local zone next to the UTC value, so a changed
 * timezone, DST transition or skewed device clock cannot change what is reported.
 */

import type { PersonaState } from "../api/contracts";

export type InstantFormatOptions = { timeZone?: string; locale?: string };

export type FormattedInstant = { local: string | null; utc: string };

export type AvailabilityView = {
  locked: boolean;
  /** Local rendering of the next-change instant; null when not locked or not formattable. */
  local: string | null;
  /** The same instant in UTC, e.g. "2026-10-17 12:30 UTC". */
  utc: string | null;
  summary: string;
};

function pad(value: number): string {
  return value.toString().padStart(2, "0");
}

function utcLabel(date: Date): string {
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(
    date.getUTCHours(),
  )}:${pad(date.getUTCMinutes())} UTC`;
}

/** Local + UTC text for one server UTC instant; `local` is null if the zone cannot format. */
export function formatInstant(
  iso: string,
  options: InstantFormatOptions = {},
): FormattedInstant | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  let local: string | null = null;
  try {
    local = new Intl.DateTimeFormat(options.locale, {
      timeZone: options.timeZone,
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date);
  } catch {
    local = null;
  }
  return { local, utc: utcLabel(date) };
}

export function describeAvailability(
  persona: Pick<PersonaState, "persona_locked" | "next_change_available_at">,
  options: InstantFormatOptions = {},
): AvailabilityView {
  if (!persona.persona_locked) {
    return {
      locked: false,
      local: null,
      utc: null,
      summary:
        "Appearance and personality can change now. Comfort and accessibility can always change.",
    };
  }
  const instant =
    persona.next_change_available_at === null
      ? null
      : formatInstant(persona.next_change_available_at, options);
  if (instant === null) {
    return {
      locked: true,
      local: null,
      utc: null,
      summary:
        "Appearance and personality are locked and the next change time is not available. Comfort and accessibility can still change now.",
    };
  }
  const when =
    instant.local === null ? instant.utc : `${instant.local} (${instant.utc})`;
  return {
    locked: true,
    local: instant.local,
    utc: instant.utc,
    summary: `Appearance and personality can change again at ${when}. Comfort and accessibility can still change now.`,
  };
}
