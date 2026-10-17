import type { TutorTurnResult } from '../api/contracts';
import { METHOD_SLIP_TURN } from '../testing/teachingFixtures';

import { noticeForTurn } from './turnNotices';

function turn(status: string, codes: string[]): TutorTurnResult {
  return {
    ...METHOD_SLIP_TURN,
    status,
    rejections: codes.map((code) => ({ code, message: code })),
  } as unknown as TutorTurnResult;
}

describe('noticeForTurn', () => {
  it('has no notice for a committed turn', () => {
    expect(noticeForTurn(turn('committed', []))).toBeNull();
  });

  it('says a stopped reply was dropped while the work is saved', () => {
    expect(noticeForTurn(turn('superseded', ['interrupted']))).toMatch(/Stopped.*work is saved/);
  });

  it.each(['superseded_by_work', 'revision_changed', 'source_changed'])(
    'explains a reply replaced by changes (%s)',
    (code) => {
      expect(noticeForTurn(turn('superseded', [code]))).toMatch(/replaced.*work is kept/);
    },
  );

  it('is honest that a restart interrupted the reply and points to Help me', () => {
    const notice = noticeForTurn(turn('failed', ['restart_interrupted']));
    expect(notice).toMatch(/restarted before it finished/);
    expect(notice).toMatch(/work is saved/);
    expect(notice).toMatch(/Help me/);
  });

  it('keeps the rejected and generic wording', () => {
    expect(noticeForTurn(turn('rejected', ['plan_mismatch']))).toMatch(/could not use that turn/);
    expect(noticeForTurn(turn('failed', ['provider_error']))).toMatch(/did not complete/);
  });
});
