/**
 * Native board input: an unfinished gesture must be cancelled, not committed, when the
 * board becomes disabled (a save/tutor turn took the busy guard) mid-stroke.
 */

import { fireEvent, render } from '@testing-library/react-native';
import React from 'react';
import { View } from 'react-native';

import { computeFitTransform } from '../board/geometry';

import { BoardInputLayer } from './BoardInputLayer';

const transform = computeFitTransform(1600, 1200);

function touch(id: number, x: number, y: number) {
  return { identifier: id, locationX: x, locationY: y };
}

function setup() {
  const onPreview = jest.fn();
  const onStroke = jest.fn();
  const onStrokeCancel = jest.fn();
  const onTap = jest.fn();
  const element = (disabled: boolean) => (
    <BoardInputLayer
      mode="draw"
      disabled={disabled}
      getTransform={() => transform}
      onPreview={onPreview}
      onStroke={onStroke}
      onStrokeCancel={onStrokeCancel}
      onTap={onTap}
    />
  );
  const screen = render(element(false));
  const host = () => screen.UNSAFE_getAllByType(View)[0];
  return {
    screen,
    host,
    onPreview,
    onStroke,
    onStrokeCancel,
    disable: () => screen.rerender(element(true)),
    enable: () => screen.rerender(element(false)),
    start: (id: number, x: number, y: number) =>
      fireEvent(host(), 'touchStart', {
        nativeEvent: { changedTouches: [touch(id, x, y)], touches: [touch(id, x, y)] },
      }),
    move: (id: number, x: number, y: number) =>
      fireEvent(host(), 'touchMove', {
        nativeEvent: { changedTouches: [touch(id, x, y)], touches: [touch(id, x, y)] },
      }),
    end: (id: number, x: number, y: number) =>
      fireEvent(host(), 'touchEnd', {
        nativeEvent: { changedTouches: [touch(id, x, y)], touches: [] },
      }),
  };
}

describe('native BoardInputLayer disable-while-drawing', () => {
  it('commits a normal stroke while enabled', () => {
    const t = setup();
    t.start(1, 10, 10);
    t.move(1, 20, 20);
    t.end(1, 20, 20);
    expect(t.onStroke).toHaveBeenCalledTimes(1);
    expect(t.onStroke.mock.calls[0][0]).toEqual([
      { x: 10, y: 10 },
      { x: 20, y: 20 },
    ]);
  });

  it('cancels an unfinished stroke when disabled and never commits it on release', () => {
    const t = setup();
    t.start(1, 10, 10);
    t.move(1, 20, 20);
    expect(t.onStrokeCancel).not.toHaveBeenCalled();

    t.disable();
    // The preview is cleared as part of the cancellation, not left for a silent drop.
    expect(t.onStrokeCancel).toHaveBeenCalledTimes(1);

    t.end(1, 20, 20);
    expect(t.onStroke).not.toHaveBeenCalled();
  });

  it('starts clean after re-enabling, without joining the cancelled points', () => {
    const t = setup();
    t.start(1, 10, 10);
    t.move(1, 20, 20);
    t.disable();
    t.end(1, 20, 20);
    t.enable();

    t.start(2, 300, 300);
    t.move(2, 310, 305);
    t.end(2, 310, 305);
    expect(t.onStroke).toHaveBeenCalledTimes(1);
    expect(t.onStroke.mock.calls[0][0]).toEqual([
      { x: 300, y: 300 },
      { x: 310, y: 305 },
    ]);
  });

  it('ignores moves while disabled without starting a phantom stroke', () => {
    const t = setup();
    t.disable();
    t.start(1, 10, 10);
    t.move(1, 20, 20);
    t.end(1, 20, 20);
    expect(t.onStroke).not.toHaveBeenCalled();
    expect(t.onPreview).not.toHaveBeenCalled();
  });
});
