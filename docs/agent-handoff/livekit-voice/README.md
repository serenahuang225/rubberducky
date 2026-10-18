# Voice integration

There are two distinct voice paths.

**Recorded hold-to-talk is implemented:** `backend/app/api/voice.py`, `backend/app/speech/`,
and frontend recording/playback controllers use xAI transcription, the existing thinking-
partner turn, and speech of the committed reply. It requires `EXTERNAL_INTEGRATIONS_ENABLED`,
`XAI_SPEECH_ENABLED`, and `XAI_API_KEY`. It is disabled on the hosted demo; its existence is
not evidence of verified microphone behavior on every browser or iPad.

**LiveKit/Deepgram/Photon calling is unfinished:** no working deployed calling flow or live
call was established in this session. It is separate from recorded audio and Photon messaging.
Do not call the current release a live voice-chat feature.

A future calling adapter must redeem its own one-time pairing code, resolve learner scope,
use the existing `execute_turn` and history, and independently revoke its voice credential.
Caller ID is not authentication. Preserve opt-out, consent, duration/timeouts, cost tracking,
cancellation, and cleanup boundaries. Review current SDK contracts before adding transport
code. Account keys alone do not enable calling or authorize a line purchase.
