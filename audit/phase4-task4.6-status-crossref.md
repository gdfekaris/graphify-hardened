# Task 4.6 (yt-dlp sandboxing) — status cross-reference

**Status:** not applicable in this fork.

## Why

Task 4.6 is gated on the `[video]` optional extra being kept (see
`IMPLEMENTATION_PLAN.md`: "Sandbox yt-dlp invocations (only if [video]
kept)"). In this fork, `[video]` was dropped during Phase 0 / Phase 1 (commit
`3f07e76 deps: drop [video] extra`). The decision and rationale are recorded
in `FORK.md` under "Rationale for dropping `[video]`":

> The `[video]` extra turns graphify from "parses local code and docs" into
> "downloads arbitrary media from arbitrary URLs and feeds it to two complex
> C/Python parsers." That is a categorical jump in attack surface that is
> not justified by the user's intended use, which does not include
> video/audio ingestion.

Per that rationale, the threat-model preference is **eliminate the class**
rather than sandbox it. Dropping `[video]` removes:

- yt-dlp's argument-injection / output-template / per-site-extractor surface,
- faster-whisper's model-download trust extension to `huggingface.co`,
- the transitive dependency on system `ffmpeg` and its codec/container
  parsers.

The recipe in Task 4.6 (URL after `--`, forced `--no-exec` /
`--no-call-home` / `--no-update`, hard timeout, bounded output dir) addresses
known classes of yt-dlp issues but cannot pre-empt future bugs in extractor
code. Eliminating the dependency does.

## What remains in the codebase

Per the fork policy ("The corresponding code paths ... are retained — the
extras list controls only which optional dependencies are installable",
`FORK.md` Phase 0 entry), the following code paths still exist:

- `graphify/transcribe.py` — `_get_yt_dlp()` and `_get_whisper()` lazy
  imports, `download_audio()` and `transcribe()` functions.
- `graphify/ingest.py` — the `youtube` branch in `_detect_url_type` and the
  `if url_type == "youtube":` arm in `ingest()` that defers to
  `transcribe.download_audio`.

Without the `[video]` dependencies installed, these paths raise `ImportError`
on first call. The error message has been updated (this commit) to explain
that the extra is intentionally absent in this fork and point readers at
`FORK.md` and this document, instead of suggesting the (now non-existent)
`pip install 'graphifyy[video]'` invocation.

## What this means for the audit

- No yt-dlp invocation exists for an attacker to influence in any default or
  hardened install of this fork. `Task 4.5` (subprocess audit) confirmed
  that the only subprocess sites are the three `git` invocations.
- The Phase 4 acceptance criterion "subprocess and cache audits from Phase 4
  are clean" (per `FORK.md` "Public release trigger") is satisfied for the
  yt-dlp class by the drop, not by sandboxing.
- If a future maintainer re-introduces `[video]`, the Task 4.6 sandboxing
  recipe in `IMPLEMENTATION_PLAN.md` lines 498–517 should be implemented
  before re-enabling the YouTube ingest path.
