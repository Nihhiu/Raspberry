"""Token/byte budget for a conversation, adapted from Kumi (crates/kumi-agent/src/kernel/budget.rs).

Measures conversation as JSON bytes (~3 bytes per token) and fits it into a model's
window using layered, threshold-based clearing. Clearing only happens past the soft
threshold (clear_at) so providers' prompt caches keep working between requests.

Usage:
    from token_budget import ContextBudget, budget_for, fit

    history = [{"role": "user", "content": "..."}, ...]
    turn = [{"role": "user", "content": "..."}]
    budget = ContextBudget(clear_at=160*1024, limit=400*1024)
    new_history, new_turn = fit(history, turn, budget)
"""
import json
from dataclasses import dataclass
from typing import Any, List, Tuple

BYTES_PER_TOKEN = 3.0
DEFAULT_CLEAR_AT = 160 * 1024
DEFAULT_LIMIT = 400 * 1024

HEAD = 200          # bytes kept of a cleared tool result
SMALL = 1024        # results this small stay whole
ASK = 300           # max bytes of one producer line in the shortened list
ASKS = 3 * 1024     # total bytes for the list of producer asks
IMAGE_BYTES = 4 * 1024
SHORTENED = "[Kumi removed the earlier part of this conversation to save room.]\n\n"
ASKED = "[What the producer said in that part, oldest first:]\n"
CLEARED_NOTE = " … [cleared to save room; re-read if needed]"
OBSERVATION_MARKER = "\n\n<current_observation_untrusted>"
CLEARED_OBSERVATION = "\n[Kumi cleared this observation to save room.]\n</current_observation_untrusted>"
REPORT_STUB = 300


@dataclass
class ContextBudget:
    clear_at: float
    limit: float


def budget_for(window_tokens: float, fixed_bytes: float, answer_tokens: float) -> ContextBudget:
    """Budget for a model that reads `window_tokens` at once."""
    limit = min(DEFAULT_LIMIT, max(16 * 1024, (window_tokens - answer_tokens) * BYTES_PER_TOKEN - fixed_bytes))
    return ContextBudget(clear_at=limit * 0.4, limit=limit)


def min(a, b):
    return a if a < b else b


def max(a, b):
    return a if a > b else b


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def bytes_of(msg: Any) -> int:
    return _json_bytes(msg) + 1  # +1 for separator


def total_bytes(messages: List[Any]) -> int:
    if not messages:
        return 2
    return len(messages) + 1 + sum(bytes_of(m) for m in messages)


def opening(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    end = n
    while end > 0 and not _is_char_boundary(text, end):
        end -= 1
    return text[:end]


def _is_char_boundary(s: str, i: int) -> bool:
    if i == 0 or i == len(s):
        return True
    # A position is a char boundary if the byte is not a continuation byte.
    # Work in bytes to be safe.
    b = s.encode("utf-8")
    if i >= len(b):
        return True
    return (b[i] & 0xC0) != 0x80


def cut_text(value: str) -> str:
    if len(value) <= SMALL:
        return value
    if value.endswith(CLEARED_NOTE.strip()):
        return value
    return opening(value, HEAD) + CLEARED_NOTE


def _clear_tool_result_part(part: dict, cleared_note: str) -> Tuple[dict, bool]:
    """Clear a single tool-result part (dict with 'content' str). Returns (part, touched)."""
    touched = False
    out = dict(part)
    content = part.get("content")
    if isinstance(content, str):
        if content.endswith(cleared_note.strip()) or len(content) <= SMALL:
            return out, False
        out["content"] = opening(content, HEAD) + cleared_note
        touched = True
    elif isinstance(content, list):
        # content is list of {type: text, text: ...}
        new_items = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                t = item["text"]
                if t.endswith(cleared_note.strip()) or len(t) <= SMALL:
                    new_items.append(item)
                else:
                    new_items.append({**item, "text": opening(t, HEAD) + cleared_note})
                    touched = True
            else:
                new_items.append(item)
        if touched:
            out["content"] = new_items
    return out, touched


def clear_message(msg: dict, observations: bool, cleared_note: str) -> Tuple[dict, bool]:
    """Return (possibly cleared message, touched)."""
    if not isinstance(msg, dict):
        return msg, False
    role = msg.get("role")
    touched = False
    out = dict(msg)

    # Tool results: clear content of tool_result parts.
    content = msg.get("content")
    if role == "tool" and isinstance(content, list):
        new_content = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "tool_result":
                p, t = _clear_tool_result_part(part, cleared_note)
                touched = touched or t
                new_content.append(p)
            else:
                new_content.append(part)
        if touched:
            out["content"] = new_content

    # User observations: strip observation marker block.
    if role == "user" and observations and isinstance(content, str):
        idx = content.find(OBSERVATION_MARKER)
        if idx != -1 and not content[idx + len(OBSERVATION_MARKER):].startswith(CLEARED_OBSERVATION):
            # keep stubs
            stubs = _job_report_stubs(content[idx:])
            kept = content[:idx]
            if stubs:
                kept = kept + OBSERVATION_MARKER + CLEARED_OBSERVATION + stubs
            out["content"] = kept
            touched = True
    if role == "user" and observations and isinstance(content, list):
        new_items = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                t = part["text"]
                idx = t.find(OBSERVATION_MARKER)
                if idx != -1 and not t[idx + len(OBSERVATION_MARKER):].startswith(CLEARED_OBSERVATION):
                    stubs = _job_report_stubs(t[idx:])
                    kept = t[:idx]
                    if stubs:
                        kept = kept + OBSERVATION_MARKER + CLEARED_OBSERVATION + stubs
                    new_items.append({**part, "text": kept})
                    touched = True
                else:
                    new_items.append(part)
            else:
                new_items.append(part)
        if touched:
            out["content"] = new_items

    return out, touched


def _job_report_stubs(tail: str) -> str:
    # Minimal: return empty; full parsing is in Kumi. Keep interface.
    return ""


def clear_until(messages: List[Any], end: int, observations: bool, cleared_note: str) -> List[Any] | None:
    end = min(end, len(messages))
    if not any_would_clear(messages[:end], observations, cleared_note):
        return None
    out = []
    touched_any = False
    for i, m in enumerate(messages):
        if i >= end:
            out.append(m)
            continue
        cleared, touched = clear_message(m, observations, cleared_note)
        if touched:
            touched_any = True
        out.append(cleared)
    return out if touched_any else None


def any_would_clear(messages: List[Any], observations: bool, cleared_note: str) -> bool:
    for m in messages:
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        role = m.get("role")
        # tool result with text to cut
        if role == "tool" and isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    cc = part.get("content")
                    if isinstance(cc, str):
                        if not (cc.endswith(cleared_note.strip()) or len(cc) <= SMALL):
                            return True
                    elif isinstance(cc, list):
                        for it in cc:
                            if isinstance(it, dict) and it.get("type") == "text" and isinstance(it.get("text"), str):
                                t = it["text"]
                                if not (t.endswith(cleared_note.strip()) or len(t) <= SMALL):
                                    return True
        if role == "user" and observations:
            if isinstance(c, str):
                idx = c.find(OBSERVATION_MARKER)
                if idx != -1 and not c[idx + len(OBSERVATION_MARKER):].startswith(CLEARED_OBSERVATION):
                    return True
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                        t = part["text"]
                        idx = t.find(OBSERVATION_MARKER)
                        if idx != -1 and not t[idx + len(OBSERVATION_MARKER):].startswith(CLEARED_OBSERVATION):
                            return True
    return False


def has_marker(msg: Any) -> bool:
    if not isinstance(msg, dict) or msg.get("role") != "user":
        return False
    c = msg.get("content")
    texts = []
    if isinstance(c, str):
        texts.append(c)
    elif isinstance(c, list):
        for part in c:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(part.get("text", ""))
    for t in texts:
        idx = t.find(OBSERVATION_MARKER)
        if idx != -1 and not t[idx + len(OBSERVATION_MARKER):].startswith(CLEARED_OBSERVATION):
            return True
    return False


def previous_turn_index(messages: List[Any]) -> int:
    # rposition of has_marker, else last user index
    for i in range(len(messages) - 1, -1, -1):
        if has_marker(messages[i]):
            return i
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], dict) and messages[i].get("role") == "user":
            return i
    return 0


def drop_earliest(messages: List[Any], room: int) -> List[Any]:
    sizes = [bytes_of(m) + 1 for m in messages]
    total = sum(sizes) + 1
    start = 0
    while start < len(messages) and total > room:
        total -= sizes[start]
        start += 1
        while start < len(messages) and (not isinstance(messages[start], dict) or messages[start].get("role") != "user"):
            total -= sizes[start]
            start += 1
            if start >= len(messages):
                break
    return messages[start:]


def asks_in(messages: List[Any]) -> List[str]:
    asks = []
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        c = m.get("content")
        texts = [c] if isinstance(c, str) else [p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"] if isinstance(c, list) else []
        for t in texts:
            words = t.split(OBSERVATION_MARKER)[0]
            # strip shortened prefix
            if words.startswith(SHORTENED):
                words = words[len(SHORTENED):]
            words = words.strip()
            if not words:
                continue
            line = " ".join(words.split())
            if len(line) > ASK:
                line = line[:ASK] + "…"
            asks.append(line)
    # dedup preserving order
    seen = set()
    deduped = []
    for a in asks:
        if a not in seen:
            seen.add(a)
            deduped.append(a)
    asks = deduped
    # bounded: keep first few and last, remove middle
    while len(asks) > 2 and sum(len(a) + 4 for a in asks) > ASKS:
        idx = min(3, len(asks) - 2)
        if idx >= len(asks) - 1:
            break
        del asks[idx]
    return asks


def list_asks(asks: List[str]) -> str:
    if not asks:
        return ""
    return ASKED + "\n".join(f"- {a}" for a in asks) + "\n\n"


def note_shortened(messages: List[Any], asks: List[str]) -> List[Any]:
    if not messages or not isinstance(messages[0], dict):
        return messages
    asks = asks[: (len(asks))]  # keep
    # bounded
    while len(asks) > 2 and sum(len(a) + 4 for a in asks) > ASKS:
        idx = 3 if 3 < len(asks) - 1 else len(asks) - 2
        if idx < 0 or idx >= len(asks):
            break
        del asks[idx]
    note = SHORTENED + list_asks(asks)
    out = [dict(m) for m in messages]
    m0 = out[0]
    c = m0.get("content")
    if isinstance(c, str):
        m0["content"] = note + c
    elif isinstance(c, list):
        # prepend text part
        m0["content"] = [{"type": "text", "text": note}] + list(c)
    return out


def fit(history: List[Any], turn: List[Any], budget: ContextBudget) -> Tuple[List[Any], List[Any]]:
    """Fit history + turn into budget. Returns (history, turn)."""
    cleared_note = CLEARED_NOTE
    # put away images: not implemented for LYNX text-only; skip.

    history = [dict(m) for m in history]
    turn = [dict(m) for m in turn]

    h_bytes = total_bytes(history)
    t_bytes = total_bytes(turn)

    def within(hb, tb, bound):
        return (hb + tb) <= bound

    if within(h_bytes, t_bytes, budget.clear_at):
        return history, turn

    # layer 1: clear earlier turns up to previous turn
    end = previous_turn_index(history) if history else 0
    # clear_until uses end as count
    cleared = clear_until(history, end, True, cleared_note)
    if cleared is not None:
        history = cleared
        h_bytes = total_bytes(history)

    if within(h_bytes, t_bytes, budget.limit):
        return history, turn

    # layer 2: clear all history
    cleared = clear_until(history, len(history), True, cleared_note)
    if cleared is not None:
        history = cleared
        h_bytes = total_bytes(history)

    if within(h_bytes, t_bytes, budget.limit):
        return history, turn

    # layer 3: clear turn's older tool results up to last tool index
    last_tool = None
    for i in range(len(turn) - 1, -1, -1):
        if isinstance(turn[i], dict) and turn[i].get("role") == "tool":
            last_tool = i
            break
    if last_tool is not None:
        cleared = clear_until(turn, last_tool, False, cleared_note)
        if cleared is not None:
            turn = cleared
            t_bytes = total_bytes(turn)

    if within(h_bytes, t_bytes, budget.limit):
        return history, turn

    # layer 4: drop earliest exchanges
    listed = len(SHORTENED) + len(list_asks([]))  # approximate
    # compute asks from history to be removed
    room = int((budget.limit * 0.75) - (t_bytes + listed))
    if room < 0:
        room = 0
    kept = drop_earliest(history, room)
    removed = history[:len(history) - len(kept)] if kept else history
    asks = asks_in(removed)
    if len(kept) == len(history):
        pass
    elif not kept:
        turn = note_shortened(turn, asks)
    else:
        history = note_shortened(list(kept), asks)

    h_bytes = total_bytes(history)
    t_bytes = total_bytes(turn)
    total = h_bytes + t_bytes
    if total <= budget.limit:
        return history, turn

    # layer 5: cut latest tool result
    # find last tool index in turn
    at = None
    for i in range(len(turn) - 1, -1, -1):
        if isinstance(turn[i], dict) and turn[i].get("role") == "tool":
            at = i
            break
    if at is None:
        return history, turn
    room2 = int(budget.limit) - (total - bytes_of(turn[at]))
    # cut content of that tool message
    msg = turn[at]
    if not isinstance(msg, dict):
        return history, turn
    content = msg.get("content")
    # handle str or list of tool_result
    if isinstance(content, list):
        new_content = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "tool_result":
                cc = part.get("content")
                if isinstance(cc, str):
                    if len(cc) > room2 and room2 > HEAD:
                        part = {**part, "content": opening(cc, max(HEAD, room2 - len(CLEARED_NOTE))) + CLEARED_NOTE}
                new_content.append(part)
            else:
                new_content.append(part)
        new_msg = dict(msg)
        new_msg["content"] = new_content
        new_turn = list(turn)
        new_turn[at] = new_msg
        turn = new_turn

    return history, turn


if __name__ == "__main__":
    # tiny demo
    big = "x" * 5000
    history = [{"role": "user", "content": "first request " + big},
               {"role": "assistant", "content": "ok"},
               {"role": "tool", "content": [{"type": "tool_result", "tool_name": "lynx_read", "content": big}]}]
    turn = [{"role": "user", "content": "now do something"}]
    b = ContextBudget(clear_at=1000, limit=2000)
    h, t = fit(history, turn, b)
    print("history len:", len(h), "turn len:", len(t))
    print("total bytes:", total_bytes(h) + total_bytes(t))
    print(json.dumps(h)[:200])
