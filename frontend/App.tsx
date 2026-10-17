/**
 * App flow: load the paired credential, run first-run onboarding when needed, then open
 * the whiteboard workspace on an active session. The same components power the Expo Go
 * iPad app and the same-client web build; DOM APIs exist only inside `.web` adapters.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, SafeAreaView, StyleSheet, Text, View } from 'react-native';

import { ApiClient, ApiClientError } from './src/api/client';
import type { Appearance, Personality, Session, TutorConfiguration } from './src/api/contracts';
import { getApiBaseUrl } from './src/config/apiBaseUrl';
import {
  clearCredentials,
  loadCredentials,
  saveCredentials,
  type StoredCredentials,
} from './src/storage/credentials';

import { OnboardingScreen } from './src/screens/OnboardingScreen';
import { WorkspaceScreen } from './src/screens/WorkspaceScreen';

type BootState =
  | { kind: 'loading' }
  | { kind: 'unavailable'; message: string }
  | {
      kind: 'onboarding';
      credentials: StoredCredentials | null;
    }
  | {
      kind: 'workspace';
      credentials: StoredCredentials;
      persona: TutorConfiguration;
      session: Session;
    };

export default function App() {
  const baseUrl = useMemo(() => getApiBaseUrl(), []);
  const [boot, setBoot] = useState<BootState>({ kind: 'loading' });
  const [submitting, setSubmitting] = useState(false);
  const [onboardingError, setOnboardingError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;

    async function openSession(
      client: ApiClient,
      credentials: StoredCredentials,
      persona: TutorConfiguration,
    ): Promise<BootState> {
      const sessions = await client.listSessions();
      const resumable = sessions.find((session) => session.status === 'active');
      const session = resumable ?? (await client.startSession());
      return { kind: 'workspace', credentials, persona, session };
    }

    async function start() {
      setBoot({ kind: 'loading' });
      const stored = await loadCredentials();
      if (stored === null) {
        return { kind: 'onboarding', credentials: null } satisfies BootState;
      }
      const client = new ApiClient(baseUrl, stored.accessToken);
      try {
        const me = await client.me();
        if (me.tutor_configuration === null) {
          return { kind: 'onboarding', credentials: stored } satisfies BootState;
        }
        return await openSession(client, stored, me.tutor_configuration);
      } catch (error) {
        if (error instanceof ApiClientError && error.status === 401) {
          await clearCredentials();
          return { kind: 'onboarding', credentials: null } satisfies BootState;
        }
        return {
          kind: 'unavailable',
          message:
            'The tutor service is not reachable. Start it on this Mac and try again — your work is saved on the server.',
        } satisfies BootState;
      }
    }

    start()
      .then((next) => {
        if (active) setBoot(next);
      })
      .catch(() => {
        if (active) {
          setBoot({ kind: 'unavailable', message: 'The app could not start. Please try again.' });
        }
      });
    return () => {
      active = false;
    };
  }, [baseUrl, attempt]);

  const completeOnboarding = useCallback(
    async (choices: { displayName: string; appearance: Appearance; personality: Personality }) => {
      setSubmitting(true);
      setOnboardingError(null);
      try {
        let credentials: StoredCredentials | null =
          boot.kind === 'onboarding' ? boot.credentials : null;
        if (credentials === null) {
          const anonymous = new ApiClient(baseUrl);
          const pairing = await anonymous.bootstrapDemoLearner(choices.displayName);
          credentials = {
            accessToken: pairing.access_token,
            learnerId: pairing.learner.id,
            displayName: pairing.learner.display_name,
          };
          await saveCredentials(credentials);
        }
        const client = new ApiClient(baseUrl, credentials.accessToken);
        const persona = await client.putTutorConfiguration(
          choices.appearance,
          choices.personality,
        );
        const sessions = await client.listSessions();
        const resumable = sessions.find((session) => session.status === 'active');
        const session = resumable ?? (await client.startSession());
        setBoot({ kind: 'workspace', credentials, persona, session });
      } catch (error) {
        setOnboardingError(
          error instanceof Error
            ? error.message
            : 'Setup could not finish. Please try again.',
        );
      } finally {
        setSubmitting(false);
      }
    },
    [baseUrl, boot],
  );

  return (
    <SafeAreaView style={styles.safe}>
      {boot.kind === 'loading' ? (
        <View style={styles.centered}>
          <ActivityIndicator color="#1D4ED8" />
          <Text style={styles.muted}>Opening your board…</Text>
        </View>
      ) : null}

      {boot.kind === 'unavailable' ? (
        <View style={styles.centered}>
          <Text style={styles.title}>Rubberducky</Text>
          <Text style={styles.muted}>{boot.message}</Text>
          <Pressable
            testID="app-retry"
            accessibilityRole="button"
            accessibilityLabel="Try connecting again"
            onPress={() => setAttempt((n) => n + 1)}
            style={styles.retryButton}
          >
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : null}

      {boot.kind === 'onboarding' ? (
        <OnboardingScreen
          submitting={submitting}
          errorMessage={onboardingError}
          showNameField={boot.credentials === null}
          onComplete={(choices) => void completeOnboarding(choices)}
        />
      ) : null}

      {boot.kind === 'workspace' ? (
        <WorkspaceScreen
          client={new ApiClient(baseUrl, boot.credentials.accessToken)}
          sessionId={boot.session.id}
          persona={boot.persona}
          displayName={boot.credentials.displayName}
        />
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#FCFCFA' },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 14,
    padding: 24,
  },
  title: { fontSize: 30, fontWeight: '700', color: '#1F2937' },
  muted: { fontSize: 16, color: '#52606D', textAlign: 'center' },
  retryButton: {
    minHeight: 44,
    paddingHorizontal: 20,
    borderRadius: 10,
    backgroundColor: '#2F4858',
    alignItems: 'center',
    justifyContent: 'center',
  },
  retryText: { color: '#FFFFFF', fontSize: 16, fontWeight: '600' },
});
