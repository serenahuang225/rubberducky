# Photon / LiveKit voice continuation

## Goal and current status

Build the optional **Python LiveKit Agents/API voice worker** using Claude and Deepgram
Nova-3/Aura-2 through LiveKit Inference, sharing authorized tutor/history with the app.
Photon supplies an entitled SIP line. Own **VAL-INTEGRATION-005**.
Read the [index](../README.md), [backend](../../../backend/README.md) and
[working-tree guide](../working-tree/README.md).

`photon-livekit-voice-continuation` is pending. No production voice worker, settings/CLI,
repository voice dependency lock or transport tests exist in the inspected snapshot.
Scratch imports/signatures proved toolchain feasibility only, not calling or implemented
authorization. This documentation request does not authorize implementation or execution.

## Already implemented / do not rebuild

- Shared Python scope/pairing/session/history/context/policy/coordinator, source permissions,
  revisions/idempotency and cancellation. Voice must use these services, not a separate
  unconstrained chat-memory database.
- In-app optional mic/camera/TTS controllers are a **different path**. Their simulated speech
  is not a telephone call, LiveKit transport, STT or acoustic barge-in.
- Readiness inspected compatible versions offline: livekit-agents1.8.8,
  livekit-plugins-anthropic1.8.8, livekit-api1.2.2, livekit1.1.20,
  protocol1.1.27, local-inference0.2.7 alongside core dependencies.
  Constructors were inspected with no stream/start/prewarm, no network attempts/audio or
  downloaded models. Package-bundled native VAD may initialize at SDK import; avoid claiming
  imports have literally no native initialization.
- SDK/API fixture and redaction patterns exist. Do not add a remote deployment or proof system.

## Relevant code and interfaces

| Existing path | Use |
| --- | --- |
| [pairing/scope](../../../backend/app/learner/pairing.py), [deps](../../../backend/app/api/deps.py) | Explicit learner authorization; caller ID is never enough |
| [coordinator](../../../backend/app/tutor/coordinator.py), [schemas](../../../backend/app/schemas/tutor.py) | Same bounded validated tutoring and evidence semantics |
| [context](../../../backend/app/inference/context.py), [graph](../../../backend/app/graph/context.py) | Own prior sources, bounded retrieval and missingness |
| [cancellation](../../../backend/app/tutor/cancellation.py), [interrupt](../../../backend/app/tutor/interrupt.py) | Epoch fencing; current turn can continue after cancellation |
| [config](../../../backend/app/config.py), [CLI](../../../backend/app/cli.py) | Future shared config/disabled status/dry-run registration; not currently implemented |
| [redaction](../../../backend/app/redaction.py), [provider fixtures](../../../backend/tests/provider_fixtures.py) | Sanitized failures/outbound-blocked tests |

Verified scratch signatures, not executable product code:

- `AgentSession(stt=..., vad=..., llm=..., tts=...)`, `start(agent, room=...)`, `aclose()`.
- `inference.STT(model="deepgram/nova-3", language="en")`;
  `inference.TTS(model="deepgram/aura-2", voice=<explicit configured voice>, language="en")`;
  `inference.VAD(model="silero")`.
- `livekit.plugins.anthropic.LLM(model=<explicit configured model>)`; construct only after
  activation/config gates, not at import/health. SDK's model default is not an approved
  model/account selection.
- `LiveKitAPI.sip.create_outbound_trunk(CreateSIPOutboundTrunkRequest)`,
  `.create_sip_participant(CreateSIPParticipantRequest)` and
  `.agent_dispatch.create_dispatch(CreateAgentDispatchRequest)`.
  Inspect actual protobuf fields/enums rather than invent keyword names.
- Framework call retries may default3 independently of Anthropic vendor retry settings.
  Duration/cost accounting must consider both, without promising a provider hard cap.

SIP selection: **`sip.spectrum.photon.codes`, TLS5061, registration OFF**,
Digest project ID/secret, From a **project-owned entitled iMessage calling line**, codecs
PCMU/PCMA. TLS signaling does not itself prove encrypted RTP. Real entitlement/rates are
unverified; a Business line may exceed the entire test allowance. Do not purchase it or
claim a universal per-minute rate/<= $5 line availability.

Selected configuration names from planning: `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
`LIVEKIT_API_SECRET`, `VOICE_ENABLED`, Stable `SPECTRUM_PROJECT_ID/SECRET`,
server-side Anthropic model/key. They are not implemented runtime settings yet.
Deepgram is through LiveKit Inference; do not require a separate Deepgram key/account.

## Remaining work (ordered checklist with concrete outcomes)

1. [ ] Obtain explicit offline implementation assignment. Confirm dependency availability/
   reproducible lock requirements; appropriate local tests/research/routine setup fit that
   assignment within agreed scope and standing resource/download restrictions.
   Agree with Photon owner on channel/session authorization and shared Python boundary.
2. [ ] Define disabled/configured-unverified/refused/failed status and a local dry-run path
   that cannot dial. No client/stream/prewarm/trunk/session is created at app import/health.
3. [ ] Implement preflight fail-closed gates: explicit activation; all required credentials;
   eligible project-owned line/entitlement; confirmed rates/account/free-plan policy;
   exact approved destination and consent; authorized learner link; duration and cost bound.
   Missing/unknown inputs block **before dialing or disclosing history**.
4. [ ] Connect an authorized synthetic voice channel to shared bounded tutor/history, validated
   turn/evidence semantics and cancellation. An incoming caller ID alone must retrieve no
   personal history. Limit context and keep cloud-transmission disclosures honest.
5. [ ] Wire actual LiveKit Agents/Inference/Anthropic and SIP API types behind injected
   transports. No live media, phone calls or provisioning to “check” the wire shapes.
6. [ ] Exercise start/stop, hangup/opt-out, timeout, cancellation, duration/cost exhaustion and
   cleanup with fake sessions/SDK boundaries and zero outbound. Suppress late speech/tools/
   memory and show a successful subsequent authorized current turn where applicable.
7. [ ] Add executable config/status/dry-run CLI and focused tests; document real command names
   and dependency installation only once implemented. Extend existing backend gate entrypoints,
   without making default API imports require optional live SDK initialization.
8. [ ] Document private outward worker connectivity and deferred live prerequisites. No FastAPI
   public ingress is required for a later approved outbound call; do not deploy one.
9. [ ] **Return control after the last independent integration** before dispatching paused media,
   absent external modeling or final physical work. Ask whether external commits have arrived;
   do not continue automatically.

## Acceptance criteria (existing VAL IDs and approved behavior; no new assurance/scope)

**VAL-INTEGRATION-005 remains pending.** Required intercepted fixture matrix:
missing credentials; absent/unknown line entitlement; missing rates; absent exact destination
approval; absent consent; caller-only unauthorized history; fully eligible synthetic dry-run;
hangup; opt-out; timeout; duration exhaustion; cost exhaustion; cancellation/cleanup.

Each missing gate prevents start. Eligible synthetic flow proves executable wiring/start/stop,
not delivery, live STT/TTS or account eligibility. Worker shares authorized state, default
disabled; no upgrade/line purchase/call. Enforce explicit **LiveKit free Build / $0 additional
paid spend / no upgrade** policy, while leaving actual account quotas and inference credits
unverified. No fixture may mark the account live-verified.

## Verification commands and evidence

Not run here. There is **no current voice CLI/test filename** to execute. Do not copy a
planned `voice dry-run` as an existing command. After implementation assignment, add and run
focused tests against installed real SDK types/transports with outbound blocked, then:

```sh
cd /Users/huangrh/workspace/rubberducky
backend/.venv/bin/python -m mypy --config-file backend/pyproject.toml backend/app
backend/.venv/bin/python -m ruff check backend
```

Use two numerical threads for applicable pytest, temporary migrated SQLite, no listeners.
Record actual CLI help/config/refusal/dry-run commands and exits, gate reasons before any
transport operation, synthetic resource start/stop counts, cancellation/opt-out results,
bounded source IDs and real-call/media count0.

Secondary local reference:
`/private/tmp/rubberducky-readiness/voice-smoke-results.json` records actual signatures,
protobuf fields and constructor-only probe results;
`requirements-voice.lock` in the same directory is readiness scratch, not a shipped repo
voice lock. Do not rerun readiness or install SDKs during this documentation task.

## Ownership, dependencies, parallelism and stop conditions

Separate voice modules/fixtures can progress alongside Photon after assignment, but serialize
shared settings, CLI, pairing/channel mapping, route inventory and locks. Preserve frontend
media/dirty UI; this is not an in-app media rewrite. Never alter the other agent's modeling
worktree. Use [working-tree coordination](../working-tree/README.md).

Stop if dependencies/SDK semantics are unavailable, any authorization/rate/account input is
unknown, shared file ownership conflicts, or a proposed test would actually connect. Report
missing input, not a fake plan tier/entitlement/rate or a live fallback.

## Not authorized / deferred

No real calls/messages, purchase/upgrade/top-up, remote trunk/room/worker deployment,
public ingress/tunnel, audio capture, transcription, secret access, environment dumps,
browser/services, expensive downloads, or commits for the docs task. Future <=$5 Photon/
Claude allowance is not current activation; LiveKit/Deepgram $0 extra remains binding.
No claim of native-device media acceptance, emotional diagnosis or learning gains.

## Copyable assignment prompt

> After confirming offline implementation is authorized, complete
> `photon-livekit-voice-continuation` using this README and the handoff/backend/working-tree
> guides. Reuse shared scoped Python tutoring; no caller-ID-only history. Implement actual
> LiveKit Agents/API, Claude and Deepgram via Inference plus Stable Photon SIP TLS5061/
> no registration, behind fail-closed credential/entitlement/rate/destination/consent/
> duration/cost/free-Build gates. Cover VAL-INTEGRATION-005 with intercepted transports,
> zero real calls/media and truthful configured-unverified status. No browser/services/
> deployment/purchases/secrets/downloads. Coordinate shared files. Return control after
> independent integration before any paused browser, external experiment or device task.

## Required return report

`Summary; files/commit IDs (or uncommitted); exact commands + exit/status; actual evidence/artifact paths; skipped/blocked checks and reason; remaining gaps; next owner`.
Include implemented CLI/scripts/locks, SDK versions and real-vs-fake boundaries, complete
gate matrix, zero real-call/media count, unknown account/line/rates, and mandatory return
checkpoint for the orchestrator/user.
