import assert from "node:assert/strict";
import test from "node:test";

import type { TutorClient, TutorTurn } from "./bridge.ts";
import { matchInbound, runPhoton, type BetaMessaging, type ListedMessage, type PhotonEnv } from "./live.ts";

const env: PhotonEnv = {
  PHOTON_MESSAGING_ENABLED: "true",
  PHOTON_API_KEY: "pho_sk_test",
  PHOTON_PROJECT_ID: "pho_prj_test",
  PHOTON_AGENT_HANDLE: "+15550001111",
  PHOTON_TEST_SENDER: "+15550002222",
};

function message(overrides: Partial<ListedMessage> = {}): ListedMessage {
  return {
    id: "msg-1",
    platform: "imessage",
    status: "received",
    createdAt: new Date().toISOString(),
    sentBy: { platform: "imessage", kind: "human", handle: "+15550002222", id: "human-1" },
    receivedBy: { platform: "imessage", kind: "agent", handle: "+15550001111", id: "agent-1" },
    space: { platform: "imessage", kind: "direct", id: "space-1" },
    content: { type: "text", format: "plain", text: "pair ADACODE12345" },
    ...overrides,
  };
}

function tutor(): TutorClient {
  const turn = (utterance: string, revision: number): TutorTurn => ({
    utterance,
    revision,
    message: utterance,
  });
  return {
    async redeem() {
      return { accessToken: "token-ada" };
    },
    async startSession() {
      return { sessionId: "session-1", revision: 0 };
    },
    async checkIn() {
      return turn("Last time you distributed only the first term.", 1);
    },
    async submitWork(_token, _session, _revision, text) {
      return turn(`Next: ${text}`, 2);
    },
  };
}

test("a phone number never selects the learner, and a later text stays on the paired session", async () => {
  const seen: string[] = [];
  const sent: string[] = [];
  const messaging: BetaMessaging = {
    async listReceived() {
      return {
        items: [
          message(),
          message({ id: "msg-2", content: { type: "text", format: "plain", text: "2x + 3 = 14" } }),
          message({
            id: "msg-own",
            sentBy: { platform: "imessage", kind: "agent", handle: "+15550001111", id: "agent-1" },
            content: { type: "text", format: "plain", text: "Next: 2x + 3 = 14" },
          }),
        ],
      };
    },
    async sendReply(input) {
      sent.push(input.text);
      seen.push(input.parentMessageId);
    },
  };
  const status = await runPhoton(env, tutor(), async () => messaging, { maxPasses: 1 });
  assert.equal(status, "started");
  assert.deepEqual(seen, ["msg-1", "msg-2"]);
  assert.match(sent[0] ?? "", /first term/);
  assert.match(sent[1] ?? "", /2x \+ 3 = 14/);
});

test("messages from another sender are ignored", () => {
  const inbound = matchInbound(
    message({
      sentBy: { platform: "imessage", kind: "human", handle: "+19990000000", id: "other" },
    }),
    {
      PHOTON_API_KEY: "pho_sk_test",
      PHOTON_PROJECT_ID: "pho_prj_test",
      PHOTON_AGENT_HANDLE: "+15550001111",
      PHOTON_TEST_SENDER: "+15550002222",
    },
    Date.now() - 60_000,
  );
  assert.equal(inbound, null);
});
