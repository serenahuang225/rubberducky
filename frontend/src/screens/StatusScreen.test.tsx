import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import React from 'react';

import { fetchServiceStatus, type FetchLike, type ServiceStatus } from '../api/health';
import { StatusScreen } from './StatusScreen';

const status: ServiceStatus = {
  health: {
    schema_version: 'health.v1',
    status: 'ok',
    service: 'rubberducky-api',
    version: '0.1.0',
    time_utc: '2026-10-16T12:00:00Z',
  },
  model: {
    schema_version: 'model-readiness.v1',
    provider: 'mock',
    state: 'ready',
    ready: true,
    is_mock: true,
    label: 'Deterministic mock tutor (not a language model)',
    model_id: null,
    model_revision: null,
    detail: 'Scripted responses for development and tests.',
  },
};

describe('StatusScreen', () => {
  it('shows the connected service and the labeled mock tutor mode', async () => {
    render(<StatusScreen loadStatus={() => Promise.resolve(status)} />);
    expect(await screen.findByText('Tutor service connected')).toBeTruthy();
    expect(screen.getByTestId('model-status')).toHaveTextContent(
      'Tutor mode: Deterministic mock tutor (not a language model)',
    );
  });

  it('offers a retry when the service is unavailable', async () => {
    const loadStatus = jest
      .fn<Promise<ServiceStatus>, []>()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(status);
    render(<StatusScreen loadStatus={loadStatus} />);
    fireEvent.press(await screen.findByRole('button', { name: 'Try connecting again' }));
    await waitFor(() => expect(screen.getByText('Tutor service connected')).toBeTruthy());
    expect(loadStatus).toHaveBeenCalledTimes(2);
  });
});

describe('fetchServiceStatus', () => {
  it('rejects responses that do not match the health contract', async () => {
    const fetchImpl: FetchLike = () =>
      Promise.resolve(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }));
    await expect(fetchServiceStatus('http://127.0.0.1:3100', fetchImpl)).rejects.toThrow();
  });
});
