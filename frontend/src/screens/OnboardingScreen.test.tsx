import { fireEvent, render } from '@testing-library/react-native';
import React from 'react';

import { APPEARANCES, PERSONALITIES } from '../api/contracts';

import { APPEARANCE_INFO, OnboardingScreen, PERSONALITY_INFO } from './OnboardingScreen';

function renderOnboarding(onComplete = jest.fn()) {
  const utils = render(
    <OnboardingScreen
      submitting={false}
      errorMessage={null}
      showNameField
      onComplete={onComplete}
    />,
  );
  return { ...utils, onComplete };
}

describe('OnboardingScreen', () => {
  it('offers all three appearances and all five ducks as separate choices', () => {
    const screen = renderOnboarding();
    for (const appearance of APPEARANCES) {
      expect(screen.getByTestId(`appearance-${appearance}`)).toBeTruthy();
    }
    for (const personality of PERSONALITIES) {
      expect(screen.getByTestId(`personality-${personality}`)).toBeTruthy();
    }
    expect(screen.getByTestId('onboarding-start')).toBeTruthy();
  });

  it('keeps the start button disabled until both independent axes are chosen', () => {
    const onComplete = jest.fn();
    const screen = renderOnboarding(onComplete);
    const start = screen.getByTestId('onboarding-start');
    expect(start.props.accessibilityState?.disabled).toBe(true);

    fireEvent.press(screen.getByTestId('appearance-animal'));
    expect(screen.getByTestId('onboarding-start').props.accessibilityState?.disabled).toBe(true);
    fireEvent.press(screen.getByTestId('personality-janelle'));
    expect(screen.getByTestId('onboarding-start').props.accessibilityState?.disabled).toBe(false);

    fireEvent.press(screen.getByTestId('onboarding-start'));
    expect(onComplete).toHaveBeenCalledWith(
      expect.objectContaining({ appearance: 'animal', personality: 'janelle' }),
    );
  });

  it.each(APPEARANCES.flatMap((appearance) =>
    PERSONALITIES.map((personality) => [appearance, personality] as const),
  ))('accepts the independent pair %s + %s', (appearance, personality) => {
    const onComplete = jest.fn();
    const screen = renderOnboarding(onComplete);
    fireEvent.press(screen.getByTestId(`appearance-${appearance}`));
    fireEvent.press(screen.getByTestId(`personality-${personality}`));
    fireEvent.press(screen.getByTestId('onboarding-start'));
    expect(onComplete).toHaveBeenCalledWith(
      expect.objectContaining({ appearance, personality }),
    );
  });

  it('lets the learner change each axis independently before starting', () => {
    const onComplete = jest.fn();
    const screen = renderOnboarding(onComplete);
    fireEvent.press(screen.getByTestId('appearance-animal'));
    fireEvent.press(screen.getByTestId('appearance-older_adult'));
    fireEvent.press(screen.getByTestId('personality-zeeshan'));
    fireEvent.press(screen.getByTestId('personality-vincent'));
    fireEvent.press(screen.getByTestId('onboarding-start'));
    expect(onComplete).toHaveBeenCalledWith(
      expect.objectContaining({ appearance: 'older_adult', personality: 'vincent' }),
    );
  });

  it('words every choice without competence stereotypes', () => {
    const screen = renderOnboarding();
    // Kind framing is visible, and no copy ties appearance or style to ability.
    expect(
      screen.getByText(/every duck stays respectful of you/i),
    ).toBeTruthy();
    expect(
      screen.getByText(/never what it thinks you can do/i),
    ).toBeTruthy();
    const copy = [...Object.values(APPEARANCE_INFO), ...Object.values(PERSONALITY_INFO)]
      .flatMap((info) => [info.name, info.blurb])
      .join(' ')
      .toLowerCase();
    for (const banned of ['smart', 'clever', 'advanced', 'expert', 'genius', 'beginner']) {
      expect(copy).not.toContain(banned);
    }
  });
});
