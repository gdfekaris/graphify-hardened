# API-key handling audit (Phase 4 / Task 4.10)

**Scope:** every site in `graphify/` that reads or handles a credential
environment variable, plus every site where a credential value could
plausibly reach a log file, an output file under `graphify-out/`, or an
exception message that propagates to the caller. Reviewed at commit
`ba80743` after the office/PDF hardening landed.

## Inventory

```
$ grep -rn 'os\.environ\|os\.getenv' graphify/
```

Twelve hits in `*.py` files (skill-*.md template strings excluded; they
are templates rendered into user repositories and only reference the
benign `GRAPHIFY_WHISPER_PROMPT` and `GRAPHIFY_WHISPER_MODEL` non-secret
overrides).

For each hit, classify whether the env var **value** is read or only its
**presence** is tested:

| File:line | Variable | Mode | Notes |
|---|---|---|---|
| `security.py:33` | `GRAPHIFY_MAX_TEXT_BYTES` | value | Numeric cap, not a credential. |
| `security.py:55` | `GRAPHIFY_FETCH_ALLOWLIST` | value | Hostname list, not a credential. |
| `transcribe.py:18` | `GRAPHIFY_WHISPER_MODEL` | value | Model name, not a credential. |
| `transcribe.py:108` | `GRAPHIFY_WHISPER_PROMPT` | value | Prompt text, not a credential. |
| `ingest.py:45` | `GRAPHIFY_CONTENT_TYPE_STRICT` | value | `"0"`/`"1"` toggle. |
| `detect.py:112` | `GRAPHIFY_PDF_MAX_BYTES` | value | Byte cap. |
| `detect.py:123` | `GRAPHIFY_PDF_MEMORY_CAP_BYTES` | value | Byte cap. |
| `detect.py:217` | `GRAPHIFY_OFFICE_MAX_UNCOMPRESSED_BYTES` | value | Byte cap. |
| `hooks.py:68` | `GRAPHIFY_CHANGED` | value | Comma-separated path list, not a credential. |
| `__main__.py:195-196` | `CLAUDE_CONFIG_DIR` | value | Filesystem path, not a credential. |
| `__main__.py:1049` | `GRAPHIFY_CLONE_ALLOWED_HOSTS` | value | Hostname list. |
| `__main__.py:1057` | `GRAPHIFY_CLONE_ALLOWED_OWNERS` | value | Owner list. |
| `__main__.py:1635` | `MOONSHOT_API_KEY` | **presence** | `if not os.environ.get(...)` — value discarded. |
| `__main__.py:1635` | `GRAPHIFY_NO_TIPS` | presence | Toggle. |
| `llm.py:153` | `cfg["env_key"]` (= `ANTHROPIC_API_KEY` or `MOONSHOT_API_KEY`) | **value** | Read into local `key`, then passed to SDK constructor as `api_key=`. **Sole credential-value read.** |
| `llm.py:214` | `MOONSHOT_API_KEY` | presence | Truthy check; value discarded. |
| `llm.py:216` | `ANTHROPIC_API_KEY` | presence | Truthy check; value discarded. |

**Net result: there is exactly one site that reads a credential value into
a Python variable, `graphify/llm.py:153`. Everywhere else it is a
presence-test.**

## Where the credential value flows

From `llm.py:153`, the local `key` flows to:

1. `_call_claude(api_key=key, ...)` → `anthropic.Anthropic(api_key=api_key)`.
2. `_call_openai_compat(api_key=key, ...)` → `OpenAI(api_key=api_key, ...)`.

Both SDK constructors are well-behaved in the success path: the credential
goes into the `Authorization` header of the outgoing HTTP request and is
not echoed back. The realistic leak vector is the **failure path**: a
malformed-key or rate-limit error from the SDK can produce an exception
whose message text includes the offending key value. Without intervention,
that exception propagates straight to the caller (and onward into any
future audit log).

## Mitigation

`graphify/llm.py` now contains:

1. **`_redact_key(exc, key)`** — same-class scrubber that replaces the
   literal key value with `[REDACTED]` in the exception message, falling
   back to `RuntimeError` if the original class refuses single-argument
   construction. An 8-character floor stops pathological replacements when
   the caller passes a placeholder shorter than any plausible real key.

2. **Capture-then-raise wrappers** around the SDK call blocks in both
   `_call_claude` and `_call_openai_compat`:
   ```python
   scrubbed: BaseException | None = None
   try:
       resp = client.messages.create(...)
   except Exception as exc:
       if api_key and api_key in str(exc):
           scrubbed = _redact_key(exc, api_key)
       else:
           raise
   if scrubbed is not None:
       raise scrubbed
   ```
   Raising **outside** the `except` block is necessary: `raise X from None`
   inside the `except` only suppresses cause-display — Python's exception
   machinery still attaches the in-flight exception via `__context__` at
   the bytecode level, and an audit-logger or debugger that walks the
   chain would see the original unredacted message. Capturing the
   scrubbed exception, exiting the except block, and raising afterwards
   leaves `__context__` as `None`. The `tests/test_llm_api_key_scrub.py`
   regression tests walk the full chain (`__cause__` and `__context__`)
   to verify this.

3. **The `No API key for backend …` `ValueError`** at `llm.py:155-158`
   references the env-var **name** (`ANTHROPIC_API_KEY`) — it is raised
   precisely *because* no value was found, so it cannot leak one. A
   regression test (`test_no_api_key_set_error_does_not_contain_a_key`)
   guards against accidental f-string changes.

## Confirmations against the spec checklist

- **Never logged.** Zero `print(...)`, `logging.*`, or `sys.stderr.write`
  calls in `graphify/` reference `api_key`, `key`, or any of the four
  `*_API_KEY` env vars by value. Confirmed by
  `grep -rn 'api_key\|API_KEY' graphify/*.py`.
- **Never written to any `graphify-out/` file.** No file-write call site
  takes `key` / `api_key` as part of its serialized payload.
- **Never in error messages or exception strings.** The two SDK call
  paths are now scrubbed; the `No API key` ValueError refers to the env
  var name, not the value.

## Out of scope

- **The shell history of the user that exported the variable.** Process
  environment is the user's trust boundary; we cannot redact it from
  outside.
- **The OS process listing.** API keys live in environment, not argv —
  not an issue here, but recorded for completeness.
- **Future audit log (Phase 5).** When `graphify/audit_log.py` lands, its
  fields must not include any of the env-var values listed in the
  inventory above as "value". The cache-integrity stub
  (`_log_integrity_failure` in `cache.py`) and the existing test surface
  do not cite credentials, so the migration is a straight rebind. A
  follow-up review at the start of Phase 5 should re-run this grep over
  the audit-log writer's call sites.

## Status

Single credential-value read site identified, wrapped, and tested.
Acceptance criteria for Task 4.10 met. 624-test suite green at commit
preceding this audit.
