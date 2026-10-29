"""Secret shapes, shared by `wikiloop lint` and `wikiloop report-session`.

The lint refuses a line with a plausible secret; the redaction replaces anything that may be
one, so it accepts more false hits. A wiki adds its own token shapes in `lint.secret_patterns`.
Tests build their synthetic secrets at runtime: no literal in the core matches.
"""
from __future__ import annotations

import re

REDACTED = "<redacted>"

# The whole match is the secret.
TOKENS = [
    ("GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"),
    ("Slack token", r"\bxox[abeoprs]-[A-Za-z0-9-]{10,}"),
    ("Slack webhook", r"https://hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9/_-]{20,}"),
    ("AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}"),
    ("Google OAuth token", r"\bya29\.[0-9A-Za-z_-]{20,}"),
    ("Google refresh token", r"\b1//0[0-9A-Za-z_-]{30,}"),
    ("Grafana token", r"\bgl(?:sa|c)_[A-Za-z0-9_=+/-]{20,}"),
    ("GitLab token", r"\bglpat-[A-Za-z0-9_-]{20,}"),
    ("model API key", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}"),
    ("JWT", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]+)?"),
]
TOKENS = [(kind, re.compile(pattern)) for kind, pattern in TOKENS]

# Only the value group is the secret; it must also pass `plausible`.
_KEY = r"[A-Za-z0-9_-]*(?:password|passwd|passphrase|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|credentials?)(?:[_-]?id)?"
_VALUE = r"([^\s\"'\\,;(){}\[\]<>]+)"
ASSIGNMENTS = [
    # `password: x`, `TOKEN=x`, and JSON at any escaping depth: `"token": "x"`, `\"token\": \"x\"`.
    ("secret field", re.compile(rf"(?i)(?<![A-Za-z0-9_-]){_KEY}(?:\\*[\"'])?\s*[:=]\s*(?:\\*[\"'])?{_VALUE}")),
    ("secret flag", re.compile(rf"(?i)--[a-z-]*(?:password|passwd|token|secret|api-key|apikey)(?:=|\s+)[\"']?{_VALUE}")),
    ("bearer token", re.compile(rf"(?i)\bbearer\s+{_VALUE}")),
    ("basic auth", re.compile(rf"(?i)\bauthorization:\s*basic\s+{_VALUE}")),
    ("URL credentials", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@\"'\\]+:([^\s/@\"'\\]+)@")),
    ("curl credentials", re.compile(r"(?:\s-u|--user)\s+[\"']?[^\s:\"']+:([^\s\"']+)")),
]

_KEY_HEAD = r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----"
_KEY_TAIL = r"-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----"
PRIVATE_KEY_HEAD = re.compile(_KEY_HEAD)
# On one line: a transcript escapes the key's newlines, at any depth.
PRIVATE_KEY_BLOCK = re.compile(rf"{_KEY_HEAD}.*?{_KEY_TAIL}")
# A key cut short, as in a truncated tool result: the header and whatever base64 follows.
PRIVATE_KEY_OPEN = re.compile(rf"{_KEY_HEAD}(?:\\+[nr]|[A-Za-z0-9+/=:, \t-])*")
PRIVATE_KEY_BODY = re.compile(r"^[A-Za-z0-9+/=:, \t-]*$")
PRIVATE_KEY_END = re.compile(rf"^.*?{_KEY_TAIL}")

PLACEHOLDER = re.compile(r"^(?:[<$%{(\[*~/.]|x{4,}$|\*+$|(?:redacted|null|none|true|false|changeme)$)", re.I)


def wiki_tokens(cfg: dict) -> list:
    """The wiki's own token shapes from `lint.secret_patterns`."""
    return [("wiki token", re.compile(p)) for p in cfg["lint"].get("secret_patterns", [])]


def plausible(value: str, strict: bool) -> bool:
    """Whether an assigned value can be a secret. `strict` is the lint's bar: a secret
    there blocks a merge, so it must look random, not like an identifier."""
    if PLACEHOLDER.match(value) or value.isdigit():
        return False
    if not strict:
        return len(value) >= 8

    has_letter = any(c.isalpha() for c in value)
    has_digit = any(c.isdigit() for c in value)
    return len(value) >= 12 and has_letter and has_digit


def find(line: str, extra: list = ()) -> list[str]:
    """Kinds of secret on one line, by the lint's bar."""
    kinds = []
    if PRIVATE_KEY_HEAD.search(line):
        kinds.append("private key")
    for kind, pat in [*TOKENS, *extra]:
        if pat.search(line):
            kinds.append(kind)
    for kind, pat in ASSIGNMENTS:
        if any(plausible(m.group(1), strict=True) for m in pat.finditer(line)):
            kinds.append(kind)
    return kinds


def _redact_values(line: str) -> tuple[str, int]:
    count = 0
    for _, pat in ASSIGNMENTS:
        def repl(m: re.Match) -> str:
            nonlocal count
            if not plausible(m.group(1), strict=False):
                return m.group(0)
            count += 1
            start, end = m.span(1)
            return m.group(0)[: start - m.start()] + REDACTED + m.group(0)[end - m.start():]

        line = pat.sub(repl, line)
    return line, count


def redact(lines, extra: list = ()):
    """Yield (line, count) per input line. A private key goes whole: the header, the body and
    the footer, whether its newlines are real or escaped. A raw key's body lines are dropped."""
    in_key = False
    for line in lines:
        count = 0
        if in_key:
            end = PRIVATE_KEY_END.match(line)
            if end:
                line, in_key = line[end.end():], False
            elif PRIVATE_KEY_BODY.match(line.rstrip("\n")):
                continue
            else:
                in_key = False

        line, n = PRIVATE_KEY_BLOCK.subn(REDACTED, line)
        count += n
        opened = PRIVATE_KEY_OPEN.search(line)
        if opened:
            in_key = opened.end() >= len(line.rstrip("\n"))
            line, n = PRIVATE_KEY_OPEN.subn(REDACTED, line)
            count += n

        for _, pat in [*TOKENS, *extra]:
            line, n = pat.subn(REDACTED, line)
            count += n
        line, n = _redact_values(line)
        yield line, count + n


def redact_text(text: str, extra: list = ()) -> tuple[str, int]:
    out = list(redact(text.splitlines(keepends=True), extra))
    return "".join(line for line, _ in out), sum(n for _, n in out)
