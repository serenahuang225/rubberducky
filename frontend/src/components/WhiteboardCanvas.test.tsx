import { fireEvent, render } from '@testing-library/react-native';
import React from 'react';

import { getTheme } from '../board/palette';
import type { SceneObjectRecord } from '../board/sceneTypes';

import { BoardInputLayer } from './BoardInputLayer';
import { describeObject, objectBounds, orderedObjects } from './SceneObjectView';
import { WhiteboardCanvas } from './WhiteboardCanvas';

const theme = getTheme('paper');

function object(partial: Partial<SceneObjectRecord> & { id: string }): SceneObjectRecord {
  return {
    author_role: 'student',
    semantic_role: 'work',
    kind: 'path',
    payload: {},
    ...partial,
  };
}

describe('describeObject (color-independent author labels)', () => {
  it('distinguishes authors and content without relying on color', () => {
    expect(
      describeObject(object({ id: 's1', payload: { points: [{ x: 1, y: 1 }, { x: 2, y: 2 }] } })),
    ).toBe('Your pen stroke');
    expect(describeObject(object({ id: 's2', payload: { points: [{ x: 1, y: 1 }] } }))).toBe(
      'Your dot',
    );
    expect(
      describeObject(
        object({
          id: 't1',
          author_role: 'tutor',
          semantic_role: 'problem_statement',
          kind: 'text',
          payload: { text: '2(x + 3) = 14', x: 80, y: 120 },
        }),
      ),
    ).toBe('Tutor posed the problem: "2(x + 3) = 14"');
    expect(
      describeObject(
        object({ id: 't2', author_role: 'tutor', semantic_role: 'grouping_mark', kind: 'bracket' }),
      ),
    ).toBe('Tutor grouping mark around the parentheses');
    expect(
      describeObject(
        object({
          id: 't3',
          author_role: 'tutor',
          semantic_role: 'annotation',
          kind: 'add_math',
          payload: { text: '2x + 6', at: { x: 10, y: 10 } },
        }),
      ),
    ).toBe('Tutor note: "2x + 6"');
  });
});

describe('scene object bounds', () => {
  it('computes bounds for paths, text and shapes', () => {
    expect(
      objectBounds(
        object({ id: 'p', payload: { points: [{ x: 10, y: 20 }, { x: 40, y: 5 }] } }),
      ),
    ).toEqual({ minX: 10, minY: 5, maxX: 40, maxY: 20 });
    const text = objectBounds(
      object({ id: 't', kind: 'text', payload: { text: 'x = 4', x: 80, y: 120 } }),
    );
    expect(text).not.toBeNull();
    expect(text!.minX).toBeLessThan(80);
    expect(text!.maxX).toBeGreaterThan(80);
    const shape = objectBounds(
      object({
        id: 'r',
        kind: 'rectangle',
        payload: { start: { x: 5, y: 50 }, end: { x: 25, y: 10 } },
      }),
    );
    expect(shape).toEqual({ minX: 5, minY: 10, maxX: 25, maxY: 50 });
  });
});

describe('orderedObjects', () => {
  it('paints highlight washes and focus frames underneath ink', () => {
    const ink1 = object({ id: 'ink1' });
    const highlight = object({ id: 'h', author_role: 'tutor', kind: 'highlight' });
    const ink2 = object({ id: 'ink2' });
    const focus = object({ id: 'f', author_role: 'tutor', kind: 'focus_region' });
    const ordered = orderedObjects([ink1, highlight, ink2, focus]);
    expect(ordered.map((o) => o.id)).toEqual(['h', 'f', 'ink1', 'ink2']);
  });
});

describe('WhiteboardCanvas', () => {
  const noop = () => undefined;

  it('renders an accessible board summary and a color-independent contents list', () => {
    const objects = [
      object({ id: 's1', payload: { points: [{ x: 1, y: 1 }, { x: 30, y: 30 }] } }),
      object({
        id: 't1',
        author_role: 'tutor',
        semantic_role: 'problem_statement',
        kind: 'text',
        payload: { text: '2(x + 3) = 14', x: 80, y: 120 },
      }),
    ];
    const screen = render(
      <WhiteboardCanvas
        testID="whiteboard"
        objects={objects}
        theme={theme}
        mode="draw"
        onStroke={noop}
        onEraseAt={noop}
      />,
    );
    const board = screen.getByTestId('whiteboard');
    expect(board.props.accessibilityLabel).toBe('Whiteboard: 1 of your marks, 1 tutor marks');
    expect(screen.getByText('Your pen stroke')).toBeTruthy();
    expect(screen.getByText('Tutor posed the problem: "2(x + 3) = 14"')).toBeTruthy();
  });

  it('describes an empty board honestly', () => {
    const screen = render(
      <WhiteboardCanvas
        testID="whiteboard"
        objects={[]}
        theme={theme}
        mode="draw"
        onStroke={noop}
        onEraseAt={noop}
      />,
    );
    expect(screen.getByTestId('whiteboard').props.accessibilityLabel).toBe('Whiteboard, empty');
    expect(screen.getByText('The board is empty.')).toBeTruthy();
  });

  it('renders every durable object kind without throwing', () => {
    const objects: SceneObjectRecord[] = [
      object({ id: 'path', payload: { points: [{ x: 1, y: 1 }, { x: 9, y: 9 }], width: 3 } }),
      object({ id: 'dot', payload: { points: [{ x: 100, y: 100 }], width: 3 } }),
      object({
        id: 'text',
        author_role: 'tutor',
        semantic_role: 'problem_statement',
        kind: 'text',
        payload: { text: '2(x + 3) = 14', x: 80, y: 120, color_role: 'tutor' },
      }),
      object({
        id: 'math',
        author_role: 'tutor',
        semantic_role: 'annotation',
        kind: 'add_math',
        payload: { text: '2x + 6', at: { x: 200, y: 300 }, color_role: 'tutor' },
      }),
      ...(['circle', 'rectangle', 'line', 'bracket', 'arrow'] as const).map((kind) =>
        object({
          id: `shape-${kind}`,
          author_role: 'tutor',
          semantic_role: 'grouping_mark',
          kind,
          payload: { start: { x: 100, y: 150 }, end: { x: 300, y: 170 }, color_role: 'tutor' },
        }),
      ),
      object({
        id: 'hl',
        author_role: 'tutor',
        semantic_role: 'emphasis',
        kind: 'highlight',
        payload: { target_object_id: 'text', term: '(x + 3)', color_role: 'tutor' },
      }),
      object({
        id: 'focus',
        author_role: 'tutor',
        semantic_role: 'focus',
        kind: 'focus_region',
        payload: { start: { x: 50, y: 60 }, end: { x: 500, y: 200 }, color_role: 'tutor' },
      }),
    ];
    const screen = render(
      <WhiteboardCanvas
        testID="whiteboard"
        objects={objects}
        theme={theme}
        mode="draw"
        onStroke={noop}
        onEraseAt={noop}
      />,
    );
    expect(screen.getByTestId('whiteboard')).toBeTruthy();
    expect(screen.getByText('Tutor highlight on your work')).toBeTruthy();
    expect(screen.getByText('Tutor focus frame')).toBeTruthy();
  });

  it('renders queued strokes as visibly unsaved, never as committed work', () => {
    const screen = render(
      <WhiteboardCanvas
        testID="whiteboard"
        objects={[object({ id: 's1', payload: { points: [{ x: 1, y: 1 }, { x: 9, y: 9 }] } })]}
        pendingStrokes={[
          { id: 'pending-1', points: [{ x: 100, y: 100 }, { x: 200, y: 120 }] },
          { id: 'pending-2', points: [{ x: 300, y: 300 }] },
        ]}
        theme={theme}
        mode="draw"
        onStroke={noop}
        onEraseAt={noop}
      />,
    );
    // Committed work keeps its normal label; queued marks say "not saved yet".
    expect(screen.getByText('Your pen stroke')).toBeTruthy();
    expect(screen.getByText('Your pen stroke (not saved yet)')).toBeTruthy();
    expect(screen.getByText('Your dot (not saved yet)')).toBeTruthy();
  });

  it('ignores board input until the first real layout measurement', () => {
    // The placeholder 1x1 fit transform would squash any early point into a board
    // corner; input must stay disabled until onLayout reports a real size.
    const screen = render(
      <WhiteboardCanvas
        testID="whiteboard"
        objects={[]}
        theme={theme}
        mode="draw"
        onStroke={noop}
        onEraseAt={noop}
      />,
    );
    expect(screen.UNSAFE_getByType(BoardInputLayer).props.disabled).toBe(true);
    fireEvent(screen.getByTestId('whiteboard'), 'onLayout', {
      nativeEvent: { layout: { width: 800, height: 600 } },
    });
    expect(screen.UNSAFE_getByType(BoardInputLayer).props.disabled).toBe(false);
  });

  it('keeps input disabled after layout while a save is in flight', () => {
    const screen = render(
      <WhiteboardCanvas
        testID="whiteboard"
        objects={[]}
        theme={theme}
        mode="draw"
        inputDisabled
        onStroke={noop}
        onEraseAt={noop}
      />,
    );
    fireEvent(screen.getByTestId('whiteboard'), 'onLayout', {
      nativeEvent: { layout: { width: 800, height: 600 } },
    });
    expect(screen.UNSAFE_getByType(BoardInputLayer).props.disabled).toBe(true);
  });

  it('ignores a malformed payload instead of crashing the board', () => {
    const objects = [
      object({ id: 'bad', kind: 'path', payload: { points: [{ x: Number.NaN }] } }),
      object({ id: 'unknown-kind', kind: 'teleport', payload: {} }),
    ];
    const screen = render(
      <WhiteboardCanvas
        testID="whiteboard"
        objects={objects}
        theme={theme}
        mode="draw"
        onStroke={noop}
        onEraseAt={noop}
      />,
    );
    expect(screen.getByTestId('whiteboard')).toBeTruthy();
  });
});
