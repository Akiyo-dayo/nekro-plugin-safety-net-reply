import ast
import json
import re
import tokenize
from io import StringIO
from typing import List, Optional


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCED_CODE_RE = re.compile(r"```(?:python)?\s*.*?```", re.DOTALL | re.IGNORECASE)
_PYTHON_INTENT_RE = re.compile(
    r"(^|\n)\s*(from|import|def|class|async\s+def|await|for|while|if|elif|else|try|except|with|return|raise|"
    r"send_\w+|update_\w+|set_\w+|get_\w+|[A-Za-z_][A-Za-z0-9_]*\s*=)",
    re.MULTILINE,
)
_CJK_TEXT_RE = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")
_MESSAGE_INTENT_RE = re.compile(r"\b(msg\s*=|send_msg_text\s*\(|send_plain_text_response\s*\()", re.MULTILINE)
DEFAULT_MAX_MESSAGE_CHARS = 1200


def sanitize_plain_text(raw_content: str, code_content: str) -> str:
    """Return the text that should be sent when a model produced prose instead of code."""
    source = raw_content or code_content
    source = _THINK_BLOCK_RE.sub("", source)
    return source.strip()


def is_plain_text_fallback_candidate(code_content: str, raw_content: str = "") -> bool:
    """Detect prose that NA would otherwise execute as Python."""
    code = (code_content or "").strip()
    raw = (raw_content or code_content or "").strip()
    if not code or not raw:
        return False
    if _FENCED_CODE_RE.search(raw):
        return False

    try:
        ast.parse(code)
    except SyntaxError:
        pass
    else:
        return False

    if _PYTHON_INTENT_RE.search(code):
        return False

    return bool(_CJK_TEXT_RE.search(code))


def extract_message_text_from_malformed_code(code_content: str) -> Optional[str]:
    """Recover message text from malformed NA-style message-sending code."""
    code = (code_content or "").strip()
    if not code or not _MESSAGE_INTENT_RE.search(code):
        return None

    try:
        ast.parse(code)
    except SyntaxError:
        pass
    else:
        return None

    fragments: List[str] = []
    try:
        tokens = tokenize.generate_tokens(StringIO(code).readline)
        for token in tokens:
            if token.type != tokenize.STRING:
                continue
            try:
                value = ast.literal_eval(token.string)
            except (SyntaxError, ValueError):
                continue
            if isinstance(value, str):
                fragments.append(value)
    except tokenize.TokenError:
        pass

    message_text = "".join(fragments).strip()
    if not message_text or not _CJK_TEXT_RE.search(message_text):
        return None
    return message_text


def _split_for_string_literals(message_text: str) -> List[str]:
    raw_parts = message_text.splitlines(keepends=True)
    parts: List[str] = []
    for part in raw_parts:
        if parts and part in {"\n", "\r\n"}:
            parts[-1] += part
        else:
            parts.append(part)
    if not parts:
        return [""]
    return parts


def build_fallback_code(message_text: str) -> str:
    """Build NA-style sandbox code that sends prose through a predeclared method."""
    literal_lines = [f"    {json.dumps(part, ensure_ascii=False)}" for part in _split_for_string_literals(message_text)]
    return "msg = (\n" + "\n".join(literal_lines) + "\n)\n\nsend_plain_text_response(_ck, msg)"


def split_message_text(message_text: str, max_chars: int = DEFAULT_MAX_MESSAGE_CHARS) -> List[str]:
    """Split long outgoing text while preserving every character."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(message_text) <= max_chars:
        return [message_text]

    chunks: List[str] = []
    remaining = message_text
    while len(remaining) > max_chars:
        split_at = remaining.rfind("\n\n", 0, max_chars + 1)
        if split_at <= 0:
            split_at = remaining.rfind("\n", 0, max_chars + 1)
        if split_at <= 0:
            split_at = max_chars
        else:
            split_at += 2 if remaining.startswith("\n\n", split_at) else 1
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        chunks.append(remaining)
    return chunks
