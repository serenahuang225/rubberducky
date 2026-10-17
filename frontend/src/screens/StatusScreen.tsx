import React, { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { fetchServiceStatus, type ServiceStatus } from '../api/health';
import { getApiBaseUrl } from '../config/apiBaseUrl';

type LoadState =
  | { kind: 'checking' }
  | { kind: 'connected'; status: ServiceStatus }
  | { kind: 'unavailable' };

type Props = {
  loadStatus?: () => Promise<ServiceStatus>;
};

const defaultLoadStatus = () => fetchServiceStatus(getApiBaseUrl());

export function StatusScreen({ loadStatus = defaultLoadStatus }: Props) {
  const [state, setState] = useState<LoadState>({ kind: 'checking' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    loadStatus()
      .then((status) => active && setState({ kind: 'connected', status }))
      .catch(() => active && setState({ kind: 'unavailable' }));
    return () => {
      active = false;
    };
  }, [loadStatus, attempt]);

  const retry = useCallback(() => {
    setState({ kind: 'checking' });
    setAttempt((previous) => previous + 1);
  }, []);

  const serviceText =
    state.kind === 'checking'
      ? 'Checking the tutor service…'
      : state.kind === 'connected'
        ? 'Tutor service connected'
        : 'Tutor service unavailable';

  return (
    <View style={styles.page}>
      <Text role="heading" style={styles.title}>
        Rubberducky
      </Text>
      <Text style={styles.subtitle}>A math tutor that helps you think it through.</Text>
      <View style={styles.card} accessibilityLiveRegion="polite">
        <Text testID="service-status" style={styles.status}>
          {serviceText}
        </Text>
        {state.kind === 'connected' ? (
          <Text testID="model-status" style={styles.detail}>
            Tutor mode: {state.status.model.label}
          </Text>
        ) : null}
        {state.kind === 'unavailable' ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Try connecting again"
            onPress={retry}
            style={styles.button}
          >
            <Text style={styles.buttonText}>Try again</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    backgroundColor: '#fcfcfa',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
    gap: 16,
  },
  title: { fontSize: 32, fontWeight: '600', color: '#1f2933' },
  subtitle: { fontSize: 18, color: '#3e4c59' },
  card: {
    minWidth: 320,
    padding: 20,
    gap: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#d9dde1',
    backgroundColor: '#ffffff',
  },
  status: { fontSize: 18, color: '#1f2933' },
  detail: { fontSize: 16, color: '#3e4c59' },
  button: {
    alignSelf: 'flex-start',
    minHeight: 44,
    paddingHorizontal: 16,
    justifyContent: 'center',
    borderRadius: 8,
    backgroundColor: '#2f4858',
  },
  buttonText: { color: '#ffffff', fontSize: 16, fontWeight: '600' },
});
