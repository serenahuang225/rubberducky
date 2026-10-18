/**
 * Web-only type, focus, and motion. Native uses the same token families and falls back
 * to faces that ship with the device. Animations run only when the resolved motion mode
 * is full; an explicit full choice still runs if the system asks for less motion.
 */

import { useEffect } from "react";
import { Platform } from "react-native";

import type { BoardTheme } from "../board/palette";
import type { MotionMode } from "../feedback/preferences";

const WEB_CSS = `
html, body, #root {
  width: 100%;
  height: 100%;
  margin: 0;
  background: var(--rd-canvas, #FFFFFF);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
html, body { overflow: hidden; }
#root {
  display: flex;
  min-height: 100dvh;
}
#root > div {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  width: 100%;
}
[role="button"], [role="radio"], [role="switch"], input, textarea {
  transition: background-color 140ms cubic-bezier(0.2, 0, 0, 1),
    color 140ms cubic-bezier(0.2, 0, 0, 1),
    border-color 140ms cubic-bezier(0.2, 0, 0, 1),
    opacity 140ms cubic-bezier(0.2, 0, 0, 1);
}
[role="button"] { cursor: pointer; }
[role="button"][aria-disabled="true"] { cursor: default; }
[role="button"]:focus-visible,
[role="radio"]:focus-visible,
[role="switch"]:focus-visible,
input:focus-visible,
textarea:focus-visible {
  outline: 2px solid var(--rd-focus, #1985d0) !important;
  outline-offset: 2px;
}
[data-status] { transition: background-color 160ms cubic-bezier(0.2, 0, 0, 1), border-color 160ms cubic-bezier(0.2, 0, 0, 1), opacity 160ms cubic-bezier(0.2, 0, 0, 1); }
@keyframes rd-enter {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
[data-enter="1"] { animation: rd-enter 200ms cubic-bezier(0.16, 1, 0.3, 1); }
@keyframes rd-ack {
  0% { opacity: 0; transform: translateY(4px); }
  18% { opacity: 1; transform: translateY(0); }
  72% { opacity: 1; }
  100% { opacity: 0; }
}
[data-ack="1"] { animation: rd-ack 1600ms cubic-bezier(0.2, 0, 0, 1) forwards; }
@media (prefers-reduced-motion: reduce) {
  html:not([data-motion="full"]) [role="button"],
  html:not([data-motion="full"]) [role="radio"],
  html:not([data-motion="full"]) [role="switch"],
  html:not([data-motion="full"]) input,
  html:not([data-motion="full"]) textarea,
  html:not([data-motion="full"]) [data-status] { transition: none; }
  html:not([data-motion="full"]) [data-enter="1"],
  html:not([data-motion="full"]) [data-ack="1"] { animation: none; }
}
html[data-motion="reduced"] [role="button"],
html[data-motion="reduced"] [role="radio"],
html[data-motion="reduced"] [role="switch"],
html[data-motion="reduced"] input,
html[data-motion="reduced"] textarea,
html[data-motion="reduced"] [data-status] { transition: none; }
html[data-motion="reduced"] [data-enter="1"],
html[data-motion="reduced"] [data-ack="1"] { animation: none; }
`;

let installed = false;

export function installWebTheme(): void {
  if (installed || Platform.OS !== "web" || typeof document === "undefined") {
    return;
  }
  installed = true;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href =
    "https://fonts.googleapis.com/css2?family=Nunito:ital,wght@0,500;0,600;0,700;0,800;1,500&display=swap";
  document.head.appendChild(link);
  const style = document.createElement("style");
  style.setAttribute("data-rubberducky-theme", "true");
  style.textContent = WEB_CSS;
  document.head.appendChild(style);
}

export function useDocumentTheme(theme: BoardTheme, motion: MotionMode): void {
  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return;
    const root = document.documentElement;
    root.style.setProperty("--rd-focus", theme.focusOutline);
    root.style.setProperty("--rd-canvas", theme.board);
    root.style.backgroundColor = theme.board;
    document.body.style.backgroundColor = theme.board;
    root.dataset.motion = motion;
  }, [motion, theme]);
}

type WebData = { dataSet?: Record<string, string> };

export function enterProps(motion: MotionMode): WebData {
  if (Platform.OS !== "web" || motion !== "full") return {};
  return { dataSet: { enter: "1" } };
}

export function ackProps(motion: MotionMode): WebData {
  if (Platform.OS !== "web" || motion !== "full") return {};
  return { dataSet: { ack: "1" } };
}

export function statusProps(state: string): WebData {
  if (Platform.OS !== "web") return {};
  return { dataSet: { status: state } };
}
