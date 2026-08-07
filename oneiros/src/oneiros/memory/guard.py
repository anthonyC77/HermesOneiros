"""Screening memory entries before they reach the system prompt.

A memory entry is injected into the system prompt at session start, which means
it carries operator authority. Anything that can write memory can therefore
write instructions — and by the time an entry is in the prompt, the model has no
way to tell it apart from the harness's own guidance.

The screening below is a filter, not a proof. It catches the shapes that
actually turn up: instruction override, conversation forgery, credential
exfiltration, and invisible characters. It does not catch a determined attacker
who knows what it looks for, which is why staged approval (:mod:`.gate`) exists
alongside it rather than instead of it.

**Precision matters more than recall here.** A rule that fires on a legitimate
note trains the operator to approve blindly, which costs more than the rule
buys. So every pattern is phrase-level: ``ignore``, ``system`` and
``~/.ssh/id_ed25519`` are all ordinary content in a technical note and none of
them trip anything on their own.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["Finding", "UnsafeContent", "scan", "assert_safe"]


@dataclass(frozen=True)
class Finding:
    rule: str
    detail: str


class UnsafeContent(Exception):
    """An entry was refused. Names every rule that fired."""

    def __init__(self, findings: list[Finding]) -> None:
        self.findings = findings
        summary = "; ".join(f"{f.rule}: {f.detail}" for f in findings)
        super().__init__(f"Refused — this content is not safe to put in a prompt. {summary}")


_FLAGS = re.IGNORECASE | re.MULTILINE

#: Instruction-override and role-confusion patterns. Each requires a full
#: phrase, never a bare keyword.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction-override",
        re.compile(
            r"\bignore\s+(?:all\s+|any\s+)?(?:the\s+)?"
            r"(?:previous|prior|preceding|above|earlier|foregoing)\s+"
            r"(?:instructions?|prompts?|rules?|directions?|guidance)",
            _FLAGS,
        ),
    ),
    (
        "instruction-override",
        re.compile(
            r"\bdisregard\s+(?:all\s+|any\s+)?(?:the\s+)?"
            r"(?:previous|prior|above|earlier|system)\s+"
            r"(?:instructions?|prompts?|rules?|messages?)",
            _FLAGS,
        ),
    ),
    (
        "instruction-override",
        re.compile(r"\bforget\s+(?:everything|all)\s+(?:you|above|before|prior)\b", _FLAGS),
    ),
    (
        "instruction-override",
        re.compile(r"\boverride\s+(?:your|the|all)\s+"
                   r"(?:instructions?|rules?|safety|guidelines?|system\s+prompt)", _FLAGS),
    ),
    (
        "instruction-override",
        re.compile(r"\bnew\s+(?:system\s+)?instructions?\s*:", _FLAGS),
    ),
    (
        "identity-rewrite",
        re.compile(r"\b(?:you\s+are\s+now|from\s+now\s+on,?\s+you\s+are)\s+(?:a|an|the)\b", _FLAGS),
    ),
    (
        "identity-rewrite",
        re.compile(r"\bpretend\s+(?:to\s+be|you\s+are)\b", _FLAGS),
    ),
    (
        "identity-rewrite",
        re.compile(r"\byour\s+(?:real|true|actual)\s+"
                   r"(?:instructions?|purpose|goal|objective)\s+(?:is|are)\b", _FLAGS),
    ),
    (
        "prompt-boundary-forgery",
        re.compile(r"</?\s*(?:system|system[_-]?prompt|assistant|human)\s*>", _FLAGS),
    ),
    (
        "prompt-boundary-forgery",
        re.compile(r"\[/?INST\]|<\|(?:im_start|im_end|endoftext)\|>", _FLAGS),
    ),
    (
        "prompt-boundary-forgery",
        re.compile(r"\bBEGIN\s+SYSTEM\s+PROMPT\b", _FLAGS),
    ),
    (
        "concealment",
        re.compile(r"\bdo\s+not\s+(?:tell|inform|mention\s+(?:this\s+)?to|reveal\s+this\s+to)\s+"
                   r"the\s+user\b", _FLAGS),
    ),
    (
        "concealment",
        re.compile(r"\b(?:do\s+(?:it|this|so)|proceed|act|run\s+it|execute)\s+"
                   r"without\s+(?:telling|informing|asking)\s+the\s+user\b", _FLAGS),
    ),
    (
        "exfiltration",
        re.compile(
            r"\b(?:curl|wget|nc|Invoke-WebRequest|iwr)\b[^\n]{0,200}"
            r"\$\{?[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS?)[A-Z0-9_]*\}?",
            _FLAGS,
        ),
    ),
    (
        "exfiltration",
        re.compile(
            r"\b(?:cat|type|Get-Content)\b[^\n|]{0,120}"
            r"(?:id_rsa|id_ed25519|\.env\b|credentials|\.aws/|\.npmrc)"
            r"[^\n]{0,120}\|\s*(?:curl|wget|nc|base64|openssl)",
            _FLAGS,
        ),
    ),
    (
        "exfiltration",
        re.compile(r"\b(?:printenv|env)\s*\|\s*(?:curl|wget|nc|base64)", _FLAGS),
    ),
    (
        "exfiltration",
        re.compile(
            r"\b(?:send|upload|post|exfiltrate|forward|email)\s+"
            r"(?:me\s+|us\s+)?(?:the\s+|your\s+|all\s+)?(?:api\s+)?"
            r"(?:keys?|tokens?|secrets?|credentials?|password)\s+to\s+"
            r"(?:https?://|[\w.-]+@[\w.-]+|me\b)",
            _FLAGS,
        ),
    ),
    (
        "persistence-backdoor",
        re.compile(r">>?\s*~?/?[\w./-]*\.ssh/authorized_keys", _FLAGS),
    ),
    (
        "persistence-backdoor",
        re.compile(r"\bcrontab\s+-\s*$|\becho\b[^\n]{0,120}\|\s*crontab\b", _FLAGS),
    ),
)

#: Role markers that, repeated, indicate a forged transcript rather than prose.
_ROLE_MARKER = re.compile(r"^\s*(System|Human|User|Assistant)\s*:", re.MULTILINE)

#: Format characters that render as nothing. Allowed: none — a memory entry has
#: no legitimate use for a zero-width joiner or a bidi override.
_INVISIBLE_RANGES = (
    (0x00AD, 0x00AD),    # soft hyphen
    (0x200B, 0x200F),    # zero-width space .. RTL mark
    (0x202A, 0x202E),    # bidi embedding / override
    (0x2060, 0x2064),    # word joiner, invisible operators
    (0x2066, 0x2069),    # bidi isolates
    (0xFEFF, 0xFEFF),    # BOM / zero-width no-break space
    (0xE0000, 0xE007F),  # tag characters — the classic hidden-prompt channel
)


def _invisible(text: str) -> list[str]:
    hits: list[str] = []
    for char in text:
        code = ord(char)
        if any(low <= code <= high for low, high in _INVISIBLE_RANGES):
            name = unicodedata.name(char, "unnamed")
            hits.append(f"U+{code:04X} {name}")
    return hits


def scan(text: str) -> list[Finding]:
    """Return every reason this content should not enter a prompt."""
    findings: list[Finding] = []

    for name, pattern in _RULES:
        match = pattern.search(text)
        if match:
            findings.append(Finding(name, f"matched {match.group(0)[:60]!r}"))

    # A single "Assistant:" is ordinary prose about a log format. Two or more
    # distinct role markers is a transcript someone is trying to graft on.
    roles = {m.group(1).lower() for m in _ROLE_MARKER.finditer(text)}
    if len(roles) >= 2:
        findings.append(
            Finding("prompt-boundary-forgery", f"forged turn markers: {sorted(roles)}")
        )

    invisible = _invisible(text)
    if invisible:
        findings.append(
            Finding("invisible-characters", ", ".join(sorted(set(invisible))[:4]))
        )

    return findings


def assert_safe(text: str) -> None:
    """Raise :class:`UnsafeContent` if the text must not enter a prompt."""
    findings = scan(text)
    if findings:
        raise UnsafeContent(findings)
