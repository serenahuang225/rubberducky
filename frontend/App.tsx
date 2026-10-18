/**
 * App flow: load the paired credential, run first-run onboarding when needed, then open
 * the whiteboard workspace on an active session. The same components power the Expo Go
 * iPad app and the same-client web build; DOM APIs exist only inside `.web` adapters.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { ApiClient, ApiClientError } from "./src/api/client";
import type {
  Appearance,
  HandholdMode,
  Personality,
  Session,
  TutorConfiguration,
} from "./src/api/contracts";
import { getTheme, type BoardTheme } from "./src/board/palette";
import { getApiBaseUrl } from "./src/config/apiBaseUrl";
import { resolveMotion } from "./src/feedback/preferences";
import { useSystemReducedMotion } from "./src/feedback/useSystemReducedMotion";
import {
  clearCredentials,
  loadCredentials,
  saveCredentials,
  type StoredCredentials,
} from "./src/storage/credentials";

import { MemoryScreen } from "./src/screens/MemoryScreen";
import { OnboardingScreen } from "./src/screens/OnboardingScreen";
import { SettingsScreen } from "./src/screens/SettingsScreen";
import { WorkspaceScreen } from "./src/screens/WorkspaceScreen";
import type { ChangeSummary } from "./src/state/memoryEffects";
import { useLearnerSettings } from "./src/state/useLearnerSettings";
import { useStoredTheme } from "./src/state/useStoredTheme";
import { installWebTheme, useDocumentTheme } from "./src/theme/webTheme";

type BootState =
  | { kind: "loading" }
  | { kind: "unavailable"; message: string }
  | {
      kind: "onboarding";
      credentials: StoredCredentials | null;
    }
  | {
      kind: "workspace";
      credentials: StoredCredentials;
      persona: TutorConfiguration;
      session: Session;
    };

type Panel = "none" | "settings" | "memory";

/** Reads the learner's chosen board theme each time a panel opens. */
function ThemedPanel({
  children,
}: {
  children: (theme: ReturnType<typeof useStoredTheme>) => React.ReactNode;
}) {
  return <>{children(useStoredTheme())}</>;
}

export default function App() {
  const baseUrl = useMemo(() => getApiBaseUrl(), []);
  const [boot, setBoot] = useState<BootState>({ kind: "loading" });
  const [panel, setPanel] = useState<Panel>("none");
  const [memoryReturn, setMemoryReturn] = useState<Panel>("none");
  const [removalNotice, setRemovalNotice] = useState<ChangeSummary | null>(
    null,
  );
  const accessToken =
    boot.kind === "workspace" ? boot.credentials.accessToken : null;
  // One client per URL and credential: a new instance on every render would reset anything
  // keyed on client identity and discard commands the board is running.
  const workspaceClient = useMemo(
    () => (accessToken === null ? null : new ApiClient(baseUrl, accessToken)),
    [baseUrl, accessToken],
  );
  const settings = useLearnerSettings(workspaceClient);
  const storedTheme = useStoredTheme();
  const [liveTheme, setLiveTheme] = useState<BoardTheme | null>(null);
  const [handhold, setHandhold] = useState<HandholdMode>("balanced");
  // The safe-area bands use the same color as the writing surface. Onboarding stays
  // on the warm canvas; the workspace follows the learner's board, including chalkboard.
  const shellTheme =
    boot.kind === "workspace" ? (liveTheme ?? storedTheme) : getTheme("paper");
  const systemReducedMotion = useSystemReducedMotion();
  const motion = resolveMotion(
    settings.accessibility.animation,
    systemReducedMotion,
  );
  useEffect(() => {
    installWebTheme();
  }, []);
  useDocumentTheme(shellTheme, motion);
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
      const resumable = sessions.find((session) => session.status === "active");
      const session = resumable ?? (await client.startSession());
      return { kind: "workspace", credentials, persona, session };
    }

    async function start() {
      setBoot({ kind: "loading" });
      const stored = await loadCredentials();
      if (stored === null) {
        return { kind: "onboarding", credentials: null } satisfies BootState;
      }
      const client = new ApiClient(baseUrl, stored.accessToken);
      try {
        const me = await client.me();
        if (me.tutor_configuration === null) {
          return {
            kind: "onboarding",
            credentials: stored,
          } satisfies BootState;
        }
        return await openSession(client, stored, me.tutor_configuration);
      } catch (error) {
        if (error instanceof ApiClientError && error.status === 401) {
          await clearCredentials();
          return { kind: "onboarding", credentials: null } satisfies BootState;
        }
        return {
          kind: "unavailable",
          message:
            "The tutor service is not reachable. Start it on this Mac and try again — your work is saved on the server.",
        } satisfies BootState;
      }
    }

    start()
      .then((next) => {
        if (active) setBoot(next);
      })
      .catch(() => {
        if (active) {
          setBoot({
            kind: "unavailable",
            message: "The app could not start. Please try again.",
          });
        }
      });
    return () => {
      active = false;
    };
  }, [baseUrl, attempt]);

  const completeOnboarding = useCallback(
    async (choices: {
      displayName: string;
      appearance: Appearance;
      personality: Personality;
    }) => {
      setSubmitting(true);
      setOnboardingError(null);
      try {
        let credentials: StoredCredentials | null =
          boot.kind === "onboarding" ? boot.credentials : null;
        if (credentials === null) {
          const anonymous = new ApiClient(baseUrl);
          const pairing = await anonymous.bootstrapDemoLearner(
            choices.displayName,
          );
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
        const resumable = sessions.find(
          (session) => session.status === "active",
        );
        const session = resumable ?? (await client.startSession());
        setRemovalNotice(null);
        setBoot({ kind: "workspace", credentials, persona, session });
      } catch (error) {
        setOnboardingError(
          error instanceof Error
            ? error.message
            : "Setup could not finish. Please try again.",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [baseUrl, boot],
  );

  const openMemoryFrom = useCallback((from: Panel) => {
    setMemoryReturn(from);
    setPanel("memory");
  }, []);

  const handleSessionRemoved = useCallback(
    (_sessionId: string, wasCurrent: boolean) => {
      if (wasCurrent) {
        setPanel("none");
        setAttempt((n) => n + 1);
      }
    },
    [],
  );

  const handleProfileDeleted = useCallback((summary: ChangeSummary) => {
    void clearCredentials().finally(() => {
      setPanel("none");
      setRemovalNotice(summary);
      setBoot({ kind: "onboarding", credentials: null });
    });
  }, []);

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: shellTheme.board }]}>
      {boot.kind === "loading" ? (
        <View style={styles.centered}>
          <ActivityIndicator color="#1D4ED8" />
          <Text style={styles.muted}>Opening your board…</Text>
        </View>
      ) : null}

      {boot.kind === "unavailable" ? (
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

      {boot.kind === "onboarding" && removalNotice !== null ? (
        <View
          testID="removal-notice"
          accessibilityLiveRegion="polite"
          style={styles.notice}
        >
          <Text style={styles.noticeTitle}>{removalNotice.title}</Text>
          {removalNotice.lines.map((line) => (
            <Text key={line} style={styles.noticeText}>
              {line}
            </Text>
          ))}
          {removalNotice.notice !== null ? (
            <Text style={styles.noticeText}>{removalNotice.notice}</Text>
          ) : null}
        </View>
      ) : null}

      {boot.kind === "onboarding" ? (
        <OnboardingScreen
          submitting={submitting}
          errorMessage={onboardingError}
          showNameField={boot.credentials === null}
          onComplete={(choices) => void completeOnboarding(choices)}
        />
      ) : null}

      {boot.kind === "workspace" && workspaceClient !== null ? (
        <>
          {/* Hidden, never unmounted, while a panel is open so running commands survive. */}
          <View style={[styles.fill, panel !== "none" && styles.hidden]}>
            <WorkspaceScreen
              client={workspaceClient}
              sessionId={boot.session.id}
              persona={settings.persona ?? boot.persona}
              displayName={boot.credentials.displayName}
              accessibility={settings.accessibility}
              boardHidden={panel !== "none"}
              onOpenSettings={() => setPanel("settings")}
              onOpenMemory={() => openMemoryFrom("none")}
              onThemeChange={setLiveTheme}
              handhold={handhold}
              onSessionEnded={() => {
                setPanel("none");
                setBoot((current) =>
                  current.kind === "workspace"
                    ? { kind: "onboarding", credentials: current.credentials }
                    : current,
                );
              }}
            />
          </View>
          {panel === "settings" ? (
            <ThemedPanel>
              {(theme) => (
                <SettingsScreen
                  settings={settings}
                  theme={theme}
                  motion={motion}
                  onClose={() => setPanel("none")}
                  onOpenMemory={() => openMemoryFrom("settings")}
                  handhold={handhold}
                  onChangeHandhold={setHandhold}
                />
              )}
            </ThemedPanel>
          ) : null}
          {panel === "memory" ? (
            <ThemedPanel>
              {(theme) => (
                <MemoryScreen
                  client={workspaceClient}
                  currentSessionId={boot.session.id}
                  theme={theme}
                  onClose={() => setPanel(memoryReturn)}
                  onSessionRemoved={handleSessionRemoved}
                  onProfileDeleted={handleProfileDeleted}
                />
              )}
            </ThemedPanel>
          ) : null}
        </>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  fill: { flex: 1 },
  hidden: { display: "none" },
  notice: {
    margin: 12,
    padding: 14,
    borderRadius: 12,
    backgroundColor: "#FFFFFF",
    borderWidth: 1,
    borderColor: "#D9DDE1",
    gap: 4,
  },
  noticeTitle: { fontSize: 17, fontWeight: "700", color: "#1F2937" },
  noticeText: { fontSize: 14, lineHeight: 20, color: "#374151" },
  centered: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 14,
    padding: 24,
  },
  title: { fontSize: 30, fontWeight: "700", color: "#1F2937" },
  muted: { fontSize: 16, color: "#52606D", textAlign: "center" },
  retryButton: {
    minHeight: 44,
    paddingHorizontal: 20,
    borderRadius: 10,
    backgroundColor: "#2F4858",
    alignItems: "center",
    justifyContent: "center",
  },
  retryText: { color: "#FFFFFF", fontSize: 16, fontWeight: "600" },
});
