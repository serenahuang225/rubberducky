/**
 * Photon Beta (2.0) iMessage connection.
 * Docs: https://photon.codes/docs/beta/get-started/imessage
 *
 * Importing this file does not connect or send. `runPhoton` returns immediately
 * unless messaging is explicitly enabled and the Beta project credentials are present.
 * API origin is https://api.photon.codes. Credentials are a bearer project key
 * (`pho_sk_...`) and a project id (`pho_prj_...`). This is not the Stable Spectrum SDK.
 */

import { ChannelBridge, type InboundMessage, type TutorClient } from "./bridge.ts";

export type PhotonEnv = {
  PHOTON_MESSAGING_ENABLED?: string;
  PHOTON_API_KEY?: string;
  PHOTON_PROJECT_ID?: string;
  PHOTON_AGENT_HANDLE?: string;
  PHOTON_TEST_SENDER?: string;
};

export type PhotonStatus = "disabled" | "missing_credentials" | "started";

export type ListedMessage = {
  id: string;
  platform: string;
  status: string;
  createdAt: string;
  sentBy: { platform: string; kind: string; handle: string; id: string };
  receivedBy: { platform: string; kind: string; handle: string; id: string } | null;
  space: { platform: string; kind: string; id: string };
  content: { type: string; format?: string; text?: string };
};

export type BetaMessaging = {
  listReceived(
    createdSince: string,
    pageToken?: string,
  ): Promise<{ items: ListedMessage[]; nextPageToken?: string }>;
  sendReply(input: {
    idempotencyKey: string;
    spaceId: string;
    senderId: string;
    parentMessageId: string;
    text: string;
  }): Promise<void>;
};

type ReadyEnv = {
  PHOTON_API_KEY: string;
  PHOTON_PROJECT_ID: string;
  PHOTON_AGENT_HANDLE: string;
  PHOTON_TEST_SENDER: string;
};

export function photonStatus(env: PhotonEnv): PhotonStatus | "ready" {
  if (env.PHOTON_MESSAGING_ENABLED !== "true") return "disabled";
  if (
    !env.PHOTON_API_KEY ||
    !env.PHOTON_PROJECT_ID ||
    !env.PHOTON_AGENT_HANDLE ||
    !env.PHOTON_TEST_SENDER
  ) {
    return "missing_credentials";
  }
  return "ready";
}

function readyEnv(env: PhotonEnv): ReadyEnv {
  return {
    PHOTON_API_KEY: env.PHOTON_API_KEY ?? "",
    PHOTON_PROJECT_ID: env.PHOTON_PROJECT_ID ?? "",
    PHOTON_AGENT_HANDLE: env.PHOTON_AGENT_HANDLE ?? "",
    PHOTON_TEST_SENDER: env.PHOTON_TEST_SENDER ?? "",
  };
}

/** A direct iMessage from the configured test sender to the assigned agent line. */
export function matchInbound(
  message: ListedMessage,
  env: ReadyEnv,
  startedAt: number,
): InboundMessage | null {
  if (message.platform !== "imessage" || message.status !== "received") return null;
  if (Date.parse(message.createdAt) < startedAt) return null;
  if (message.sentBy.platform !== "imessage" || message.sentBy.kind !== "human") return null;
  if (message.sentBy.handle !== env.PHOTON_TEST_SENDER) return null;
  if (message.receivedBy?.platform !== "imessage" || message.receivedBy.kind !== "agent") return null;
  if (message.receivedBy.handle !== env.PHOTON_AGENT_HANDLE) return null;
  if (message.sentBy.id === message.receivedBy.id) return null;
  if (message.space.platform !== "imessage" || message.space.kind !== "direct") return null;
  if (message.content.type !== "text" || message.content.format !== "plain") return null;
  if (typeof message.content.text !== "string") return null;
  return {
    id: message.id,
    senderId: message.sentBy.id,
    text: message.content.text,
    direction: "inbound",
  };
}

type PhotonClient = {
  projects: {
    listMessages(input: {
      path: { id: string };
      query: Record<string, string | number>;
    }): Promise<{ items: ListedMessage[]; nextPageToken?: string }>;
    sendMessage(input: {
      path: { id: string };
      headers: { "idempotency-key": string };
      body: {
        spaceId: string;
        senderId: string;
        parentMessageId: string;
        content: { type: "text"; format: "plain"; text: string };
      };
    }): Promise<unknown>;
  };
};

/** Loads `@photon-ai/api` only after the enable checks pass. */
export async function loadBetaMessaging(env: PhotonEnv): Promise<BetaMessaging> {
  const ready = readyEnv(env);
  const imported = (await import("@photon-ai/api")) as {
    Photon: new (options: { headers: { Authorization: string } }) => PhotonClient;
  };
  const photon = new imported.Photon({
    headers: { Authorization: `Bearer ${ready.PHOTON_API_KEY}` },
  });
  return {
    async listReceived(createdSince, pageToken) {
      const page = await photon.projects.listMessages({
        path: { id: ready.PHOTON_PROJECT_ID },
        query: {
          createdSince,
          direction: "received",
          order: "asc",
          pageSize: 100,
          platform: "imessage",
          ...(pageToken ? { pageToken } : {}),
        },
      });
      return { items: page.items, nextPageToken: page.nextPageToken };
    },
    async sendReply(input) {
      await photon.projects.sendMessage({
        path: { id: ready.PHOTON_PROJECT_ID },
        headers: { "idempotency-key": input.idempotencyKey },
        body: {
          spaceId: input.spaceId,
          senderId: input.senderId,
          parentMessageId: input.parentMessageId,
          content: { type: "text", format: "plain", text: input.text },
        },
      });
    },
  };
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function runPhoton(
  env: PhotonEnv,
  tutor: TutorClient,
  connect: (env: PhotonEnv) => Promise<BetaMessaging> = loadBetaMessaging,
  options: { maxPasses?: number; pollMs?: number } = {},
): Promise<PhotonStatus> {
  const status = photonStatus(env);
  if (status !== "ready") return status;
  const ready = readyEnv(env);
  const messaging = await connect(env);
  const bridge = new ChannelBridge(tutor);
  const startedAt = Date.now();
  const createdSince = new Date(startedAt - 5_000).toISOString();
  const pollMs = options.pollMs ?? 2_000;
  let passes = 0;
  while (options.maxPasses === undefined || passes < options.maxPasses) {
    passes += 1;
    let pageToken: string | undefined;
    do {
      const page = await messaging.listReceived(createdSince, pageToken);
      for (const message of page.items) {
        const event = matchInbound(message, ready, startedAt);
        if (event === null) continue;
        const outcome = await bridge.handle(event);
        if (outcome.action !== "reply") continue;
        try {
          await messaging.sendReply({
            idempotencyKey: `tutor-reply:${event.id}`,
            spaceId: message.space.id,
            senderId: message.receivedBy?.id ?? "",
            parentMessageId: event.id,
            text: outcome.text,
          });
        } catch {
          bridge.forget(event.id);
        }
      }
      pageToken = page.nextPageToken;
    } while (pageToken);
    if (options.maxPasses !== undefined) break;
    await sleep(pollMs);
  }
  return "started";
}
