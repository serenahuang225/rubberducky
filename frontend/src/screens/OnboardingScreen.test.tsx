import { fireEvent, render } from '@testing-library/react-native';
import React from 'react';

import { PERSONALITIES } from '../api/contracts';

import { OnboardingScreen, PERSONALITY_INFO } from './OnboardingScreen';

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
  it('offers the five ducks and no companion look', () => {
    const screen = renderOnboarding();
    for (const personality of PERSONALITIES) {
      expect(screen.getByTestId(`personality-${personality}`)).toBeTruthy();
    }
    expect(screen.queryByText(/choose a companion/i)).toBeNull();
    expect(screen.queryByText('Sunny the duck')).toBeNull();
    expect(screen.queryByText('Rowan')).toBeNull();
    expect(screen.queryByText('Kai')).toBeNull();
    expect(screen.getByTestId('onboarding-start')).toBeTruthy();
  });

  it('keeps the start button disabled until a duck is chosen', () => {
    const onComplete = jest.fn();
    const screen = renderOnboarding(onComplete);
    const start = screen.getByTestId('onboarding-start');
    expect(start.props.accessibilityState?.disabled).toBe(true);

    fireEvent.press(screen.getByTestId('personality-janelle'));
    expect(screen.getByTestId('onboarding-start').props.accessibilityState?.disabled).toBe(false);

    fireEvent.press(screen.getByTestId('onboarding-start'));
    expect(onComplete).toHaveBeenCalledWith(
      expect.objectContaining({ personality: 'janelle' }),
    );
    expect(onComplete.mock.calls[0][0]).not.toHaveProperty('appearance');
  });

  it.each(PERSONALITIES)('accepts %s on its own', (personality) => {
    const onComplete = jest.fn();
    const screen = renderOnboarding(onComplete);
    fireEvent.press(screen.getByTestId(`personality-${personality}`));
    fireEvent.press(screen.getByTestId('onboarding-start'));
    expect(onComplete).toHaveBeenCalledWith(
      expect.objectContaining({ personality }),
    );
  });

  it('lets the learner change ducks before starting', () => {
    const onComplete = jest.fn();
    const screen = renderOnboarding(onComplete);
    fireEvent.press(screen.getByTestId('personality-zeeshan'));
    fireEvent.press(screen.getByTestId('personality-vincent'));
    fireEvent.press(screen.getByTestId('onboarding-start'));
    expect(onComplete).toHaveBeenCalledWith(
      expect.objectContaining({ personality: 'vincent' }),
    );
  });

  it('words every choice without competence stereotypes', () => {
    const screen = renderOnboarding();
    expect(
      screen.getByText(/every duck stays respectful of you/i),
    ).toBeTruthy();
    expect(
      screen.getByText(/never what it thinks you can do/i),
    ).toBeTruthy();
    const copy = Object.values(PERSONALITY_INFO)
      .flatMap((info) => [info.name, info.blurb])
      .join(' ')
      .toLowerCase();
    for (const banned of ['smart', 'clever', 'advanced', 'expert', 'genius', 'beginner']) {
      expect(copy).not.toContain(banned);
    }
  });
});
