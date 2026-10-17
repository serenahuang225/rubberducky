/** @jest-environment jsdom */
/**
 * Web board input: an unfinished pointer gesture must be cancelled, not committed, when
 * the board becomes disabled mid-stroke. The DOM host is a minimal EventTarget stand-in
 * supplied through createNodeMock, so the real listener wiring is exercised.
 */

import { render } from '@testing-library/react-native';
import React from 'react';

import { computeFitTransform } from '../board/geometry';

import { BoardInputLayer } from './BoardInputLayer.web';

// Render View as a plain host element so createNodeMock can stand in for the DOM node.
jest.mock('react-native', () => {
  const actual = jest.requireActual('react-native');
  const ReactModule = jest.requireActual<typeof import('react')>('react');
  const HostView = ReactModule.forwardRef(function HostView(
    props: { children?: React.ReactNode },
    ref: React.Ref<unknown>,
  ) {
    return ReactModule.createElement('View', { ref }, props.children);
  });
  return new Proxy(actual, { get: (target, key) => (key === 'View' ? HostView : target[key]) });
});

const transform = computeFitTransform(1600, 1200);

type Listener = (event: unknown) => void;

function makeHost() {
  const listeners = new Map<string, Set<Listener>>();
  return {
    style: {} as Record<string, string>,
    addEventListener: (type: string, fn: Listener) => {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type)!.add(fn);
    },
    removeEventListener: (type: string, fn: Listener) => listeners.get(type)?.delete(fn),
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1600, height: 1200 }),
    setPointerCapture: () => undefined,
    dispatch(type: string, init: Record<string, unknown>) {
      const event = {
        pointerId: 1,
        pointerType: 'mouse',
        button: 0,
        buttons: 1,
        isPrimary: true,
        clientX: 0,
        clientY: 0,
        preventDefault: () => undefined,
        ...init,
      };
      listeners.get(type)?.forEach((fn) => fn(event));
    },
  };
}

function setup() {
  const host = makeHost();
  const onPreview = jest.fn();
  const onStroke = jest.fn();
  const onStrokeCancel = jest.fn();
  const element = (disabled: boolean) => (
    <BoardInputLayer
      mode="draw"
      disabled={disabled}
      getTransform={() => transform}
      onPreview={onPreview}
      onStroke={onStroke}
      onStrokeCancel={onStrokeCancel}
      onTap={jest.fn()}
    />
  );
  const screen = render(element(false), { createNodeMock: () => host });
  return {
    host,
    screen,
    onPreview,
    onStroke,
    onStrokeCancel,
    disable: () => screen.rerender(element(true)),
    enable: () => screen.rerender(element(false)),
    down: (id: number, x: number, y: number) =>
      host.dispatch('pointerdown', { pointerId: id, clientX: x, clientY: y }),
    move: (id: number, x: number, y: number) =>
      host.dispatch('pointermove', { pointerId: id, clientX: x, clientY: y }),
    up: (id: number, x: number, y: number) =>
      host.dispatch('pointerup', { pointerId: id, clientX: x, clientY: y, buttons: 0 }),
  };
}

describe('web BoardInputLayer disable-while-drawing', () => {
  it('commits a normal stroke while enabled', () => {
    const t = setup();
    t.down(1, 10, 10);
    t.move(1, 20, 20);
    t.up(1, 20, 20);
    expect(t.onStroke).toHaveBeenCalledTimes(1);
    expect(t.onStroke.mock.calls[0][0]).toEqual([
      { x: 10, y: 10 },
      { x: 20, y: 20 },
    ]);
  });

  it('cancels an unfinished stroke when disabled and never commits it on release', () => {
    const t = setup();
    t.down(1, 10, 10);
    t.move(1, 20, 20);
    expect(t.onStrokeCancel).not.toHaveBeenCalled();

    t.disable();
    expect(t.onStrokeCancel).toHaveBeenCalledTimes(1);

    t.up(1, 20, 20);
    expect(t.onStroke).not.toHaveBeenCalled();
  });

  it('starts clean after re-enabling, without joining the cancelled points', () => {
    const t = setup();
    t.down(1, 10, 10);
    t.move(1, 20, 20);
    t.disable();
    t.up(1, 20, 20);
    t.enable();

    t.down(2, 300, 300);
    t.move(2, 310, 305);
    t.up(2, 310, 305);
    expect(t.onStroke).toHaveBeenCalledTimes(1);
    expect(t.onStroke.mock.calls[0][0]).toEqual([
      { x: 300, y: 300 },
      { x: 310, y: 305 },
    ]);
  });
});
