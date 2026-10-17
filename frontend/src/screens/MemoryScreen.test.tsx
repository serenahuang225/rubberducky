/**
 * The private memory view through the REAL ApiClient against a transport double that records
 * every request and answers like the backend: derived updates must come from the server's
 * receipts and re-read, deletions need an explicit second step, and the inspection bound is
 * described per kind, not as a total.
 */

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import React from "react";

import { ApiClient } from "../api/client";
import { getTheme } from "../board/palette";
import {
  ESTIMATE_ITEM,
  EVIDENCE_CORRECTION_RECEIPT,
  EVIDENCE_ITEM,
  INSPECTION,
  NOTE_DELETION_RECEIPT,
  NOTE_ITEM,
  PROFILE_REMOVAL_RECEIPT,
  SESSION_REMOVAL_RECEIPT,
} from "../testing/agencyFixtures";

import { MemoryScreen } from "./MemoryScreen";

type Recorded = { method: string; url: string; body: unknown };

const SESSIONS = [
  {
    schema_version: "session.v1",
    id: "s1",
    learner_id: "learner-1",
    status: "active",
    goal: null,
    revision: 3,
    started_at: "2026-10-12T08:00:00Z",
    ended_at: null,
  },
  {
    schema_version: "session.v1",
    id: "s0",
    learner_id: "learner-1",
    status: "ended",
    goal: null,
    revision: 9,
    started_at: "2026-10-10T12:00:00Z",
    ended_at: "2026-10-10T12:50:00Z",
  },
];

function makeBackend() {
  const state = {
    items: [NOTE_ITEM, EVIDENCE_ITEM, ESTIMATE_ITEM] as unknown[],
    requests: [] as Recorded[],
    failInspect: false,
  };
  const respond = (status: number, body: unknown) =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }) as Response;
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace("http://api", "");
    const method = init?.method ?? "GET";
    state.requests.push({
      method,
      url,
      body:
        init?.body === undefined ? undefined : JSON.parse(String(init.body)),
    });
    if (url.startsWith("/memory/inspect")) {
      if (state.failInspect) throw new TypeError("Network request failed");
      const limit = Number(
        new URL(`http://x${url}`).searchParams.get("limit") ?? 20,
      );
      return respond(200, { ...INSPECTION, limit, items: state.items });
    }
    if (url === "/sessions") return respond(200, SESSIONS);
    if (method === "DELETE" && url === "/memory/notes/mem-1") {
      state.items = state.items.filter(
        (item) => (item as { id: string }).id !== "mem-1",
      );
      return respond(200, NOTE_DELETION_RECEIPT);
    }
    if (method === "POST" && url === "/memory/evidence/obs-1/correction") {
      return respond(200, EVIDENCE_CORRECTION_RECEIPT);
    }
    if (method === "POST" && url === "/memory/notes/mem-1/correction") {
      state.items = state.items.map((item) =>
        (item as { id: string }).id === "mem-1"
          ? {
              ...NOTE_ITEM,
              id: "mem-2",
              summary: "I distributed to both terms.",
              origin: "learner",
              epistemic_status: "self_report",
              supersedes_id: "mem-1",
              correction: {
                original: NOTE_ITEM.summary,
                current: "I distributed to both terms.",
                corrected_at: "2026-10-12T09:10:00Z",
              },
            }
          : item,
      );
      return respond(200, {
        schema_version: "memory-correction.v1",
        kind: "note",
        record_id: "mem-1",
        changed: true,
        replacement_id: "mem-2",
        original: NOTE_ITEM.summary,
        current: "I distributed to both terms.",
        effects: EVIDENCE_CORRECTION_RECEIPT.effects,
      });
    }
    if (method === "DELETE" && url === "/sessions/s0")
      return respond(200, { ...SESSION_REMOVAL_RECEIPT, record_id: "s0" });
    if (method === "DELETE" && url === "/sessions/s1")
      return respond(200, SESSION_REMOVAL_RECEIPT);
    if (method === "DELETE" && url === "/me?confirm=delete-my-profile")
      return respond(200, PROFILE_REMOVAL_RECEIPT);
    return respond(404, {
      schema_version: "error.v1",
      error: { code: "not_found", message: url },
    });
  }) as typeof fetch;
  return { state, client: new ApiClient("http://api", "tok", fetchImpl) };
}

function setup() {
  const made = makeBackend();
  const props = {
    onClose: jest.fn(),
    onSessionRemoved: jest.fn(),
    onProfileDeleted: jest.fn(),
  };
  render(
    <MemoryScreen
      client={made.client}
      currentSessionId="s1"
      theme={getTheme("paper")}
      timeZone="UTC"
      locale="en-US"
      {...props}
    />,
  );
  return { ...made, props };
}

async function loaded() {
  await waitFor(() => expect(screen.getByTestId("memory-items")).toBeTruthy());
}

describe("MemoryScreen", () => {
  it("shows what is remembered by kind with source, uncertainty and why it matters", async () => {
    setup();
    await loaded();
    expect(screen.getByText("Notes the tutor kept")).toBeTruthy();
    expect(screen.getByText("Evidence from your work")).toBeTruthy();
    expect(screen.getByText("Estimates (uncalibrated)")).toBeTruthy();
    const note = screen.getByTestId("memory-item-mem-1");
    expect(note).toHaveTextContent(/Distributing over a sum/);
    expect(note).toHaveTextContent(/Your step "2x \+ 3 = 14"/);
    expect(note).toHaveTextContent(/moderate confidence \(60%\)/i);
    expect(note).toHaveTextContent(/Uncertainty: One attempt only\./);
    expect(note).toHaveTextContent(/Used to choose a hint/);
    expect(note).toHaveTextContent(/inference/i);
  });

  it("states the inspection bound per kind, and raises it only on request", async () => {
    const { state } = setup();
    await loaded();
    expect(screen.getByTestId("memory-bound")).toHaveTextContent(
      /up to 20 of each kind/i,
    );
    expect(screen.getByTestId("memory-bound")).not.toHaveTextContent(
      /20 items in total/i,
    );
    fireEvent.press(
      screen.getByRole("button", { name: "Show more of each kind" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("memory-bound")).toHaveTextContent(
        /up to 50 of each kind/i,
      ),
    );
    expect(state.requests.some((r) => r.url.includes("limit=50"))).toBe(true);
    expect(
      screen.queryByRole("button", { name: "Show more of each kind" }),
    ).toBeNull();
  });

  it("offers no correction or deletion for derived estimates, and explains how they change", async () => {
    setup();
    await loaded();
    const estimate = screen.getByTestId("memory-item-est-1");
    expect(estimate).toHaveTextContent(/uncalibrated/i);
    expect(estimate).toHaveTextContent(/correct or delete the evidence/i);
    expect(
      screen.queryByRole("button", { name: /Delete .*Distribution estimate/ }),
    ).toBeNull();
  });

  it("needs a second step to delete, can be cancelled, and shows the server receipt and re-read", async () => {
    const { state } = setup();
    await loaded();
    fireEvent.press(
      screen.getByRole("button", { name: "Delete: Distributing over a sum" }),
    );
    fireEvent.press(
      screen.getByRole("button", { name: "Keep it: Distributing over a sum" }),
    );
    expect(state.requests.some((r) => r.method === "DELETE")).toBe(false);
    expect(screen.getByTestId("memory-item-mem-1")).toBeTruthy();

    fireEvent.press(
      screen.getByRole("button", { name: "Delete: Distributing over a sum" }),
    );
    fireEvent.press(
      screen.getByRole("button", {
        name: "Yes, delete: Distributing over a sum",
      }),
    );
    await screen.findByTestId("memory-change");
    await waitFor(() =>
      expect(screen.queryByTestId("memory-item-mem-1")).toBeNull(),
    );
    expect(state.requests.filter((r) => r.method === "DELETE")).toEqual([
      { method: "DELETE", url: "/memory/notes/mem-1", body: undefined },
    ]);
    const change = screen.getByTestId("memory-change");
    expect(change).toHaveTextContent(/Deleted/);
    expect(change).toHaveTextContent(/1 item removed/);
    expect(change).toHaveTextContent(/no deleted text is retained/i);
  });

  it("marks evidence right or wrong and shows the recomputed estimate from the receipt", async () => {
    const { state } = setup();
    await loaded();
    fireEvent.press(
      screen.getByRole("button", { name: "This was right: Step check" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("memory-change")).toHaveTextContent(/67%/),
    );
    expect(
      state.requests.find((r) => r.url === "/memory/evidence/obs-1/correction"),
    ).toMatchObject({
      method: "POST",
      body: { correct: true },
    });
    expect(screen.getByTestId("memory-change")).toHaveTextContent(/withdrawn/);
  });

  it("corrects a note in the learner’s own words and shows the distinguishable replacement", async () => {
    const { state } = setup();
    await loaded();
    fireEvent.press(
      screen.getByRole("button", {
        name: "Correct wording: Distributing over a sum",
      }),
    );
    const input = screen.getByLabelText("Your corrected wording");
    fireEvent.changeText(input, "I distributed to both terms.");
    fireEvent.press(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() =>
      expect(screen.getByTestId("memory-item-mem-2")).toBeTruthy(),
    );
    expect(
      state.requests.find((r) => r.url === "/memory/notes/mem-1/correction")
        ?.body,
    ).toEqual({
      content: "I distributed to both terms.",
    });
    const replacement = screen.getByTestId("memory-item-mem-2");
    expect(replacement).toHaveTextContent(/your own words|self.report/i);
    expect(replacement).toHaveTextContent(/You corrected/i);
    expect(replacement).toHaveTextContent(
      /Before: “You distributed the 2 to the first term only\.”/,
    );
  });

  it("does not send an empty correction", async () => {
    const { state } = setup();
    await loaded();
    fireEvent.press(
      screen.getByRole("button", {
        name: "Correct wording: Distributing over a sum",
      }),
    );
    fireEvent.press(screen.getByRole("button", { name: "Save correction" }));
    expect(state.requests.some((r) => r.url.endsWith("/correction"))).toBe(
      false,
    );
  });

  it("removes a session after confirmation and tells the app whether it was the current one", async () => {
    const { props, state } = setup();
    await loaded();
    fireEvent.press(
      screen.getByRole("button", { name: "Remove session from Oct 10, 2026" }),
    );
    fireEvent.press(
      screen.getByRole("button", {
        name: "Yes, remove session from Oct 10, 2026",
      }),
    );
    await waitFor(() =>
      expect(props.onSessionRemoved).toHaveBeenCalledWith("s0", false),
    );
    expect(
      state.requests.some(
        (r) => r.method === "DELETE" && r.url === "/sessions/s0",
      ),
    ).toBe(true);

    fireEvent.press(
      screen.getByRole("button", {
        name: "Remove session from Oct 12, 2026 (current)",
      }),
    );
    fireEvent.press(
      screen.getByRole("button", {
        name: "Yes, remove session from Oct 12, 2026 (current)",
      }),
    );
    await waitFor(() =>
      expect(props.onSessionRemoved).toHaveBeenCalledWith("s1", true),
    );
  });

  it("deletes the whole profile only after an explicit confirmation, and hands the receipt to the app", async () => {
    const { props, state } = setup();
    await loaded();
    fireEvent.press(screen.getByRole("button", { name: "Delete my profile" }));
    expect(state.requests.some((r) => r.url.startsWith("/me?"))).toBe(false);
    expect(screen.getByTestId("profile-delete-warning")).toHaveTextContent(
      /not secure disk, backup or vendor erasure/i,
    );
    await act(async () => {
      fireEvent.press(
        screen.getByRole("button", { name: "Yes, delete my profile" }),
      );
    });
    await waitFor(() =>
      expect(props.onProfileDeleted).toHaveBeenCalledTimes(1),
    );
    expect(props.onProfileDeleted.mock.calls[0][0].title).toMatch(
      /Profile removed/,
    );
    expect(
      state.requests.some(
        (r) =>
          r.method === "DELETE" && r.url === "/me?confirm=delete-my-profile",
      ),
    ).toBe(true);
  });

  it("says so and offers a retry when memory cannot be loaded", async () => {
    const { state } = setup();
    await loaded();
    state.failInspect = true;
    fireEvent.press(screen.getByRole("button", { name: "Refresh memory" }));
    await waitFor(() =>
      expect(screen.getByTestId("memory-error")).toHaveTextContent(
        /could not be loaded/i,
      ),
    );
    expect(screen.getByTestId("memory-item-mem-1")).toBeTruthy();
  });

  it("gives repeated titles distinct control names by when they were recorded", async () => {
    const { state } = setup();
    state.items = [
      NOTE_ITEM,
      {
        ...NOTE_ITEM,
        id: "mem-9",
        at: "2026-10-11T09:30:00Z",
        actions: [
          { action: "delete", method: "DELETE", path: "/memory/notes/mem-9" },
        ],
      },
    ];
    await loaded();
    fireEvent.press(screen.getByRole("button", { name: "Refresh memory" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Delete: Distributing over a sum 2 of 2, recorded Oct 11, 2026, 9:30 AM",
        }),
      ).toBeTruthy(),
    );
    expect(
      screen.getByRole("button", {
        name: /Delete: Distributing over a sum 1 of 2, recorded Oct 10, 2026/,
      }),
    ).toBeTruthy();
  });

  it("has a named way back to the board", async () => {
    const { props } = setup();
    await loaded();
    fireEvent.press(screen.getByRole("button", { name: "Back to board" }));
    expect(props.onClose).toHaveBeenCalled();
  });
});
