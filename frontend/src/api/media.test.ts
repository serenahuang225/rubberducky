import { ApiClient, ApiClientError } from "./client";

function respond(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const RESULT = {
  schema_version: "media-event-result.v1",
  event_id: "e1",
  kind: "image_snapshot",
  status: "perception_unavailable",
  simulated: false,
  session_id: "s1",
  session_revision: 3,
  cancellation_epoch: 1,
  message: "Photo reading is not configured.",
  assessment_effect: "none",
  evidence_recorded: false,
  raw_media_retained: false,
};

describe("ApiClient media methods", () => {
  it("posts a bounded image event with its scope and no pixel data", async () => {
    const fetchImpl = jest.fn(async () => respond(200, RESULT));
    const client = new ApiClient(
      "http://t.test",
      "token",
      fetchImpl as unknown as typeof fetch,
    );
    const result = await client.postMediaEvent(
      "s1",
      {
        kind: "image_snapshot",
        event_id: "e1",
        source: "device",
        orientation: "work_facing",
        mime: "image/jpeg",
        width: 640,
        height: 480,
      },
      { revision: 3, epoch: 1 },
    );
    expect(result.status).toBe("perception_unavailable");
    expect(result.evidence_recorded).toBe(false);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe("http://t.test/sessions/s1/media/events");
    const body = JSON.parse(String(init.body));
    expect(body).toMatchObject({
      schema_version: "media-event-request.v1",
      expected_revision: 3,
      observed_epoch: 1,
      trigger: "explicit_capture",
      orientation: "work_facing",
    });
    expect(Object.keys(body)).not.toEqual(
      expect.arrayContaining(["image_base64"]),
    );
  });

  it("surfaces a stale-scope refusal as an ApiClientError with status 409", async () => {
    const client = new ApiClient("http://t.test", "token", (async () =>
      respond(409, {
        schema_version: "error.v1",
        error: { code: "stale_media_event", message: "The board moved on." },
      })) as unknown as typeof fetch);
    await expect(
      client.postMediaEvent(
        "s1",
        {
          kind: "weak_context",
          event_id: "e2",
          source: "simulated",
          signal: "silence",
        },
        { revision: 1, epoch: 0 },
      ),
    ).rejects.toMatchObject({ status: 409 });
    await expect(
      client.postMediaEvent(
        "s1",
        {
          kind: "weak_context",
          event_id: "e2",
          source: "simulated",
          signal: "silence",
        },
        { revision: 1, epoch: 0 },
      ),
    ).rejects.toBeInstanceOf(ApiClientError);
  });

  it("rejects a malformed capabilities answer instead of trusting it", async () => {
    const client = new ApiClient("http://t.test", "token", (async () =>
      respond(200, {
        schema_version: "media-capabilities.v1",
      })) as unknown as typeof fetch);
    await expect(client.mediaCapabilities()).rejects.toBeDefined();
  });
});
