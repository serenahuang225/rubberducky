/**
 * Plain-language notices for tutor turns that did not commit.
 *
 * The server reports why a reply was withdrawn (interrupted, replaced by newer work, source
 * changed, server restarted). Each message says the same thing: the learner's own work is
 * kept and only the tutor's reply was dropped. Nothing is inferred on the client.
 */

import type { TutorTurnResult } from '../api/contracts';

const REPLACED_CODES = new Set(['superseded_by_work', 'revision_changed', 'source_changed']);

/** The notice for a non-committed turn, or null when the turn committed. */
export function noticeForTurn(result: TutorTurnResult): string | null {
  if (result.status === 'committed') {
    return null;
  }
  const codes = result.rejections.map((rejection) => rejection.code);
  if (result.status === 'rejected') {
    return 'The tutor could not use that turn; your work is unchanged.';
  }
  if (result.status === 'superseded') {
    if (codes.includes('interrupted')) {
      return 'Stopped. Your work is saved and the unfinished reply was dropped.';
    }
    if (codes.some((code) => REPLACED_CODES.has(code))) {
      return 'That reply was replaced because your work or the board changed. Your work is kept.';
    }
  }
  if (result.status === 'failed' && codes.includes('restart_interrupted')) {
    return 'The tutor restarted before it finished. Your work is saved. Press Help me or send your step again.';
  }
  return 'The tutor turn did not complete; your work is unchanged.';
}
