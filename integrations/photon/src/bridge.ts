/**
 * Continues one learner's tutor session from a paired messaging channel.
 *
 * The bridge holds a bearer token only in memory, after a one-time pairing code is
 * redeemed. It does not open Spectrum, read a Messages database, or send anything by
 * itself. A caller supplies inbound events and performs the actual send.
 */

const CODE = /^[A-Za-z0-9]{8,32}$/;
const MAX_WORK = 500;

export type InboundMessage = {
  id: string;
  senderId: string;
  text: string;
  direction: "inbound" | "outbound";
};

export type BridgeOutcome =
  | { action: "reply"; text: string }
  | { action: "ignore"; reason: "echo" | "duplicate" | "unsupported" | "empty" }
  | { action: "failed"; reason: string };

export type TutorTurn = {
  utterance: string | null;
  revision: number;
  message: string;
};

export type TutorClient = {
  redeem(code: string): Promise<{ accessToken: string }>;
  startSession(accessToken: string): Promise<{ sessionId: string; revision: number }>;
  checkIn(
    accessToken: string,
    sessionId: string,
    revision: number,
    idempotencyKey: string,
  ): Promise<TutorTurn>;
  submitWork(
    accessToken: string,
    sessionId: string,
    revision: number,
    text: string,
    idempotencyKey: string,
  ): Promise<TutorTurn>;
};

type Linked = {
  accessToken: string;
  sessionId: string;
  revision: number;
};

function pairingCode(text: string): string | null {
  const trimmed = text.trim();
  const code = trimmed.toLowerCase().startsWith("pair ")
    ? trimmed.slice(5).trim()
    : trimmed;
  return CODE.test(code) ? code : null;
}

function idempotencyKey(id: string): string {
  const cleaned = id.replace(/[^A-Za-z0-9_.:-]/g, "").slice(0, 120);
  const key = cleaned.length >= 8 ? cleaned : `msg${cleaned}`;
  return key.padEnd(8, "0").slice(0, 128);
}

function replyText(turn: TutorTurn): string {
  const text = (turn.utterance ?? turn.message).trim();
  return text.length > 0 ? text.slice(0, 1200) : "The tutor had no reply. Try that step again.";
}

export class ChannelBridge {
  private readonly linked = new Map<string, Linked>();
  private readonly done = new Set<string>();
  private readonly tutor: TutorClient;

  constructor(tutor: TutorClient) {
    this.tutor = tutor;
  }

  /** Drop a completed id so a failed outbound send can be retried. */
  forget(messageId: string): void {
    this.done.delete(messageId);
  }

  async handle(message: InboundMessage): Promise<BridgeOutcome> {
    if (message.direction === "outbound") return { action: "ignore", reason: "echo" };
    const text = message.text.trim();
    if (message.id.trim().length === 0 || message.senderId.trim().length === 0) {
      return { action: "ignore", reason: "unsupported" };
    }
    if (text.length === 0) return { action: "ignore", reason: "empty" };
    if (this.done.has(message.id)) return { action: "ignore", reason: "duplicate" };

    const existing = this.linked.get(message.senderId);
    try {
      if (existing === undefined) {
        const code = pairingCode(text);
        if (code === null) {
          return {
            action: "reply",
            text: "Send the pairing code from this tutor to connect this chat. Nothing is linked yet.",
          };
        }
        const redeemed = await this.tutor.redeem(code);
        const session = await this.tutor.startSession(redeemed.accessToken);
        const opened = await this.tutor.checkIn(
          redeemed.accessToken,
          session.sessionId,
          session.revision,
          idempotencyKey(message.id),
        );
        this.linked.set(message.senderId, {
          accessToken: redeemed.accessToken,
          sessionId: session.sessionId,
          revision: opened.revision,
        });
        this.done.add(message.id);
        return { action: "reply", text: replyText(opened) };
      }
      const turn = await this.tutor.submitWork(
        existing.accessToken,
        existing.sessionId,
        existing.revision,
        text.slice(0, MAX_WORK),
        idempotencyKey(message.id),
      );
      existing.revision = turn.revision;
      this.done.add(message.id);
      return { action: "reply", text: replyText(turn) };
    } catch (error) {
      const reason = error instanceof Error ? error.message : "The tutor could not be reached.";
      return { action: "failed", reason: reason.slice(0, 200) };
    }
  }
}
