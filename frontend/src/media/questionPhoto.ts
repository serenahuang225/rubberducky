/**
 * Pick a camera still small enough to send as a question.
 * The bytes are JPEG base64, same shape the browser upload already uses.
 */

export const QUESTION_PHOTO_EDGE = 1600;
export const MAX_QUESTION_PHOTO_CHARS = 2_200_000;

export function choosePictureSize(
  sizes: readonly string[],
  maxEdge = QUESTION_PHOTO_EDGE,
): string | null {
  const parsed = sizes.flatMap((size) => {
    const match = /^(\d+)x(\d+)$/i.exec(size.trim());
    if (match === null) return [];
    return [{ size, edge: Math.max(Number(match[1]), Number(match[2])) }];
  });
  if (parsed.length === 0) return null;
  const fitting = parsed.filter((item) => item.edge <= maxEdge);
  if (fitting.length > 0) {
    fitting.sort((a, b) => b.edge - a.edge);
    return fitting[0].size;
  }
  parsed.sort((a, b) => a.edge - b.edge);
  return parsed[0].size;
}

export function photoBase64(value: string | undefined): string {
  const encoded = (value ?? "")
    .replace(/^data:image\/[a-z0-9.+-]+;base64,/i, "")
    .replace(/\s/g, "");
  if (encoded.length === 0) {
    throw new Error("Could not read that photo.");
  }
  if (encoded.length > MAX_QUESTION_PHOTO_CHARS) {
    throw new Error(
      "That photo is too large to send. Move a little farther away and try again.",
    );
  }
  return encoded;
}
