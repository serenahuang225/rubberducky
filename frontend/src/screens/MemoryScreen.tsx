/**
 * Private memory view. Everything the tutor keeps about the learner is listed by kind with
 * where it came from, how uncertain it is and why it matters. Estimates are derived, so they
 * can only change by correcting or deleting the evidence under them. Deletion always takes a
 * second explicit step, and every change is reported from the server's own receipt.
 */

import React, { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import type { ApiClient } from "../api/client";
import type { KnowledgeMap, MemoryItem, Session } from "../api/contracts";
import type { BoardTheme } from "../board/palette";
import { KnowledgeGraph } from "../components/KnowledgeGraph";
import { ScreenFrame } from "../components/ScreenFrame";
import type { ChangeSummary } from "../state/memoryEffects";
import {
  DEFAULT_ITEM_LIMIT,
  MAX_ITEM_LIMIT,
  useMemoryView,
} from "../state/useMemoryView";

export type MemoryScreenProps = {
  client: ApiClient;
  currentSessionId: string | null;
  theme: BoardTheme;
  onClose: () => void;
  onSessionRemoved: (sessionId: string, wasCurrent: boolean) => void;
  onProfileDeleted: (summary: ChangeSummary) => void;
  timeZone?: string;
  locale?: string;
};

const KIND_ORDER: { kind: MemoryItem["kind"]; heading: string }[] = [
  { kind: "note", heading: "Notes the tutor kept" },
  { kind: "evidence", heading: "Evidence from your work" },
  { kind: "hypothesis", heading: "Tentative beliefs" },
  { kind: "session_context", heading: "This session’s context" },
  { kind: "estimate", heading: "Estimates (uncalibrated)" },
];

const STATUS_LABELS: Record<string, string> = {
  inference: "Tutor’s inference",
  verified: "Verified by a check",
  self_report: "Your own words (self-report)",
  derived_estimate: "Derived estimate",
};

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status.replace(/_/g, " ");
}

function formatDateTime(
  iso: string,
  timeZone?: string,
  locale?: string,
): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "an unknown time";
  try {
    return new Intl.DateTimeFormat(locale, {
      timeZone,
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date);
  } catch {
    return date.toISOString();
  }
}

function formatDate(iso: string, timeZone?: string, locale?: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "an unknown date";
  try {
    return new Intl.DateTimeFormat(locale, {
      timeZone,
      dateStyle: "medium",
    }).format(date);
  } catch {
    return date.toISOString().slice(0, 10);
  }
}

type Palette = {
  text: { color: string };
  muted: { color: string };
  danger: { color: string };
};

type ItemCardProps = {
  item: MemoryItem;
  theme: BoardTheme;
  palette: Palette;
  working: boolean;
  /** Names and shows when it was recorded; part of the control names when titles repeat. */
  recorded: string;
  /** "2 of 3" when the same title appears more than once, otherwise null. */
  position: string | null;
  onCorrectEvidence: (item: MemoryItem, correct: boolean) => Promise<boolean>;
  onCorrectNote: (item: MemoryItem, content: string) => Promise<boolean>;
  onDelete: (item: MemoryItem) => Promise<boolean>;
};

function ItemCard({
  item,
  theme,
  palette,
  working,
  recorded,
  position,
  onCorrectEvidence,
  onCorrectNote,
  onDelete,
}: ItemCardProps) {
  const [confirming, setConfirming] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [draftError, setDraftError] = useState<string | null>(null);
  const canCorrect = item.actions.some((action) => action.action === "correct");
  const canDelete = item.actions.some((action) => action.action === "delete");
  const button = { backgroundColor: theme.controlBackground };
  const buttonText = { color: theme.controlText };
  const confidence = item.uncertainty.confidence;
  const name =
    position === null
      ? item.title
      : `${item.title} ${position}, recorded ${recorded}`;

  const saveNote = async () => {
    const content = draft.trim();
    if (content === "") {
      setDraftError("Write what should be remembered instead, or cancel.");
      return;
    }
    setDraftError(null);
    if (await onCorrectNote(item, content)) setEditing(false);
  };

  return (
    <View
      testID={`memory-item-${item.id}`}
      style={[
        styles.card,
        { backgroundColor: theme.surface, borderColor: theme.surfaceEdge },
      ]}
    >
      <Text accessibilityRole="header" style={[styles.itemTitle, palette.text]}>
        {item.title}
      </Text>
      <Text style={[styles.body, palette.text]}>{item.summary}</Text>
      <Text style={[styles.meta, palette.muted]}>Recorded {recorded}</Text>
      <Text style={[styles.meta, palette.muted]}>
        {statusLabel(item.epistemic_status)} · {item.uncertainty.qualitative}{" "}
        confidence
        {confidence !== null ? ` (${Math.round(confidence * 100)}%)` : ""}
        {item.state !== "current" ? ` · ${item.state.replace(/_/g, " ")}` : ""}
      </Text>
      <Text style={[styles.meta, palette.muted]}>
        Uncertainty: {item.uncertainty.explanation}
      </Text>
      <Text style={[styles.meta, palette.text]}>
        Why it matters: {item.why_it_matters}
      </Text>
      {item.correction !== null ? (
        <Text style={[styles.meta, palette.text]}>
          You corrected this. Before: “{item.correction.original}”
        </Text>
      ) : null}
      {item.sources.length > 0 ? (
        <View style={styles.sources}>
          <Text style={[styles.meta, palette.text]}>Where it came from</Text>
          {item.sources.map((source) => (
            <Text key={source.id} style={[styles.meta, palette.muted]}>
              • {source.label}
              {source.excerpt !== null && source.excerpt !== source.label
                ? ` — “${source.excerpt}”`
                : ""}
              {source.available ? "" : " (that source has since been removed)"}
            </Text>
          ))}
        </View>
      ) : null}
      {item.kind === "estimate" ? (
        <Text style={[styles.meta, palette.muted]}>
          This estimate is computed from evidence. To change it, correct or
          delete the evidence it came from.
        </Text>
      ) : null}

      {editing ? (
        <View style={styles.editor}>
          <TextInput
            accessibilityLabel="Your corrected wording"
            value={draft}
            onChangeText={setDraft}
            multiline
            style={[
              styles.input,
              {
                color: theme.labelText,
                borderColor: theme.controlEdge,
                backgroundColor: theme.boardGrain,
              },
            ]}
          />
          {draftError !== null ? (
            <Text style={[styles.meta, palette.danger]}>{draftError}</Text>
          ) : null}
          <View style={styles.actions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Save correction"
              disabled={working}
              onPress={() => void saveNote()}
              style={[styles.button, button, working && styles.dim]}
            >
              <Text style={[styles.buttonText, buttonText]}>
                Save correction
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cancel correction"
              onPress={() => {
                setEditing(false);
                setDraftError(null);
              }}
              style={[
                styles.button,
                styles.outline,
                { borderColor: theme.controlEdge },
              ]}
            >
              <Text style={[styles.buttonText, palette.text]}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      ) : null}

      {confirming ? (
        <View style={styles.actions}>
          <Text style={[styles.meta, palette.danger]}>
            Delete this for good?
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Yes, delete: ${name}`}
            disabled={working}
            onPress={() => {
              void onDelete(item).then((done) => {
                if (!done) setConfirming(false);
              });
            }}
            style={[styles.button, button, working && styles.dim]}
          >
            <Text style={[styles.buttonText, buttonText]}>Yes, delete</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Keep it: ${name}`}
            onPress={() => setConfirming(false)}
            style={[
              styles.button,
              styles.outline,
              { borderColor: theme.controlEdge },
            ]}
          >
            <Text style={[styles.buttonText, palette.text]}>Keep it</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.actions}>
          {canCorrect && item.kind === "evidence" ? (
            <>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`This was right: ${name}`}
                disabled={working}
                onPress={() => void onCorrectEvidence(item, true)}
                style={[styles.button, button, working && styles.dim]}
              >
                <Text style={[styles.buttonText, buttonText]}>
                  This was right
                </Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`This was wrong: ${name}`}
                disabled={working}
                onPress={() => void onCorrectEvidence(item, false)}
                style={[styles.button, button, working && styles.dim]}
              >
                <Text style={[styles.buttonText, buttonText]}>
                  This was wrong
                </Text>
              </Pressable>
            </>
          ) : null}
          {canCorrect && item.kind === "note" && !editing ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`Correct wording: ${name}`}
              onPress={() => setEditing(true)}
              style={[styles.button, button]}
            >
              <Text style={[styles.buttonText, buttonText]}>
                Correct wording
              </Text>
            </Pressable>
          ) : null}
          {canDelete ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`Delete: ${name}`}
              disabled={working}
              onPress={() => setConfirming(true)}
              style={[
                styles.button,
                styles.outline,
                { borderColor: theme.controlEdge },
              ]}
            >
              <Text style={[styles.buttonText, palette.text]}>Delete</Text>
            </Pressable>
          ) : null}
        </View>
      )}
    </View>
  );
}

type SessionRowProps = {
  session: Session;
  isCurrent: boolean;
  theme: BoardTheme;
  palette: Palette;
  working: boolean;
  timeZone?: string;
  locale?: string;
  onRemove: (sessionId: string) => Promise<boolean>;
};

function SessionRow({
  session,
  isCurrent,
  theme,
  palette,
  working,
  timeZone,
  locale,
  onRemove,
}: SessionRowProps) {
  const [confirming, setConfirming] = useState(false);
  const label = `session from ${formatDate(session.started_at, timeZone, locale)}${isCurrent ? " (current)" : ""}`;
  return (
    <View style={[styles.row, { borderColor: theme.surfaceEdge }]}>
      <Text style={[styles.body, palette.text, styles.rowText]}>
        {label.charAt(0).toUpperCase() + label.slice(1)} · {session.status}
      </Text>
      {confirming ? (
        <View style={styles.actions}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Yes, remove ${label}`}
            disabled={working}
            onPress={() => {
              void onRemove(session.id).then(() => setConfirming(false));
            }}
            style={[
              styles.button,
              { backgroundColor: theme.controlBackground },
              working && styles.dim,
            ]}
          >
            <Text style={[styles.buttonText, { color: theme.controlText }]}>
              Yes, remove
            </Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Keep ${label}`}
            onPress={() => setConfirming(false)}
            style={[
              styles.button,
              styles.outline,
              { borderColor: theme.controlEdge },
            ]}
          >
            <Text style={[styles.buttonText, palette.text]}>Keep</Text>
          </Pressable>
        </View>
      ) : (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Remove ${label}`}
          disabled={working}
          onPress={() => setConfirming(true)}
          style={[
            styles.button,
            styles.outline,
            { borderColor: theme.controlEdge },
          ]}
        >
          <Text style={[styles.buttonText, palette.text]}>Remove</Text>
        </Pressable>
      )}
    </View>
  );
}

export function MemoryScreen({
  client,
  currentSessionId,
  theme,
  onClose,
  onSessionRemoved,
  onProfileDeleted,
  timeZone,
  locale,
}: MemoryScreenProps) {
  const view = useMemoryView(client);
  const [confirmProfile, setConfirmProfile] = useState(false);
  const [knowledge, setKnowledge] = useState<KnowledgeMap | null>(null);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);
  const loadKnowledge = useCallback(() => {
    setKnowledgeError(null);
    void client
      .knowledgeMap()
      .then(setKnowledge)
      .catch((error: unknown) => {
        setKnowledgeError(
          error instanceof Error
            ? error.message
            : "The concept graph could not be loaded.",
        );
      });
  }, [client]);
  useEffect(() => {
    loadKnowledge();
  }, [loadKnowledge]);
  const palette: Palette = {
    text: { color: theme.labelText },
    muted: { color: theme.labelMuted },
    danger: { color: theme.danger },
  };
  const items = view.inspection?.items ?? [];
  const titleCounts = new Map<string, number>();
  for (const item of items)
    titleCounts.set(item.title, (titleCounts.get(item.title) ?? 0) + 1);
  const seen = new Map<string, number>();
  const positions = new Map<string, string | null>();
  for (const item of items) {
    const total = titleCounts.get(item.title) ?? 1;
    const index = (seen.get(item.title) ?? 0) + 1;
    seen.set(item.title, index);
    positions.set(item.id, total > 1 ? `${index} of ${total}` : null);
  }

  const removeSession = async (sessionId: string): Promise<boolean> => {
    const done = await view.deleteSession(sessionId);
    if (done) onSessionRemoved(sessionId, sessionId === currentSessionId);
    return done;
  };

  const removeProfile = async () => {
    const summary = await view.deleteProfile();
    if (summary !== null) onProfileDeleted(summary);
    else setConfirmProfile(false);
  };

  return (
    <ScreenFrame
      theme={theme}
      testID="memory-screen"
      title="Private memory"
      closeLabel="Back to board"
      onClose={onClose}
    >
      {view.inspection !== null ? (
        <Text style={[styles.body, palette.text]}>
          {view.inspection.notice}
        </Text>
      ) : view.phase === "loading" ? (
        <Text style={[styles.body, palette.muted]}>
          Loading what your tutor remembers…
        </Text>
      ) : null}

      {view.error !== null ? (
        <Text
          testID="memory-error"
          accessibilityLiveRegion="polite"
          style={[styles.body, palette.danger]}
        >
          {view.error}
        </Text>
      ) : null}

      {view.lastChange !== null ? (
        <View
          testID="memory-change"
          accessibilityLiveRegion="polite"
          style={[
            styles.card,
            { backgroundColor: theme.surface, borderColor: theme.surfaceEdge },
          ]}
        >
          <Text
            accessibilityRole="header"
            style={[styles.itemTitle, palette.text]}
          >
            {view.lastChange.title}
          </Text>
          {view.lastChange.lines.map((line) => (
            <Text key={line} style={[styles.body, palette.text]}>
              {line}
            </Text>
          ))}
          {view.lastChange.notice !== null ? (
            <Text style={[styles.meta, palette.muted]}>
              {view.lastChange.notice}
            </Text>
          ) : null}
        </View>
      ) : null}

      {knowledge !== null ? (
        <KnowledgeGraph map={knowledge} theme={theme} />
      ) : knowledgeError !== null ? (
        <Text style={[styles.body, palette.danger]}>{knowledgeError}</Text>
      ) : (
        <Text style={[styles.body, palette.muted]}>
          Loading the concept graph…
        </Text>
      )}

      <View style={styles.actions}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Refresh memory"
          disabled={view.working}
          onPress={() => {
            void view.reload();
            loadKnowledge();
          }}
          style={[
            styles.button,
            styles.outline,
            { borderColor: theme.controlEdge },
          ]}
        >
          <Text style={[styles.buttonText, palette.text]}>Refresh</Text>
        </Pressable>
      </View>

      {view.inspection !== null ? (
        <View testID="memory-items" style={styles.group}>
          {KIND_ORDER.map(({ kind, heading }) => {
            const ofKind = items.filter((item) => item.kind === kind);
            if (ofKind.length === 0) return null;
            return (
              <View key={kind} style={styles.group}>
                <Text
                  accessibilityRole="header"
                  style={[styles.sectionTitle, palette.text]}
                >
                  {heading}
                </Text>
                {ofKind.map((item) => (
                  <ItemCard
                    key={item.id}
                    item={item}
                    theme={theme}
                    palette={palette}
                    working={view.working}
                    recorded={formatDateTime(item.at, timeZone, locale)}
                    position={positions.get(item.id) ?? null}
                    onCorrectEvidence={view.correctEvidence}
                    onCorrectNote={view.correctNote}
                    onDelete={view.deleteItem}
                  />
                ))}
              </View>
            );
          })}
          {items.length === 0 ? (
            <Text style={[styles.body, palette.text]}>
              Your tutor has not kept anything about you yet.
            </Text>
          ) : null}
          <Text testID="memory-bound" style={[styles.meta, palette.muted]}>
            Showing up to {view.limit} of each kind. Each kind has its own
            limit, so more can exist than the limit alone suggests.
            {view.canShowMore
              ? ""
              : ` ${MAX_ITEM_LIMIT} is the most that can be shown per kind.`}
          </Text>
          {view.canShowMore ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Show more of each kind"
              onPress={view.showMore}
              style={[
                styles.button,
                styles.outline,
                { borderColor: theme.controlEdge },
              ]}
            >
              <Text style={[styles.buttonText, palette.text]}>
                Show up to {MAX_ITEM_LIMIT} of each kind (now{" "}
                {DEFAULT_ITEM_LIMIT})
              </Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      <View style={styles.group}>
        <Text
          accessibilityRole="header"
          style={[styles.sectionTitle, palette.text]}
        >
          Sessions
        </Text>
        {view.sessions.length === 0 ? (
          <Text style={[styles.body, palette.muted]}>No sessions to show.</Text>
        ) : (
          view.sessions.map((session) => (
            <SessionRow
              key={session.id}
              session={session}
              isCurrent={session.id === currentSessionId}
              theme={theme}
              palette={palette}
              working={view.working}
              timeZone={timeZone}
              locale={locale}
              onRemove={removeSession}
            />
          ))
        )}
      </View>

      <View style={styles.group}>
        <Text
          accessibilityRole="header"
          style={[styles.sectionTitle, palette.text]}
        >
          Delete everything
        </Text>
        {confirmProfile ? (
          <>
            <Text
              testID="profile-delete-warning"
              style={[styles.body, palette.danger]}
            >
              This removes your profile, sessions, memory and sign-ins from the
              active local store on this tutor. It is not secure disk, backup or
              vendor erasure. You will be signed out and asked to start again.
            </Text>
            <View style={styles.actions}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Yes, delete my profile"
                disabled={view.working}
                onPress={() => void removeProfile()}
                style={[
                  styles.button,
                  { backgroundColor: theme.controlBackground },
                  view.working && styles.dim,
                ]}
              >
                <Text style={[styles.buttonText, { color: theme.controlText }]}>
                  Yes, delete my profile
                </Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Keep my profile"
                onPress={() => setConfirmProfile(false)}
                style={[
                  styles.button,
                  styles.outline,
                  { borderColor: theme.controlEdge },
                ]}
              >
                <Text style={[styles.buttonText, palette.text]}>
                  Keep my profile
                </Text>
              </Pressable>
            </View>
          </>
        ) : (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Delete my profile"
            onPress={() => setConfirmProfile(true)}
            style={[
              styles.button,
              styles.outline,
              styles.start,
              { borderColor: theme.controlEdge },
            ]}
          >
            <Text style={[styles.buttonText, palette.text]}>
              Delete my profile
            </Text>
          </Pressable>
        )}
      </View>
    </ScreenFrame>
  );
}

const styles = StyleSheet.create({
  group: { gap: 10 },
  sectionTitle: { fontSize: 20, fontWeight: "700" },
  card: { padding: 14, gap: 6, borderRadius: 28, borderWidth: 2 },
  itemTitle: { fontSize: 17, fontWeight: "700" },
  body: { fontSize: 15, lineHeight: 21 },
  meta: { fontSize: 14, lineHeight: 20 },
  sources: { gap: 2 },
  actions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
    alignItems: "center",
  },
  editor: { gap: 8 },
  input: {
    minHeight: 70,
    borderWidth: 2,
    borderRadius: 999,
    padding: 10,
    fontSize: 16,
  },
  button: {
    minHeight: 44,
    paddingHorizontal: 16,
    borderRadius: 28,
    alignItems: "center",
    justifyContent: "center",
  },
  outline: { borderWidth: 1, backgroundColor: "transparent" },
  start: { alignSelf: "flex-start" },
  dim: { opacity: 0.5 },
  buttonText: { fontSize: 15, fontWeight: "700" },
  row: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    borderBottomWidth: 1,
  },
  rowText: { flex: 1, minWidth: 180 },
});
