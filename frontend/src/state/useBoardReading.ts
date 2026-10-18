import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiClient } from "../api/client";
import type { SceneSnapshot } from "../api/contracts";

type Props = {
  client: ApiClient;
  sessionId: string;
  scene: SceneSnapshot | null;
  revision: number | null;
  attemptId: string | null;
  blocked: boolean;
  onRead: (text: string, boxedAnswer?: boolean) => Promise<unknown>;
};

/** Read only after new pen activity settles; never scan old ink on mount or tutor updates. */
export function useBoardReading(props: Props) {
  const latest = useRef(props);
  const activity = useRef(0);
  const handled = useRef(0);
  const inFlight = useRef(false);
  const manualCheck = useRef(false);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => { latest.current = props; });
  const onInkActivity = useCallback(() => { activity.current = Date.now(); }, []);

  const checkAnswer = useCallback(() => {
    if (inFlight.current) return;
    manualCheck.current = true;
    handled.current = 0;
    activity.current = Date.now() - 6500;
  }, []);

  useEffect(() => {
    let active = true;
    activity.current = 0;
    handled.current = 0;
    manualCheck.current = false;
    let lastText = "";
    const timer = setInterval(() => {
      const current = latest.current;
      const at = activity.current;
      if (inFlight.current || current.blocked || current.scene === null ||
          current.attemptId === null || at === 0 || at === handled.current ||
          Date.now() - at < 6000 ||
          !current.scene.objects.some((obj) => obj.author_role === "student")) return;
      handled.current = at;
      inFlight.current = true;
      const checking = manualCheck.current;
      manualCheck.current = false;
      setNote(checking ? "Checking your answer…" : "Reading your handwriting…");
      const reading = checking
        ? current.client.readBoard(current.sessionId, current.scene.scene_revision, true)
        : current.client.readBoard(current.sessionId, current.scene.scene_revision);
      void reading.then(async (read) => {
        const now = latest.current;
        if (!active || activity.current !== at || now.blocked ||
            now.revision !== current.revision || now.attemptId !== current.attemptId ||
            now.scene?.scene_revision !== read.scene_revision) return;
        if (!read.legible) {
          setNote(read.text
            ? `Still unclear: ${read.text}. Keep writing, or type your step.`
            : "I’m not sure I read that correctly. Keep writing, or type your step.");
          return;
        }
        if (read.text === lastText && !read.boxed_answer && !checking) { setNote(null); return; }
        lastText = read.text;
        setNote(`Read from board: ${read.text}`);
        if (read.boxed_answer || checking) await now.onRead(read.text, true);
        else await now.onRead(read.text);
      }).catch(() => {
        if (active) setNote("Couldn’t read the board. Keep writing to try again, or type your step.");
      }).finally(() => { inFlight.current = false; });
    }, 750);
    return () => { active = false; clearInterval(timer); };
  }, [props.sessionId, props.attemptId]);
  return { note, onInkActivity, checkAnswer };
}
