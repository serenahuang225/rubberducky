import { fireEvent, render } from '@testing-library/react-native';
import React from 'react';
import { StyleSheet } from 'react-native';

import type { KnowledgeMap } from '../api/contracts';
import { getTheme } from '../board/palette';

import { KnowledgeGraph } from './KnowledgeGraph';

it('reflows following nodes when a long memory card needs more vertical space', () => {
  const map = { notice: 'Private memory', nodes: [
    { concept_id: 'a', name: 'A concept with a long descriptive name', readiness_label: 'Developing',
      memories: ['A detailed memory that needs room to wrap across several lines'] },
    { concept_id: 'b', name: 'B concept', readiness_label: 'Not practiced yet', memories: [] },
  ], edges: [] } as unknown as KnowledgeMap;
  const view = render(<KnowledgeGraph map={map} theme={getTheme('paper')} />);
  const first = view.getByTestId('knowledge-node-a');
  fireEvent(first, 'layout', { nativeEvent: { layout: { width: 248, height: 600, x: 0, y: 0 } } });
  const a = StyleSheet.flatten(view.getByTestId('knowledge-node-a').props.style);
  const b = StyleSheet.flatten(view.getByTestId('knowledge-node-b').props.style);
  expect(b.top).toBeGreaterThanOrEqual(a.top + 600 + 40);
  expect(view.getByText(map.nodes[0].memories[0]).props.numberOfLines).toBeUndefined();
});
