import { act, fireEvent, render } from '@testing-library/react-native';
import React from 'react';

import type { WaitPreference, WaitState } from '../api/contracts';
import { getTheme } from '../board/palette';
import { WAIT_PREFERENCE, WAIT_STATE } from '../testing/teachingFixtures';

import { WaitControls } from './WaitControls';

const theme = getTheme('paper');
const preference = WAIT_PREFERENCE as WaitPreference;

function renderControls(overrides: Partial<React.ComponentProps<typeof WaitControls>> = {}) {
  const onChangeSeconds = jest.fn();
  const screen = render(
    <WaitControls
      theme={theme}
      hintAvailable={false}
      preference={preference}
      preferenceError={null}
      onChangeSeconds={onChangeSeconds}
      {...overrides}
    />,
  );
  return { ...screen, onChangeSeconds };
}

describe('WaitControls', () => {
  it('stays closed and quiet until the learner opens it', () => {
    const screen = renderControls();
    expect(screen.queryByTestId('wait-settings')).toBeNull();
    expect(screen.queryByTestId('quiet-hint')).toBeNull();
  });

  it('shows the hint note only when a hint is available, as plain text and not a live region', () => {
    const screen = renderControls({ hintAvailable: true });
    const note = screen.getByTestId('quiet-hint');
    expect(note.props.accessibilityLiveRegion).toBeUndefined();
    expect(screen.queryByText(/check in|are you stuck|need help\?/i)).toBeNull();
  });

  it('steps by 15 seconds and refuses to step past the server bounds', () => {
    const atMin = renderControls({ preference: { ...preference, wait_seconds: 5, source: 'preference' } });
    fireEvent.press(atMin.getByTestId('wait-settings-toggle'));
    expect(atMin.getByTestId('wait-decrease').props.accessibilityState.disabled).toBe(true);
    fireEvent.press(atMin.getByTestId('wait-decrease'));
    expect(atMin.onChangeSeconds).not.toHaveBeenCalled();
    fireEvent.press(atMin.getByTestId('wait-increase'));
    expect(atMin.onChangeSeconds).toHaveBeenCalledWith(20);

    const atMax = renderControls({ preference: { ...preference, wait_seconds: 300, source: 'preference' } });
    fireEvent.press(atMax.getByTestId('wait-settings-toggle'));
    expect(atMax.getByTestId('wait-increase').props.accessibilityState.disabled).toBe(true);
    fireEvent.press(atMax.getByTestId('wait-decrease'));
    expect(atMax.onChangeSeconds).toHaveBeenCalledWith(285);
  });

  it('is unavailable, not guessed, until the server preference is known', () => {
    const screen = renderControls({ preference: null });
    expect(screen.getByTestId('wait-settings-toggle').props.accessibilityState.disabled).toBe(true);
  });

  it('shows a save error without changing the displayed setting', () => {
    const screen = renderControls({ preferenceError: 'The waiting time could not be saved, so it is unchanged.' });
    fireEvent.press(screen.getByTestId('wait-settings-toggle'));
    expect(screen.getByTestId('wait-error')).toBeTruthy();
    expect(screen.getByTestId('wait-value').props.children).toContain('45');
  });
});


describe('hint countdown', () => {
  afterEach(() => jest.useRealTimers());

  it('counts down from server timestamps and quietly offers help at zero', () => {
    jest.useFakeTimers();
    const waitState = { ...WAIT_STATE, now: '2026-10-17T16:39:23Z', quiet_hint_at: '2026-10-17T16:39:26Z' } as WaitState;
    const screen = renderControls({ waitState, partnerName: 'Mary' });
    expect(screen.getByText('Hint offer in 0:03')).toBeTruthy();
    act(() => jest.advanceTimersByTime(2000));
    expect(screen.getByText('Hint offer in 0:01')).toBeTruthy();
    act(() => jest.advanceTimersByTime(1000));
    expect(screen.getByText('Mary: Want a hint?')).toBeTruthy();
    expect(screen.getByRole('progressbar').props.accessibilityValue.now).toBe(100);
  });

  it('does not invent a countdown when server timing is unavailable', () => {
    const screen = renderControls();
    expect(screen.queryByTestId('wait-countdown')).toBeNull();
  });
});
