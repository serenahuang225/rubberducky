/**
 * Spectrum cloud connection. Importing this file does not connect or send.
 * `runPhoton` returns immediately unless messaging is explicitly enabled and
 * both Stable project credentials are present.
 */

import { ChannelBridge, type InboundMessage, type TutorClient } from "./bridge.ts";

export type PhotonEnv = {
  PHOTON_MESSAGING_ENABLED?: string;
  SPECTRUM_PROJECT_ID?: string;
  SPECTRUM_PROJECT_SECRET?: string;
};

export type PhotonStatus = "disabled" | "missing_credentials" | "started";

type SpectrumMessage = {
  id?: string;
  direction?: string;
  sender?: { id?: string };
  content?: { type?: string; text?: string };
};

type SpectrumSpace = {
  send: (text: string) => Promise<void>;
};

type SpectrumApp = {
  messages: AsyncIterable<[SpectrumSpace, SpectrumMessage]>;
  stop: () => Promise<void>;
};

export type SpectrumLoader = (projectId: string, projectSecret: string) => Promise<SpectrumApp>;

export function photonStatus(env: PhotonEnv): PhotonStatus | "ready" {
  if (env.PHOTON_MESSAGING_ENABLED !== "true") return "disabled";
  if (!env.SPECTRUM_PROJECT_ID || !env.SPECTRUM_PROJECT_SECRET) return "missing_credentials";
  return "ready";
}

function inbound(message: SpectrumMessage): InboundMessage | null {
  if (message.direction !== "inbound") return null;
  if (message.content?.type !== "text" || typeof message.content.text !== "string") return null;
  if (typeof message.id !== "string" || typeof message.sender?.id !== "string") return null;
  return {
    id: message.id,
    senderId: message.sender.id,
    text: message.content.text,
    direction: "inbound",
  };
}

/** Default loader. Resolves the Stable SDK only after the enable checks pass. */
export const loadSpectrumCloud: SpectrumLoader = async (projectId, projectSecret) => {
  const core = (await import("@spectrum-ts/core")) as {
    Spectrum: (options: {
      projectId: string;
      projectSecret: string;
      providers: unknown[];
    }) => Promise<SpectrumApp>;
  };
  const provider = (await import("@spectrum-ts/imessage")) as {
    imessage: { config: () => unknown };
  };
  return core.Spectrum({
    projectId,
    projectSecret,
    providers: [provider.imessage.config()],
  });
};

export async function runPhoton(
  env: PhotonEnv,
  tutor: TutorClient,
  load: SpectrumLoader = loadSpectrumCloud,
): Promise<PhotonStatus> {
  const status = photonStatus(env);
  if (status !== "ready") return status;
  const app = await load(env.SPECTRUM_PROJECT_ID ?? "", env.SPECTRUM_PROJECT_SECRET ?? "");
  const bridge = new ChannelBridge(tutor);
  try {
    for await (const [space, message] of app.messages) {
      const event = inbound(message);
      if (event === null) continue;
      const outcome = await bridge.handle(event);
      if (outcome.action !== "reply") continue;
      try {
        await space.send(outcome.text);
      } catch {
        // The tutor turn already committed under this message id. Forgetting the
        // id lets a redelivery replay that turn instead of creating a second one.
        bridge.forget(event.id);
      }
    }
  } finally {
    await app.stop();
  }
  return "started";
}
