# Heuristic detection of prompt-injection content in extracted text.
#
# This is a DEFENSE IN DEPTH measure, not a complete defense. A sufficiently
# subtle injection will not match these patterns. The complete defense is:
#   1. Untrusted-data framing applied in Task 3.5 to the rules-files and
#      MCP responses that re-emit corpus content to assistants.
#   2. The user's vigilance — surface anything flagged here and continue
#      treating unflagged corpus content as untrusted by default.
#
# To extend: add a (name, pattern) tuple to _PATTERNS. Names show up in
# .flagged.json records so make them descriptive — they are the operator's
# only window into *why* a piece of content was quarantined.
from __future__ import annotations
import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Imperative addresses to an LLM. The trailing noun group is restricted
    # to LLM-instruction nouns so legitimate technical writing — e.g.
    # "ignore previous warnings about thread safety" — does not match.
    ("imperative_ignore", re.compile(
        r"\bignore\s+(all\s+)?(previous|prior|the)\s+(instructions|directives|context|prompts)\b",
        re.IGNORECASE,
    )),

    # Role-injection markup — common attempts to fake system-role framing.
    ("role_system_tag_open",  re.compile(r"<\s*system\s*>",  re.IGNORECASE)),
    ("role_system_tag_close", re.compile(r"</\s*system\s*>", re.IGNORECASE)),
    ("role_inst_marker",      re.compile(r"\[INST\]",        re.IGNORECASE)),
    ("role_system_assertion", re.compile(r"\bsystem\s*:\s*you\s+are\b", re.IGNORECASE)),

    # Tool / exfil instructions.
    ("exfil_send_to", re.compile(
        r"\b(exfiltrate|send|post|upload|email)\b.*\b(to|at)\b\s+[\w./:-]+",
        re.IGNORECASE,
    )),
    ("exfil_curl_http", re.compile(r"\bcurl\b.*\bhttp",       re.IGNORECASE)),
    ("exfil_ssh_cat",   re.compile(r"\bcat\s+~/\.ssh\b",      re.IGNORECASE)),
    # Note: the leading \b is omitted from \.env on purpose — \b before "."
    # only matches when the preceding char is a word character, so the
    # natural form " .env " in prose would silently miss. Keeping the
    # trailing \b still rejects ".envoy".
    ("exfil_dotenv_send", re.compile(r"\.env\b.*\bsend\b",    re.IGNORECASE)),

    # Common jailbreak phrases.
    ("jailbreak_dan", re.compile(
        r"\b(DAN|do anything now|developer mode|jailbreak)\b",
        re.IGNORECASE,
    )),

    # Persona override.
    ("persona_you_are_now", re.compile(r"\byou are now\s+\w+", re.IGNORECASE)),
    ("persona_act_as_if",   re.compile(r"\bact as if you\s+",  re.IGNORECASE)),
]


def flag_suspicious(text: str) -> list[str]:
    """Return the names of every _PATTERNS entry that matches ``text``.

    An empty list means the text appears clean by these heuristics — this
    does NOT guarantee it is safe; see the module docstring.
    """
    if not isinstance(text, str) or not text:
        return []
    return [name for name, pattern in _PATTERNS if pattern.search(text)]
