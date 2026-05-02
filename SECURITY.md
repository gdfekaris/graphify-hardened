# Security Policy

This document describes the security model for `graphify-hardened`. The upstream project at [`safishamsi/graphify`](https://github.com/safishamsi/graphify) has its own SECURITY.md; this fork's policy is narrower in scope (hardening seams the fork explicitly addressed) and stricter in some defaults (lower fetch caps, mandatory Content-Type checks, audit logging).

## Supported versions

| Version                          | Supported |
|----------------------------------|-----------|
| `v0.1.x-hardened` (current fork) | Yes       |
| Older fork tags                  | No        |
| Upstream `safishamsi/graphify`   | See upstream's `SECURITY.md` |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities in this fork.**

Use **GitHub's private vulnerability reporting** on this repository: <kbd>Security</kbd> tab → "Report a vulnerability". That channel is auditable, gives you a receipt, and is the only contact path this project commits to. There is intentionally no email address listed — this is a single-maintainer open-source project and a published email would not be triaged on any reliable schedule.

Please include:

- Description of the vulnerability.
- Steps to reproduce, or a proof-of-concept input file or URL.
- Potential impact (what an attacker can read, write, or run).
- Suggested fix, if any.

### Maintainer commitment (be realistic)

This fork is maintained by **one person**, in their own time, alongside a family and a day job. There is **no formal SLA**, and there is no on-call rotation. What you can expect:

- I will read every report submitted through GitHub's private vulnerability reporting and reply to acknowledge it. I will try to do that promptly, but "promptly" is best-effort, not measured in hours.
- For confirmed vulnerabilities I will work on a patch. Critical issues (RCE, credential exfiltration, ability to silently tamper with another user's graph) will be prioritised over non-critical ones.
- I will not commit to a fixed disclosure timeline. If a fix is going to take a while, I will say so.
- I will not enforce a coordinated-disclosure embargo. You are free to publish at any time; I would prefer a heads-up before you do, but it is not a condition of triage.

### What this means for you, the user

This fork exists for users who want **more security than upstream provides by default**. It is not a managed security service. If you are deploying graphify on infrastructure where a vulnerability would have meaningful impact, **you should perform your own security audit of the code** before relying on it. The hardening work in `FORK.md` and the threat-surface table below are an honest description of what was reviewed and how, not a substitute for your own review.

If you are reporting a vulnerability in upstream `safishamsi/graphify` that is not specific to this fork's hardening surface, please report it upstream as well — fixes that originate upstream are pulled in here via the cherry-pick process documented in [`FORK.md`](FORK.md).

## Security model

graphify is a **local development tool**. It runs as a Claude Code (or other assistant) skill and optionally as a local MCP stdio server. The graph-analysis pass is fully local; the only outbound network calls happen during explicit `ingest` / `add` / `clone` invocations and during LLM-extraction of docs / papers / images via your assistant's model API.

The fork's hardening focuses on five surfaces upstream addresses partially or not at all:

1. **Indirect prompt injection** through LLM-extracted node labels and rationale text that get re-injected into the assistant's context every turn.
2. **Supply-chain risk** from unpinned dependencies and a third-party `vis-network` CDN script in generated HTML output.
3. **External-input sites** (URL fetch, git clone, PDF / Office document parsing).
4. **Cache integrity** for `graphify-out/cache/` entries.
5. **Audit trail** for security-relevant operations.

Every surface below is mapped to specific Tasks in `IMPLEMENTATION_PLAN.md` (locally referenced; the plan is intentionally not committed).

### Threat surface

| Vector | Mitigation |
|--------|-----------|
| **Indirect prompt injection via LLM-extracted node text** (Phase 3) | `graphify/injection.py::flag_suspicious` matches 12 named heuristic pattern families (imperative-ignore, role-injection markup, exfiltration instructions, jailbreak phrases, persona overrides). Triggers in `build.build_from_json` redact matched free-text fields to `[FLAGGED — see graphify-out/.flagged.json]`, tag the node `flagged: True`, and append the original to `.flagged.json` with provenance. The "untrusted-data framing" block is embedded in every rules file installed by `graphify *install` — the assistant is told to treat report and wiki text as **data**, not instructions. `--untrusted-corpus` mode skips LLM extraction entirely and emits metadata-only nodes (path + size + SHA256 + file_type) for non-code files. |
| **SSRF via URL fetch** (upstream + Phase 4.1, 4.2, 4.3) | `security.validate_url` allows only `http` / `https` schemes, blocks private / loopback / link-local IPs, blocks cloud metadata endpoints, and patches `socket.getaddrinfo` for the request duration to defeat DNS rebinding. Redirect targets are re-validated before each hop. `GRAPHIFY_FETCH_ALLOWLIST` adds a hostname allowlist after the existing checks. Per-URL-type Content-Type validation enforces declared content (`GRAPHIFY_CONTENT_TYPE_STRICT=0` downgrades to warning). All fetch paths including tweet oEmbed go through `safe_fetch`. |
| **Oversized downloads** (upstream + Phase 4.2) | `safe_fetch` streams responses and aborts at 50 MB. `safe_fetch_text` aborts at the `GRAPHIFY_MAX_TEXT_BYTES` cap (default **2 MB**, hard ceiling 50 MB). Lower than upstream's 10 MB default. |
| **Non-2xx HTTP responses** (upstream) | `safe_fetch` raises `HTTPError` on non-2xx — error pages are not silently treated as content. |
| **Path traversal in MCP server** (upstream) | `security.validate_graph_path` resolves paths and requires them to be inside `graphify-out/`. Also requires `graphify-out/` to exist. |
| **XSS / HTML injection in graph HTML output** (upstream + Phase 2) | `vis-network@10.0.2` is vendored at `graphify/static/vis-network.min.js` (no third-party CDN at render time), with a `</script` substring guard on the bundle and zero `eval` / `new Function` in its source. Generated HTML carries a CSP `<meta>` block (`default-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; object-src 'none'; base-uri 'none'`; `'unsafe-eval'` intentionally omitted). `_safe_href` normalises any future hyperlink emission (rejects `javascript:` / `data:` / `vbscript:` / unknown schemes, including `\t`-prefixed and `\x00`-prefixed smuggling). `sanitize_label` strips control characters, caps at 256 chars, and HTML-escapes node labels, edge `relation` / `confidence`, and hyperedge `label` before pyvis embeds them. |
| **Prompt injection via node labels in MCP responses** (upstream + Phase 3.5) | `sanitize_label` is applied to MCP text output. The `_dispatch_tool` layer prepends an untrusted-data prefix to every text-bearing handler; numeric-only handlers (`graph_stats`) are exempt. |
| **YAML frontmatter injection** (upstream) | `_yaml_str` escapes backslashes, double quotes, and newlines before embedding user-controlled strings (webpage titles, query questions) in YAML frontmatter. |
| **Encoding crashes on source files** (upstream) | All tree-sitter byte slices decoded with `errors="replace"` — non-UTF-8 source files degrade gracefully. |
| **Symlink traversal during corpus walk** (upstream) | `os.walk(..., followlinks=False)` is explicit throughout `detect.py`. |
| **Corrupted `graph.json`** (upstream) | `_load_graph` in `serve.py` wraps `json.JSONDecodeError` and prints a recovery message instead of crashing. |
| **Subprocess argument injection** (Phase 4.4, 4.5) | `_parse_git_url` uses `urlsplit` (not `urlparse`, which strips `;params` from HTTP/HTTPS paths) and validates owner/repo against `^[a-zA-Z0-9._-]+$` plus an explicit dot-only check. `--` separator before any positional argv on `git clone` and `git pull --branch`. `shell=False` everywhere, list-form argv at every site. Optional `GRAPHIFY_CLONE_ALLOWED_HOSTS` / `GRAPHIFY_CLONE_ALLOWED_OWNERS` env gates (AND-combined). Timeouts on every subprocess invocation: 5 s for the local `git config core.hooksPath` call, 300 s for network ops (clone / pull). Full subprocess inventory is in `audit/subprocess-review.md` — three sites total, all hardened. |
| **Cache deserialization** (Phase 4.7, 4.8) | Codebase-wide grep for `pickle / cPickle / dill / marshal / shelve / joblib / cloudpickle` returns zero hits — JSON-only on both the namespaced and legacy-flat cache layouts (`audit/deserialization-review.md`). Per-entry SHA256 sidecar (`<hash>.json.sha256`) written via atomic `tmp + rename`; reads through `_read_with_integrity`. Missing sidecar = silent miss; hash mismatch = audit event + miss. AST regression test refuses any `import pickle` in `cache.py`. **Known limitation**: a fully-consistent dual rewrite (entry + sidecar both updated to match) is accepted by design. Sidecar signing would defend against that and is out of scope. |
| **Hostile PDF parsing** (Phase 4.9) | File-size pre-check before pypdf parses (`GRAPHIFY_PDF_MAX_BYTES`, default 100 MB). On Unix, `RLIMIT_AS` lowered to `GRAPHIFY_PDF_MEMORY_CAP_BYTES` (default 2 GB) for the duration of pypdf parsing and restored on exit. Windows is file-size-check only (RLIMIT_AS is Unix-only). |
| **Hostile Office documents (zip bomb / oversized)** (Phase 4.9) | `_office_zip_is_safe` reads only the `.docx` / `.xlsx` zip central directory (no decompression) before any python-docx / openpyxl call. Refuses non-zip files, archives over `GRAPHIFY_OFFICE_MAX_UNCOMPRESSED_BYTES` (default 200 MB), and archives with more than 10 000 entries. defusedxml intentionally not retrofitted: zero direct XML usage in graphify, and `defuse_stdlib()` is a no-op for the lxml-based parsers we depend on (`audit/office-pdf-hardening.md`). |
| **API-key leakage via SDK exceptions** (Phase 4.10) | `_call_claude` and `_call_openai_compat` capture Anthropic / OpenAI exceptions, scrub the API-key value out of the message text (8-char floor; falls back to `RuntimeError` for uncloneable exception classes), and re-raise without leaking the original via `__context__` or `__cause__`. The "No API key for backend" `ValueError` references the env-var **name**, not value (regression-tested). |
| **Audit-trail gap** (Phase 5) | `graphify/audit.py` provides `log_event` (best-effort) and `log_security_event` (fail-loud — file → stderr fallback → `AuditLogError` if both fail). Atomic append via `os.write` under `fcntl.flock(LOCK_EX)` on Unix; bare `O_APPEND` on Windows. Recursive secret scrubbing (Bearer, `sk-`, `sk-ant-`, `gh[ps]_`, generic 32+ char tokens) on every record. Wired into nine action families: `fetch_url`, `content_type_violation`, `quarantine_flagged`, `cache_integrity_failure`, `clone_repo`, `subprocess`, `install_hook` / `uninstall_hook`, `install_skill` / `uninstall_skill`. Format and per-action `details` allowlist documented in [`docs/AUDIT_LOG.md`](docs/AUDIT_LOG.md). |

### Corpus trust statement

Running graphify on third-party content gives that content's authors **persistent injection access to your assistant** via the always-on hook. The fork mitigates this with prompt-injection heuristics, content quarantine, and untrusted-data framing of re-emitted graph content (see "Indirect prompt injection" row above and the [Trust model section in README.md](README.md#trust-model)), **but no heuristic is complete**. If you do not trust the corpus, use `--untrusted-corpus` until you have read the contents and trust them.

### Audit log: known limitation

The audit log is **not tamper-evident**. An attacker with local write access to `graphify-out/.audit.log` (or to `GRAPHIFY_AUDIT_LOG_PATH` if set) can rewrite history — delete records, forge records, or reorder records — and there is no in-band signal that this happened. Tamper-evidence would require either:

- An HMAC chain (each record signed with a key derived from the previous record's MAC), or
- Remote shipping (records forwarded to a separate trust boundary as soon as they are written).

Neither fits a local-only tool with no daemon and no shared secret store. **Detecting log tampering is explicitly out of scope** for this fork. The audit log is a forensic aid for cooperating users, not a tamper-evident security primitive.

The fail-loud semantics of `log_security_event` *do* protect against a different threat: an attacker who can render the audit log unwritable (read-only filesystem, file replaced with a directory, etc.) cannot cause silent loss of new events. The function falls back to stderr; if stderr is also broken, it raises `AuditLogError` and aborts the operation that would have generated the event (e.g., `safe_fetch` returns `AuditLogError` rather than completing the fetch and silently failing to log).

### Subprocess sandboxing approach

Three subprocess sites total in the codebase (`audit/subprocess-review.md`):

1. `hooks._hooks_dir` calling `git config core.hooksPath` — local op, 5 s timeout.
2. `__main__._clone_repo` calling `git clone` — network op, 300 s timeout.
3. `__main__._clone_repo` calling `git pull --branch` — network op, 300 s timeout.

For all three:

- `shell=False` and list-form argv (verified by tripwire test in `tests/test_subprocess_safety.py`).
- `--` separator before any positional argument, so a flag-shaped URL or branch name cannot be re-interpreted as an option.
- Owner / repo names validated against `^[a-zA-Z0-9._-]+$` plus an explicit dot-only check (the regex alone would let `..` through).
- Optional `GRAPHIFY_CLONE_ALLOWED_HOSTS` / `GRAPHIFY_CLONE_ALLOWED_OWNERS` allowlists, AND-combined.
- Timeout handler: pull on timeout serves the existing stale clone with a warning; clone on timeout exits non-zero.
- Audit event emitted via `log_security_event` for every invocation (URL-shaped and path-shaped argv elements are replaced with `<url>` / `<path>` sentinels in the recorded `argv`).

The bounded-stdout reader is intentionally not implemented — the 300 s timeout is the practical bound, and adding a streaming reader in front of `subprocess.run` would complicate the timeout handling without measurable benefit in this codebase.

### Cache integrity model

Per-entry SHA256 sidecar at `<hash>.json.sha256`:

1. **Write path** (`save_cached`): atomic `tmp + rename` for the entry, then atomic `tmp + rename` for the sidecar. A crash between the two leaves an unmatched entry; the next read demotes it to a cache miss.
2. **Read path** (`load_cached`): missing sidecar = silent cache miss; hash mismatch = `cache_integrity_failure` audit event (with both the expected and actual SHA carved out of the secret-scrubber so the forensic record is intact) **plus** a stderr print, and the entry is treated as a miss.
3. **Clear path** (`clear_cache`): cleans up sidecars alongside entries.

**What this defends against**: corruption (disk error, partial write, truncated file), single-side tampering (rewriting either the entry or the sidecar without rewriting the other), and accidental cross-contamination between cache versions.

**What this does *not* defend against**: a fully-consistent dual rewrite (an attacker rewriting both the entry and the sidecar to match). Sidecar signing with a per-installation key would defend against that and is out of scope. A user who needs that property can mount `graphify-out/cache/` read-only after population.

## What graphify does NOT do

- Does not run a network listener (the MCP server communicates over stdio only).
- Does not execute code from source files (tree-sitter parses ASTs — no `eval` / `exec`).
- Does not use `shell=True` in any subprocess call.
- Does not store credentials or API keys (env-var reads only; the single credential read in `llm.py` is wrapped in the API-key scrubber from Phase 4.10).
- Does not deserialize untrusted bytes via `pickle` / `marshal` / `dill` / `shelve` / `joblib` / `cloudpickle` (Phase 4.7 audit).
- Does not maintain a live `upstream` git remote (Phase 0; upstream changes are pulled in via the cherry-pick process in `FORK.md`).

## Optional network calls

- `graphify add <url>`, `graphify ingest`, `graphify clone <git-url>` — explicitly initiated by the user, gated by `validate_url` / `_parse_git_url`.
- LLM-extraction (Anthropic / OpenAI / your platform's API): your platform's API endpoint, using your own API key. Skipped entirely when `--untrusted-corpus` is set.
- `audit.yml` (CI only): pulls `pip-audit==2.10.0` and `osv-scanner v2.3.5` (release binary, SHA256-verified) on a weekly cron + on PRs into `development` + manually.
- PDF / DOCX / XLSX extraction: reads local files only.
- Watch mode: local filesystem events only (`watchdog`).
