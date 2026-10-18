import { fireEvent, render, screen } from '@testing-library/react-native';
import React from 'react';
import { Text } from 'react-native';

import { tutorTurnResultSchema } from '../api/contracts';
import { getTheme } from '../board/palette';
import fallbackDistribution from '../interactives/fixtures/released-fallback-distribution.json';
import fallbackGrouping from '../interactives/fixtures/released-fallback-grouping.json';
import { METHOD_SLIP_TURN } from '../testing/teachingFixtures';

import { TeachingContext } from './TeachingContext';

const theme = getTheme('paper');
const turn = tutorTurnResultSchema.parse(METHOD_SLIP_TURN);
const quiet = { explanationPayload: fallbackDistribution };

function readout(): string {
  const node = screen.getByTestId('manipulative-readout');
  return [node.props.children].flat().join('');
}

describe('TeachingContext', () => {
  it('keeps the explanation control before any committed turn, without the inspector', () => {
    render(<TeachingContext theme={theme} turn={null} {...quiet} />);
    expect(screen.queryByTestId('teaching-context')).toBeNull();
    expect(screen.getByTestId('learner-explanation')).toBeTruthy();
    expect(screen.getByTestId('explanation-source-label').props.children).toMatch(
      /pre-vetted.*not generated/i,
    );
  });

  it('collapses the inspector again when a newer turn arrives', () => {
    const view = render(<TeachingContext theme={theme} turn={turn} {...quiet} />);
    fireEvent.press(screen.getByTestId('diagnostic-toggle'));
    expect(screen.getByTestId('diagnostic-panel')).toBeTruthy();
    view.rerender(
      <TeachingContext theme={theme} turn={{ ...turn, turn_id: 'turn-2' }} {...quiet} />,
    );
    expect(screen.queryByTestId('diagnostic-panel')).toBeNull();
  });

  it('states plainly when a move had no hypothesis but still explains why', () => {
    render(
      <TeachingContext theme={theme} turn={{ ...turn, hypothesis: null }} {...quiet} />,
    );
    fireEvent.press(screen.getByTestId('diagnostic-toggle'));
    expect(screen.getByText('No hypothesis was formed for this move.')).toBeTruthy();
    expect(screen.getByTestId('diagnostic-justification')).toBeTruthy();
  });

  it('caps a long source list and keeps the full ids in the accessible label', () => {
    const ids = Array.from({ length: 9 }, (_, index) => `source-${index}-0123456789`);
    render(
      <TeachingContext
        theme={theme}
        turn={{ ...turn, hypothesis: { ...turn.hypothesis!, source_ids: ids } }}
        {...quiet}
      />,
    );
    fireEvent.press(screen.getByTestId('diagnostic-toggle'));
    const sources = screen.getByTestId('diagnostic-sources');
    expect(sources.props.accessibilityLabel).toContain(ids[8]);
    expect(String(sources.props.children)).toContain('+3 more');
  });

  it('mounts the parsed grouping manipulative for the current concept and keeps the board', async () => {
    let requested = '';
    render(
      <TeachingContext
        theme={theme}
        turn={{
          ...turn,
          current_problem: {
            problem_id: 'problem-1',
            attempt_id: 'attempt-1',
            statement: '3 groups of 4',
            kind: 'explanation',
            concept_id: 'concept.grouping',
            statement_object_id: null,
          },
        }}
        loadExplanation={async (request) => {
          requested = request.concept_id;
          return {
            schema_version: 'learner-explanation.v1',
            live_services_contacted: false,
            notice:
              "Factory and Daytona were not contacted. This is the app's pre-vetted explanation, not a generated release.",
            release: fallbackGrouping,
          };
        }}
      />,
    );
    expect(await screen.findByTestId('explanation-manipulative')).toBeTruthy();
    expect(requested).toBe('concept.grouping');
    expect(screen.getByTestId('factory-state-label').props.children).toBe('Factory: disabled');
    expect(screen.getByTestId('daytona-state-label').props.children).toBe('Daytona: disabled');
    expect(screen.getByTestId('explanation-source-label').props.children).toMatch(/not generated/i);
    expect(screen.queryByText(/generated explanation that passed/i)).toBeNull();
    expect(readout()).toBe('3 groups × 4 counters each = 12 counters');
    fireEvent.press(screen.getByTestId('groups-more'));
    expect(readout()).toBe('4 groups × 4 counters each = 16 counters');
  });

  it('keeps a sibling board when the loaded explanation is rejected', async () => {
    render(
      <>
        <Text testID="student-board">2x + 6 = 14</Text>
        <TeachingContext
          theme={theme}
          turn={turn}
          loadExplanation={async () => ({
            schema_version: 'learner-explanation.v1',
            live_services_contacted: false,
            notice: 'not contacted',
            release: { schema_version: 'released-explanation.v1' },
          })}
        />
      </>,
    );
    expect(await screen.findByTestId('learner-explanation-error')).toBeTruthy();
    expect(screen.getByTestId('student-board').props.children).toBe('2x + 6 = 14');
    expect(screen.getByTestId('teaching-context')).toBeTruthy();
    expect(screen.queryByTestId('explanation-manipulative')).toBeNull();
  });
});
