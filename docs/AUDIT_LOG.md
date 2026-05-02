# Audit log format (Phase 5 / Task 5.1)

**Status:** design only. The logger module (`graphify/audit.py`) lands in
Task 5.2; call-site wiring lands in Task 5.3.

Upstream uses `print()` exclusively. graphify-hardened needs a structured
paper trail for security-relevant actions, with explicit semantics for
what happens when the log itself cannot be written.

## Location and on-disk format

- **Path:** `graphify-out/.audit.log`, resolved relative to the current
  working directory at the time the event is emitted. The directory is
  created if it does not exist.
- **Format:** one JSON object per line (JSONL / NDJSON). UTF-8 encoded,
  trailing `\n` after every record.
- **File mode:** `0o600` on Unix, set on first write. Best-effort on
  Windows (NTFS ACL semantics differ; see *Limitations* below).
- **Append safety:** Unix uses `fcntl.flock(fd, LOCK_EX)` around every
  write so concurrent processes interleave whole records, never bytes.
  Windows has no equivalent guarantee in the standard library; see
  *Limitations*.

## Record shape

Every record has exactly six top-level fields. No extras.

| field      | type   | required | notes |
| ---------- | ------ | -------- | ----- |
| `ts`       | string | yes      | ISO 8601 with timezone, e.g. `2026-05-01T18:42:11.143+00:00`. UTC preferred but caller's local-with-offset is accepted. |
| `action`   | string | yes      | One of the ten values in the action registry below. Unknown values are rejected at the API surface. |
| `target`   | string | yes      | The URL, repo URL, file path, or argv[0] being acted on. Always a string; complex targets are rendered to a short canonical form (e.g. `git clone` → the canonical `https://host/owner/repo` rebuild from `_parse_git_url`, not the raw user-supplied URL). |
| `result`   | string | yes      | One of `success`, `error`, `warning`. |
| `severity` | string | yes      | One of `info`, `security`. Determines failure semantics (see Task 5.2). |
| `details`  | object | yes      | Action-scoped dict; keys validated against the per-action allowlist. May be `{}` but is never omitted, so consumers can rely on the field being present. |

Records are emitted in the order calls are made; no sequence number
field. Ordering across processes is best-effort under the lock.

## Action registry

Exactly ten actions are defined. All ten are `severity: security` —
the plan currently mandates no `info` events. Adding a new action
**must** add an entry both here and in the in-code allowlist registry
(`graphify.audit._ACTION_ALLOWLIST`); the logger rejects any action
name absent from the registry. This is the mechanism the Task 5.1
acceptance criterion ("adding a new action requires updating the
allowlist") rests on.

| action                       | source                                   | allowed `details` keys                                          |
| ---------------------------- | ---------------------------------------- | --------------------------------------------------------------- |
| `fetch_url`                  | `graphify/security.py::safe_fetch`       | `status_code`, `bytes`, `content_type`, `redirect_chain`        |
| `clone_repo`                 | `graphify/__main__.py::_clone_repo`      | `host`, `owner`, `repo`, `dest`, `duration_s`                   |
| `install_skill`              | `graphify/__main__.py` install commands  | `platform`, `paths_modified`                                    |
| `install_hook`               | `graphify/hooks.py::_install_hook`       | `platform`, `paths_modified`                                    |
| `uninstall_skill`            | `graphify/__main__.py` uninstall cmds    | `platform`, `paths_modified`                                    |
| `uninstall_hook`             | `graphify/hooks.py::_uninstall_hook`     | `platform`, `paths_modified`                                    |
| `subprocess`                 | the three sites in `audit/subprocess-review.md` | `binary`, `argv_redacted`, `exit_code`, `duration_s`, `stdout_bytes`, `stderr_bytes` |
| `cache_integrity_failure`    | `graphify/cache.py::_read_with_integrity` (currently stubbed via `_log_integrity_failure`) | `cache_key`, `expected_sha`, `actual_sha` |
| `quarantine_flagged`         | `graphify/build.py` flagged-text path    | `node_id`, `matched_patterns`, `provenance`                     |
| `content_type_violation`     | `graphify/ingest.py` content-type checks | `url`, `expected`, `received`                                   |

`paths_modified` is a list of strings (filesystem paths). `argv_redacted`
is the full argv with any URL-shaped or path-shaped element replaced by
`<url>` / `<path>`; the binary itself is captured separately so the
redaction is unambiguous.

## Disallowed-key handling

Keys not in the allowlist for the given action are **dropped silently**
from the persisted record. The first time per process that any key is
dropped, the logger emits one stderr warning of the form

```
[graphify audit] dropping disallowed details key 'foo' for action 'fetch_url' (further occurrences silenced)
```

Subsequent drops are silent, by design — security-relevant log paths
must not be made noisy by a misbehaving caller.

## Secret denylist

After allowlist filtering and before serialization, every string value
in `details` (recursively, into nested objects and list elements) is
matched against the denylist below. Any match is replaced by the
literal string `[REDACTED]`, regardless of which key the value sits
under.

| pattern                         | regex                                  |
| ------------------------------- | -------------------------------------- |
| Bearer token                    | `Bearer\s+[A-Za-z0-9._-]+`             |
| OpenAI API key                  | `sk-[A-Za-z0-9]{20,}`                  |
| Anthropic API key               | `sk-ant-[A-Za-z0-9_-]+`                |
| GitHub PAT (classic / fine)     | `gh[ps]_[A-Za-z0-9]{36}`               |
| Generic key-shaped token        | `[A-Za-z0-9_-]{32,}` (with carve-out — see below) |

The generic pattern is the only one with false-positive risk. Two
known interactions:

1. **SHA-256 hex digests** (64 lowercase hex chars) match the regex
   verbatim. The legitimate consumers of long hex strings in this log
   are `cache_integrity_failure.expected_sha` and `actual_sha`. Both
   are exempt from the generic pattern (the keys are carved out by
   name in the implementation). The non-generic patterns above do not
   match SHA-256 hex, so the carve-out is sufficient. The cache stub
   already truncates to 16 chars, but the carve-out is the load-bearing
   guarantee.
2. **Long file paths** under `paths_modified` or `provenance` may
   exceed 32 chars but mix in `/`, `.`, and other characters outside
   the regex's character class — the regex matches a 32+ run of
   `[A-Za-z0-9_-]` only, so a path with separators is naturally
   immune. A path component that is itself 32+ chars of alnum (rare;
   e.g. a UUID-named directory) would be redacted; this is accepted as
   a false-positive cost of the broad pattern.

The carve-out list lives next to the pattern table in code so future
fields with legitimate token-shaped values can be added explicitly.

## Failure semantics (preview of Task 5.2)

The logger exposes two functions:

- `log_event(action, target, result, details=None)` — best-effort.
  Catches all write failures and surfaces them on stderr prefixed
  `[audit log unavailable: <reason>]`. Never raises. Reserved for
  routine operational events (no callers in the current plan).
- `log_security_event(action, target, result, details=None)` — fail-loud.
  On file-write failure, attempts a stderr fallback prefixed
  `[AUDIT FAILURE — security event not persisted]` carrying the full
  serialized event payload. If stderr also fails, raises `AuditLogError`.
  Callers must propagate, not swallow. All ten actions in the registry
  go through this function.

The fail-loud contract is the reason the registry is small and tightly
scoped: every additional action becomes a potential abort surface for
user-facing commands. New actions are added with intent.

## Out of scope

- **Tamper-evident logging.** No HMAC chain, no per-record signatures,
  no Merkle linking. A local attacker with write access to
  `graphify-out/.audit.log` can rewrite history. Defending against the
  local-write attacker is a different threat model than the one this
  fork addresses (untrusted *content* arriving via fetched URLs and
  cloned repos, not untrusted *operators*).
- **Remote shipping.** No syslog, no HTTPS POST, no journald. The log
  is a local artifact for the user who runs graphify on their own
  machine.
- **Rotation.** The file grows unbounded. Operators who care can
  rotate it externally (logrotate, manual archive). Self-rotation is
  deferred until a real-world report shows the file growing past a
  size that matters.
- **Structured query.** The file is JSONL; consumers use `jq`, `grep`,
  or read it programmatically. No CLI subcommand to query the log
  beyond what `graphify status` (Task 5.4) surfaces.

These omissions are deliberate. Each could be added later without
breaking the on-disk format defined above.

## Limitations

- **Windows file permissions.** `0o600` has no clean NTFS equivalent
  in the standard library. The implementation calls `os.chmod` for
  parity with Unix but does not attempt to manipulate ACLs. On a
  multi-user Windows machine, the log may be readable by other local
  users.
- **Windows append concurrency.** `fcntl.flock` is Unix-only. On
  Windows the implementation falls back to `os.O_APPEND` write
  semantics, which the OS guarantees are atomic for writes shorter
  than `PIPE_BUF` (typically 4096 bytes) — sufficient for any
  reasonable record but documented here so operators running graphify
  in CI on Windows are aware that interleaving across processes is
  possible for very large `details` payloads.
- **Clock skew.** `ts` reflects the host clock at emit time. There is
  no monotonic ordering guarantee across reboots or NTP corrections.
