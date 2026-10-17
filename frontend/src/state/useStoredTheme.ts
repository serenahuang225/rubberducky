import { useEffect, useMemo, useState } from "react";

import {
  getTheme,
  type BoardTheme,
  type BoardThemeName,
} from "../board/palette";
import { loadThemeName } from "../storage/credentials";

/** The board theme the learner picked on the board, re-read whenever a panel opens. */
export function useStoredTheme(): BoardTheme {
  const [name, setName] = useState<BoardThemeName>("paper");
  useEffect(() => {
    let active = true;
    loadThemeName()
      .then((stored) => {
        if (active && (stored === "paper" || stored === "slate"))
          setName(stored);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
  return useMemo(() => getTheme(name), [name]);
}
