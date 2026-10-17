import { CaptureController } from "./captureController";
import type { CaptureDriver, PermissionResult } from "./captureTypes";

type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void };
function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function fakeDriver(
  overrides: {
    mic?: () => Promise<PermissionResult>;
    cam?: () => Promise<PermissionResult>;
    camAvailable?: () => Promise<boolean>;
    camOpen?: () => Promise<void>;
  } = {},
) {
  const calls: string[] = [];
  const driver: CaptureDriver = {
    microphone: {
      request: async () => {
        calls.push("mic.request");
        return overrides.mic ? overrides.mic() : "granted";
      },
      open: async () => {
        calls.push("mic.open");
      },
      close: async () => {
        calls.push("mic.close");
      },
    },
    camera: {
      available: async () => {
        calls.push("cam.available");
        return overrides.camAvailable ? overrides.camAvailable() : true;
      },
      request: async () => {
        calls.push("cam.request");
        return overrides.cam ? overrides.cam() : "granted";
      },
      open: async (orientation) => {
        calls.push(`cam.open:${orientation}`);
        if (overrides.camOpen) await overrides.camOpen();
      },
      close: async () => {
        calls.push("cam.close");
      },
      snapshot: async () => {
        calls.push("cam.snapshot");
        return { width: 640, height: 480, mime: "image/jpeg" as const };
      },
    },
  };
  return { driver, calls };
}

describe("CaptureController", () => {
  it("starts off and makes no driver call until the learner starts capture", () => {
    const { driver, calls } = fakeDriver();
    const controller = new CaptureController(driver);
    expect(controller.getSnapshot().microphone.status).toBe("off");
    expect(controller.getSnapshot().camera.status).toBe("off");
    expect(calls).toEqual([]);
  });

  it("turns the microphone on only after a permission grant and opens it once", async () => {
    const { driver, calls } = fakeDriver();
    const controller = new CaptureController(driver);
    await controller.startMicrophone();
    expect(calls).toEqual(["mic.request", "mic.open"]);
    expect(controller.getSnapshot().microphone.status).toBe("on");
  });

  it("records the camera orientation the learner chose", async () => {
    const { driver, calls } = fakeDriver();
    const controller = new CaptureController(driver);
    await controller.startCamera("work_facing");
    expect(calls).toContain("cam.open:work_facing");
    expect(controller.getSnapshot().camera).toMatchObject({
      status: "on",
      orientation: "work_facing",
    });
  });

  it("switching camera facing closes the previous capture instead of stacking", async () => {
    const { driver, calls } = fakeDriver();
    const controller = new CaptureController(driver);
    await controller.startCamera("student_facing");
    await controller.startCamera("work_facing");
    expect(calls.filter((call) => call === "cam.close")).toHaveLength(1);
    expect(controller.getSnapshot().camera.orientation).toBe("work_facing");
  });

  it("explains denial without opening anything", async () => {
    const { driver, calls } = fakeDriver({ mic: async () => "denied" });
    const controller = new CaptureController(driver);
    await controller.startMicrophone();
    const mic = controller.getSnapshot().microphone;
    expect(mic.status).toBe("denied");
    expect(mic.note).toMatch(/keep typing and drawing/i);
    expect(calls).not.toContain("mic.open");
  });

  it("reports a missing camera before asking for permission", async () => {
    const { driver, calls } = fakeDriver({ camAvailable: async () => false });
    const controller = new CaptureController(driver);
    await controller.startCamera("student_facing");
    expect(controller.getSnapshot().camera.status).toBe("unavailable");
    expect(calls).not.toContain("cam.request");
  });

  it("reports a driver failure as an error and releases the device", async () => {
    const { driver, calls } = fakeDriver({
      camOpen: async () => {
        throw new Error("boom");
      },
    });
    const controller = new CaptureController(driver);
    await controller.startCamera("student_facing");
    expect(controller.getSnapshot().camera.status).toBe("error");
    expect(calls).toContain("cam.close");
  });

  it("a grant that arrives after Stop never opens the microphone", async () => {
    const gate = deferred<PermissionResult>();
    const { driver, calls } = fakeDriver({ mic: () => gate.promise });
    const controller = new CaptureController(driver);
    const starting = controller.startMicrophone();
    expect(controller.getSnapshot().microphone.status).toBe("requesting");
    await controller.stop("microphone", "user");
    gate.resolve("granted");
    await starting;
    expect(calls).not.toContain("mic.open");
    expect(controller.getSnapshot().microphone.status).toBe("off");
  });

  it("stop releases a capture that is on and says so", async () => {
    const { driver, calls } = fakeDriver();
    const controller = new CaptureController(driver);
    await controller.startMicrophone();
    await controller.stop("microphone", "user");
    expect(calls.at(-1)).toBe("mic.close");
    expect(controller.getSnapshot().microphone).toMatchObject({
      status: "off",
      note: "Microphone turned off.",
    });
  });

  it("releases everything with an honest reason when the app is backgrounded", async () => {
    const { driver, calls } = fakeDriver();
    const controller = new CaptureController(driver);
    await controller.startMicrophone();
    await controller.startCamera("work_facing");
    await controller.stopAll("background");
    expect(calls).toEqual(expect.arrayContaining(["mic.close", "cam.close"]));
    const snapshot = controller.getSnapshot();
    expect(snapshot.microphone.status).toBe("off");
    expect(snapshot.camera.note).toMatch(/left the foreground/i);
  });

  it("stopping something that is off makes no driver call", async () => {
    const { driver, calls } = fakeDriver();
    const controller = new CaptureController(driver);
    await controller.stopAll("unfocus");
    expect(calls).toEqual([]);
  });

  it("text-only mode refuses to start and releases anything already open", async () => {
    const { driver, calls } = fakeDriver();
    const controller = new CaptureController(driver);
    await controller.startMicrophone();
    await controller.setBlocked(true);
    expect(controller.getSnapshot().microphone.status).toBe("off");
    const before = calls.length;
    await controller.startCamera("student_facing");
    expect(calls.slice(before)).toEqual([]);
    expect(controller.getSnapshot().camera.note).toMatch(/text-only/i);
  });

  it("takes a still only while the camera is on", async () => {
    const { driver, calls } = fakeDriver();
    const controller = new CaptureController(driver);
    expect(await controller.takeSnapshot()).toBeNull();
    expect(calls).not.toContain("cam.snapshot");
    await controller.startCamera("work_facing");
    expect(await controller.takeSnapshot()).toEqual({
      width: 640,
      height: 480,
      mime: "image/jpeg",
    });
  });

  it("a preview that fails after opening is released and reported", async () => {
    const { driver, calls } = fakeDriver();
    const controller = new CaptureController(driver);
    await controller.startCamera("work_facing");
    await controller.fail("camera");
    expect(calls).toContain("cam.close");
    expect(controller.getSnapshot().camera.status).toBe("error");
  });

  it("notifies subscribers on every state change", async () => {
    const { driver } = fakeDriver();
    const controller = new CaptureController(driver);
    const seen: string[] = [];
    controller.subscribe(() =>
      seen.push(controller.getSnapshot().microphone.status),
    );
    await controller.startMicrophone();
    expect(seen).toEqual(["requesting", "on"]);
  });
});
