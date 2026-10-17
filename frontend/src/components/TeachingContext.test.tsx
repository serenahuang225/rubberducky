import { fireEvent, render } from '@testing-library/react-native';
import React from 'react';

import { tutorTurnResultSchema } from '../api/contracts';
import { getTheme } from '../board/palette';
import { METHOD_SLIP_TURN } from '../testing/teachingFixtures';

import { TeachingContext } from './TeachingContext';

const theme = getTheme('paper');
const turn = tutorTurnResultSchema.parse(METHOD_SLIP_TURN);

describe('TeachingContext', () => {
  it('renders nothing before any committed turn', () => {
    const screen = render(<TeachingContext theme={theme} turn={null} />);
    expect(screen.queryByTestId('teaching-context')).toBeNull();
  });

  it('collapses the inspector again when a newer turn arrives', () => {
    const screen = render(<TeachingContext theme={theme} turn={turn} />);
    fireEvent.press(screen.getByTestId('diagnostic-toggle'));
    expect(screen.getByTestId('diagnostic-panel')).toBeTruthy();
    screen.rerender(
      <TeachingContext theme={theme} turn={{ ...turn, turn_id: 'turn-2' }} />,
    );
    expect(screen.queryByTestId('diagnostic-panel')).toBeNull();
  });

  it('states plainly when a move had no hypothesis but still explains why', () => {
    const screen = render(
      <TeachingContext theme={theme} turn={{ ...turn, hypothesis: null }} />,
    );
    fireEvent.press(screen.getByTestId('diagnostic-toggle'));
    expect(screen.getByText('No hypothesis was formed for this move.')).toBeTruthy();
    expect(screen.getByTestId('diagnostic-justification')).toBeTruthy();
  });

  it('caps a long source list and keeps the full ids in the accessible label', () => {
    const ids = Array.from({ length: 9 }, (_, index) => `source-${index}-0123456789`);
    const screen = render(
      <TeachingContext
        theme={theme}
        turn={{ ...turn, hypothesis: { ...turn.hypothesis!, source_ids: ids } }}
      />,
    );
    fireEvent.press(screen.getByTestId('diagnostic-toggle'));
    const sources = screen.getByTestId('diagnostic-sources');
    expect(sources.props.accessibilityLabel).toContain(ids[8]);
    expect(String(sources.props.children)).toContain('+3 more');
  });
});
