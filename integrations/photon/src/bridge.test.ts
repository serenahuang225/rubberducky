import assert from "node:assert/strict";
import test from "node:test";

import { ChannelBridge, type TutorClient, type TutorTurn } from "./bridge.ts";
import { photonStatus, runPhoton } from "./live.ts";

function tutor(): TutorClient & { calls: string[] } {
  const calls: string[] = [];
  const turn = (utterance: string, revision: number): TutorTurn => ({
    utterance,
    revision,
    message: utterance,
  });
  return {
    calls,
    async redeem(code) {
      calls.push(`redeem:${code}`);
      if (code === "BADCODE1234") throw new Error("invalid");
      return { accessToken: code === "ADACODE12345" ? "token-ada" : "token-new" };
    },
    async startSession(token) {
      calls.push(`session:${token}`);
      return { sessionId: "session-1", revision: 0 };
    },
    async checkIn(token) {
      calls.push(`checkin:${token}`);
      return turn(token === "token-ada" ? "Last time you distributed only the first term." : "Let's start.", 1);
    },
    async submitWork(_token, _session, _revision, text) {
      calls.push(`work:${text}`);
      return turn(`Next: ${text}`, 2);
    },
  };
}

test("an unpaired chat is asked for a code and does not call the tutor", async () => {
  const client = tutor();
  const bridge = new ChannelBridge(client);
  const outcome = await bridge.handle({
    id: "m1",
    senderId: "person-a",
    text: "hello",
    direction: "inbound",
  });
  assert.deepEqual(outcome.action, "reply");
  assert.equal(client.calls.length, 0);
});

test("a pairing code links the sender and a later step uses that session once", async () => {
  const client = tutor();
  const bridge = new ChannelBridge(client);
  const paired = await bridge.handle({
    id: "m-pair",
    senderId: "person-a",
    text: "pair ADACODE12345",
    direction: "inbound",
  });
  assert.equal(paired.action, "reply");
  if (paired.action === "reply") {
    assert.match(paired.text, /first term/);
  }
  const again = await bridge.handle({
    id: "m-pair",
    senderId: "person-a",
    text: "pair ADACODE12345",
    direction: "inbound",
  });
  assert.deepEqual(again, { action: "ignore", reason: "duplicate" });
  const step = await bridge.handle({
    id: "m-step",
    senderId: "person-a",
    text: "2x + 3 = 14",
    direction: "inbound",
  });
  assert.equal(step.action, "reply");
  if (step.action === "reply") assert.match(step.text, /2x \+ 3 = 14/);
  const echo = await bridge.handle({
    id: "m-echo",
    senderId: "line",
    text: "Next: 2x + 3 = 14",
    direction: "outbound",
  });
  assert.deepEqual(echo, { action: "ignore", reason: "echo" });
  assert.deepEqual(client.calls, [
    "redeem:ADACODE12345",
    "session:token-ada",
    "checkin:token-ada",
    "work:2x + 3 = 14",
  ]);
});

test("a bad code fails without linking, and a send failure can be retried", async () => {
  const client = tutor();
  const bridge = new ChannelBridge(client);
  const failed = await bridge.handle({
    id: "m-bad",
    senderId: "person-b",
    text: "BADCODE1234",
    direction: "inbound",
  });
  assert.equal(failed.action, "failed");
  const retried = await bridge.handle({
    id: "m-bad",
    senderId: "person-b",
    text: "FRESHCODE1",
    direction: "inbound",
  });
  assert.equal(retried.action, "reply");
});

test("photon stays disabled and does not load a connection", async () => {
  assert.equal(photonStatus({}), "disabled");
  assert.equal(
    photonStatus({ PHOTON_MESSAGING_ENABLED: "true" }),
    "missing_credentials",
  );
  let loaded = 0;
  const status = await runPhoton({ PHOTON_MESSAGING_ENABLED: "false" }, tutor(), async () => {
    loaded += 1;
    throw new Error("should not connect");
  });
  assert.equal(status, "disabled");
  assert.equal(loaded, 0);
});
