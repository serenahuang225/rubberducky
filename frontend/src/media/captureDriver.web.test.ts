import { deviceCaptureDriver } from "./captureDriver.web";

jest.mock("./cameraDriver", () => ({ deviceCamera: {} }));

type Track = { stop: jest.Mock };
function stubMediaDevices(
  impl: (() => Promise<{ getTracks: () => Track[] }>) | null,
) {
  const nav = globalThis as unknown as { navigator?: unknown };
  const original = nav.navigator;
  nav.navigator = impl === null ? {} : { mediaDevices: { getUserMedia: impl } };
  return () => {
    nav.navigator = original;
  };
}

describe("web microphone driver", () => {
  it("reports unavailable when the browser exposes no media devices", async () => {
    const restore = stubMediaDevices(null);
    expect(await deviceCaptureDriver.microphone.request()).toBe("unavailable");
    restore();
  });

  it("maps a refused prompt to denied and a missing device to unavailable", async () => {
    let restore = stubMediaDevices(async () => {
      throw Object.assign(new Error("no"), { name: "NotAllowedError" });
    });
    expect(await deviceCaptureDriver.microphone.request()).toBe("denied");
    restore();
    restore = stubMediaDevices(async () => {
      throw Object.assign(new Error("none"), { name: "NotFoundError" });
    });
    expect(await deviceCaptureDriver.microphone.request()).toBe("unavailable");
    restore();
  });

  it("holds the granted stream only until close, which stops every track", async () => {
    const track: Track = { stop: jest.fn() };
    const restore = stubMediaDevices(async () => ({
      getTracks: () => [track],
    }));
    expect(await deviceCaptureDriver.microphone.request()).toBe("granted");
    await deviceCaptureDriver.microphone.open();
    expect(track.stop).not.toHaveBeenCalled();
    await deviceCaptureDriver.microphone.close();
    expect(track.stop).toHaveBeenCalledTimes(1);
    await expect(deviceCaptureDriver.microphone.open()).rejects.toThrow();
    restore();
  });
});
