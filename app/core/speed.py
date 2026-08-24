"""Parse speed / ETA hints from panel service names."""

from __future__ import annotations

# Lower rank = faster. 9 = unknown.
_SPEED_RULES: list[tuple[int, str, tuple[str, ...]]] = [
    (0, "мгновенно", ("instant", "мгновен", "ultra fast", "superfast", "super fast")),
    (1, "очень быстро", ("prime fast", "very fast", "extra fast", "оч. быстр")),
    (2, "быстро", ("fast", "быстр")),
    (3, "средне", ("medium", "normal", "средн")),
    (4, "медленно", ("slow", "медлен")),
    (5, "очень медленно", ("very slow", "оч. медлен")),
]


def detect_speed(name: str) -> tuple[int, str | None]:
    text = (name or "").lower()
    for rank, label, keywords in _SPEED_RULES:
        for kw in keywords:
            if kw in text:
                return rank, label
    # hour-based live viewers etc.
    if "час" in text or "hour" in text:
        return 2, "по часам"
    return 9, None


def format_speed_line(name: str, speed_rank: int | None = None) -> str | None:
    rank, label = detect_speed(name)
    if speed_rank is not None and speed_rank < 9:
        rank = speed_rank
        # refresh label from rank
        for r, lbl, _ in _SPEED_RULES:
            if r == rank:
                label = lbl
                break
    if not label:
        return None
    return f"⏱ Скорость: <b>{label}</b>"
