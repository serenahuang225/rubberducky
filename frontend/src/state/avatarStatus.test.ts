import { deriveAvatarStatus, type AvatarInputs } from "./avatarStatus";

const BASE: AvatarInputs = {
  busy: false,
  connectionLost: false,
  unsavedChanges: 0,
  failed: false,
  waiting: false,
  media: null,
  mediaAllowed: { listening: true, speaking: true },
};
const status = (patch: Partial<AvatarInputs>) =>
  deriveAvatarStatus({ ...BASE, ...patch });

describe("deriveAvatarStatus", () => {
  it("is idle when nothing is happening, and never invents listening or understanding", () => {
    const idle = status({});
    expect(idle.state).toBe("idle");
    expect(idle.label).not.toMatch(/listening|understand/i);
  });

  it("thinks only while a real tutor command is running", () => {
    expect(status({ busy: true }).state).toBe("thinking");
    expect(status({ busy: false }).state).toBe("idle");
  });

  it("waits when the learner explicitly said they are still thinking", () => {
    expect(status({ waiting: true }).state).toBe("waiting");
    expect(status({ waiting: true }).label).toMatch(/waiting/i);
  });

  it("reconnects when the tutor is unreachable or ink is still unsaved", () => {
    expect(status({ connectionLost: true }).state).toBe("reconnecting");
    expect(status({ unsavedChanges: 2 }).state).toBe("reconnecting");
    expect(status({ busy: true, connectionLost: true }).state).toBe(
      "reconnecting",
    );
  });

  it("shows an error for a rejected or failed command, but a lost connection wins", () => {
    expect(status({ failed: true }).state).toBe("error");
    expect(status({ failed: true, connectionLost: true }).state).toBe(
      "reconnecting",
    );
    expect(status({ failed: true }).label).toMatch(/went wrong|could not/i);
  });

  it("shows listening and speaking only from an explicit media event, labeled by source", () => {
    const listening = status({ media: { kind: "listening", source: "live" } });
    expect(listening.state).toBe("listening");
    expect(listening.simulated).toBe(false);
    const speaking = status({
      media: { kind: "speaking", source: "simulated" },
    });
    expect(speaking.state).toBe("speaking");
    expect(speaking.simulated).toBe(true);
    expect(speaking.label).toMatch(/simulated/i);
  });

  it("ignores media events when text-only, muted or unavailable so nothing is fabricated", () => {
    expect(
      status({
        media: { kind: "speaking", source: "live" },
        mediaAllowed: { listening: true, speaking: false },
      }).state,
    ).toBe("idle");
    expect(
      status({
        media: { kind: "listening", source: "simulated" },
        mediaAllowed: { listening: false, speaking: false },
      }).state,
    ).toBe("idle");
  });

  it("keeps thinking ahead of media and exposes accessible text for every state", () => {
    expect(
      status({ busy: true, media: { kind: "speaking", source: "live" } }).state,
    ).toBe("thinking");
    const all = [
      status({}),
      status({ busy: true }),
      status({ waiting: true }),
      status({ connectionLost: true }),
      status({ failed: true }),
      status({ media: { kind: "listening", source: "live" } }),
      status({ media: { kind: "speaking", source: "live" } }),
    ];
    expect(new Set(all.map((entry) => entry.state)).size).toBe(7);
    for (const entry of all) {
      expect(entry.label.length).toBeGreaterThan(3);
      expect(entry.description.length).toBeGreaterThan(10);
    }
  });
});
