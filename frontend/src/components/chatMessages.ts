/**
 * Turn the session's tutor outcomes into a short conversation.
 * The question is shown once, then each step the learner typed and each reply.
 */

import type { TutorTurnResult } from "../api/contracts";

export type ChatRole = "you" | "tutor";

export type ChatMessage = {
  id: string;
  role: ChatRole;
  text: string;
};

export function isGoodJob(text: string): boolean {
  return /^good job\b/i.test(text.trim());
}

export function messagesFromTurns(turns: readonly TutorTurnResult[]): ChatMessage[] {
  const messages: ChatMessage[] = [];
  let shownQuestion = "";
  for (const turn of turns) {
    if (turn.status !== "committed") continue;
    const question = turn.current_problem?.statement.trim() ?? "";
    if (question.length > 0 && question !== shownQuestion) {
      messages.push({ id: `question-${turn.turn_id}`, role: "you", text: question });
      shownQuestion = question;
    }
    const said = turn.student_input?.text?.trim() ?? "";
    if (said.length > 0 && said !== question) {
      messages.push({ id: `you-${turn.turn_id}`, role: "you", text: said });
    }
    const reply = turn.utterance?.trim() ?? "";
    if (reply.length > 0) {
      messages.push({ id: `tutor-${turn.turn_id}`, role: "tutor", text: reply });
    }
  }
  return messages;
}
