import {
  createTalkRecorder,
  type TalkClip,
  type TalkHost,
  type TalkSession,
  type TalkStream,
} from "./pushToTalk";

function host(clip: TalkClip | null = { bytes: new Blob([new Uint8Array(240)]), mime: "audio/webm" }): TalkHost {
  const stream: TalkStream = { getTracks: () => [{ stop: () => undefined }] };
  return {
    available: () => true,
    getUserMedia: async () => stream,
    record: (): TalkSession => ({
      start: () => undefined,
      stop: async () => clip,
    }),
  };
}

describe("hold to talk", () => {
  it("returns one clip when the hold produced audio", async () => {
    const recorder = createTalkRecorder(host());
    await recorder.start();
    const clip = await recorder.stop();
    expect(clip?.mime).toBe("audio/webm");
    expect(clip?.bytes.size).toBeGreaterThan(0);
  });

  it("drops a hold that ends before the microphone opens", async () => {
    let open: (stream: TalkStream) => void = () => undefined;
    const pending = new Promise<TalkStream>((resolve) => {
      open = resolve;
    });
    const recorder = createTalkRecorder({
      available: () => true,
      getUserMedia: () => pending,
      record: () => ({
        start: () => {
          throw new Error("should not start");
        },
        stop: async () => ({ bytes: new Blob(["x"]), mime: "audio/webm" }),
      }),
    });
    const starting = recorder.start();
    const stopped = recorder.stop();
    open({ getTracks: () => [{ stop: () => undefined }] });
    await starting;
    expect(await stopped).toBeNull();
  });

  it("returns null when the clip is too short to send", async () => {
    const recorder = createTalkRecorder(host(null));
    await recorder.start();
    expect(await recorder.stop()).toBeNull();
  });
});
