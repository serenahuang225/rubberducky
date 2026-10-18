/**
 * Turn a chosen file or pasted screenshot into a question the tutor can read.
 * Images are scaled down in the browser before they leave the device.
 */

const MAX_EDGE = 1600;
const MAX_TEXT_CHARS = 4000;

export type QuestionImagePayload = {
  mediaType: "image/jpeg";
  base64: string;
};

export type ReadQuestionFile =
  | { kind: "text"; text: string }
  | { kind: "image"; image: QuestionImagePayload };

export function isTextQuestionFile(file: File): boolean {
  return file.type.startsWith("text/") || file.name.toLowerCase().endsWith(".txt");
}

export function isImageQuestionFile(file: File): boolean {
  return (
    file.type === "image/png" ||
    file.type === "image/jpeg" ||
    file.type === "image/webp" ||
    /\.(png|jpe?g|webp)$/i.test(file.name)
  );
}

export async function readQuestionFile(file: File): Promise<ReadQuestionFile> {
  if (isImageQuestionFile(file)) {
    return { kind: "image", image: { mediaType: "image/jpeg", base64: await imageToJpegBase64(file) } };
  }
  if (isTextQuestionFile(file) && file.size < 200_000) {
    const text = (await file.text()).trim().slice(0, MAX_TEXT_CHARS);
    if (text.length === 0) {
      throw new Error("That file is empty.");
    }
    return { kind: "text", text };
  }
  throw new Error("Use a picture (png, jpeg, webp) or a plain text file.");
}

async function imageToJpegBase64(file: Blob): Promise<string> {
  const bitmap = await createImageBitmap(file);
  try {
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (context === null) {
      throw new Error("Could not read that picture.");
    }
    context.drawImage(bitmap, 0, 0, width, height);
    const url = canvas.toDataURL("image/jpeg", 0.82);
    const encoded = url.split(",")[1] ?? "";
    if (encoded.length === 0) {
      throw new Error("Could not read that picture.");
    }
    return encoded;
  } finally {
    bitmap.close();
  }
}
