/**
 * Calls the existing tutor HTTP API. Tokens stay in the Authorization header.
 */

import type { TutorClient, TutorTurn } from "./bridge.ts";

type TurnBody = {
  utterance?: string | null;
  session_revision?: number;
  rejections?: { message?: string }[];
};

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: { message?: string } };
    return body.error?.message ?? `The tutor returned ${response.status}.`;
  } catch {
    return `The tutor returned ${response.status}.`;
  }
}

function turnFrom(body: TurnBody): TutorTurn {
  const rejection = body.rejections?.[0]?.message;
  return {
    utterance: body.utterance ?? null,
    revision: body.session_revision ?? 0,
    message: rejection ?? "The tutor did not commit a reply.",
  };
}

export function httpTutor(apiBase: string): TutorClient {
  const root = apiBase.replace(/\/$/, "");

  const authed = async (
    token: string,
    path: string,
    init: RequestInit = {},
  ): Promise<Response> => {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    return fetch(`${root}${path}`, { ...init, headers });
  };

  return {
    async redeem(code) {
      const response = await fetch(`${root}/pairing/redeem`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const body = (await response.json()) as { access_token?: string };
      if (typeof body.access_token !== "string" || body.access_token.length === 0) {
        throw new Error("Pairing did not return a credential.");
      }
      return { accessToken: body.access_token };
    },
    async startSession(accessToken) {
      const response = await authed(accessToken, "/sessions", {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (!response.ok) throw new Error(await readError(response));
      const body = (await response.json()) as { id?: string; revision?: number };
      if (typeof body.id !== "string") throw new Error("The tutor did not start a session.");
      return { sessionId: body.id, revision: body.revision ?? 0 };
    },
    async checkIn(accessToken, sessionId, revision, idempotencyKey) {
      const response = await authed(accessToken, `/sessions/${sessionId}/check-in`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({
          schema_version: "check-in-request.v1",
          expected_revision: revision,
          goal: "solve_equations_with_parentheses",
          use_practice_problem: true,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      return turnFrom((await response.json()) as TurnBody);
    },
    async submitWork(accessToken, sessionId, revision, text, idempotencyKey) {
      const response = await authed(accessToken, `/sessions/${sessionId}/work`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({
          schema_version: "work-request.v1",
          expected_revision: revision,
          text,
          input_mode: "typed",
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      return turnFrom((await response.json()) as TurnBody);
    },
  };
}
