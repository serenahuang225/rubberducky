import { photoBase64, choosePictureSize } from "./questionPhoto";

describe("choosePictureSize", () => {
  it("picks the largest size that still fits the question edge", () => {
    expect(choosePictureSize(["4032x3024", "1920x1080", "1280x720", "640x480"])).toBe(
      "1280x720",
    );
  });

  it("uses the smallest offered size when every size is larger", () => {
    expect(choosePictureSize(["4032x3024", "3840x2160"])).toBe("3840x2160");
  });

  it("ignores sizes that are not width by height", () => {
    expect(choosePictureSize(["High", "Photo"])).toBeNull();
  });
});

describe("photoBase64", () => {
  it("strips a data-url prefix", () => {
    expect(photoBase64("data:image/jpeg;base64,abc")).toBe("abc");
  });

  it("refuses an empty or oversized photo", () => {
    expect(() => photoBase64("   ")).toThrow(/could not read/i);
    expect(() => photoBase64("a".repeat(2_200_001))).toThrow(/too large/i);
  });
});
