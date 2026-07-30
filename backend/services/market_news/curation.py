"""Parse project-root Market_News.txt curation contract (Architecture §8.8.2)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CURATION_PATH = _PROJECT_ROOT / "Market_News.txt"

# Canonical source ids used for priority, freshness, and window matching.
SOURCE_ALIASES: dict[str, str] = {
    "reuters india": "reuters",
    "reuters": "reuters",
    "moneycontrol": "moneycontrol",
    "moneycontrol live": "moneycontrol",
    "the economic times – markets": "economic_times",
    "the economic times - markets": "economic_times",
    "economic times markets": "economic_times",
    "economic times": "economic_times",
    "economic times analysis": "economic_times",
    "nse india": "nse",
    "nse announcements": "nse",
    "nse corporate announcements": "nse",
    "nse": "nse",
    "sebi circulars": "sebi",
    "sebi": "sebi",
    "pulse by zerodha": "pulse",
    "pulse": "pulse",
    "cnbc tv18": "cnbc_tv18",
    "cnbc": "cnbc_tv18",
}

SOURCE_DISPLAY: dict[str, str] = {
    "reuters": "Reuters India",
    "moneycontrol": "Moneycontrol",
    "economic_times": "Economic Times Markets",
    "nse": "NSE India",
    "sebi": "SEBI",
    "pulse": "Pulse by Zerodha",
    "cnbc_tv18": "CNBC TV18",
}

# Bot ingestion priority when Market_News.txt cannot be parsed (Architecture §8.8.2).
_DEFAULT_BOT_PRIORITY = ("reuters", "moneycontrol", "economic_times", "nse", "sebi")

_DEFAULT_WINDOWS: dict[str, tuple[str, ...]] = {
    "pre_open": ("reuters", "economic_times", "cnbc_tv18"),
    "session": ("moneycontrol", "pulse", "nse"),
    "after_close": ("economic_times", "nse", "sebi"),
}


@dataclass(frozen=True)
class CurationContract:
    """Ops-editable contract loaded from Market_News.txt."""

    path: Path
    monitors: tuple[str, ...] = ()
    bot_priority: tuple[str, ...] = _DEFAULT_BOT_PRIORITY
    windows: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(_DEFAULT_WINDOWS))
    loaded: bool = False

    def sources_for_window(self, window: str) -> tuple[str, ...]:
        return self.windows.get(window, ())


def normalize_source_id(name: str) -> str:
    key = re.sub(r"\s+", " ", name.strip().lower())
    key = key.replace("–", "-")
    if key in SOURCE_ALIASES:
        return SOURCE_ALIASES[key]
    for alias, source_id in SOURCE_ALIASES.items():
        if alias in key or key in alias:
            return source_id
    slug = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
    return slug or "unknown"


def resolve_curation_path(explicit: Path | str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.getenv("MARKET_NEWS_PATH", "").strip()
    if env:
        return Path(env)
    return _DEFAULT_CURATION_PATH


def _parse_bullet_lines(block: str) -> list[str]:
    items: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].split("—")[0].split("–")[0].strip())
    return items


def load_curation_contract(path: Path | str | None = None) -> CurationContract:
    """Load monitors, workflow windows, and bot priority from Market_News.txt."""
    curation_path = resolve_curation_path(path)
    if not curation_path.is_file():
        return CurationContract(path=curation_path, loaded=False)

    text = curation_path.read_text(encoding="utf-8")
    sections = re.split(r"\n##\s+", text)

    monitors: list[str] = []
    bot_priority: list[str] = []
    windows: dict[str, tuple[str, ...]] = dict(_DEFAULT_WINDOWS)

    for section in sections:
        header, _, body = section.partition("\n")
        header_l = header.strip().lower()
        if header_l.startswith("monitor"):
            monitors = [normalize_source_id(x) for x in _parse_bullet_lines(body)]
        elif "recommended daily workflow" in header_l:
            windows = _parse_workflow_windows(body)
        elif "for the ai trading bot" in header_l or "paper-sim" in header_l:
            bot_priority = _parse_bot_priority(body)

    if not bot_priority:
        bot_priority = list(_DEFAULT_BOT_PRIORITY)
    if not monitors:
        monitors = list(dict.fromkeys([*bot_priority, *sum(windows.values(), ())]))

    return CurationContract(
        path=curation_path,
        monitors=tuple(dict.fromkeys(monitors)),
        bot_priority=tuple(dict.fromkeys(bot_priority)),
        windows=windows,
        loaded=True,
    )


def _parse_workflow_windows(body: str) -> dict[str, tuple[str, ...]]:
    windows = dict(_DEFAULT_WINDOWS)
    current: str | None = None
    buckets: dict[str, list[str]] = {
        "pre_open": [],
        "session": [],
        "after_close": [],
    }
    for line in body.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("###"):
            title = lower.lstrip("#").strip()
            if "before market open" in title or "pre-open" in title:
                current = "pre_open"
            elif "during market" in title or "session" in title:
                current = "session"
            elif "after market" in title or "after close" in title:
                current = "after_close"
            else:
                current = None
            continue
        if current and stripped.startswith("- "):
            label = stripped[2:].split("—")[0].strip()
            buckets[current].append(normalize_source_id(label))
    for key, values in buckets.items():
        if values:
            windows[key] = tuple(dict.fromkeys(values))
    return windows


def _parse_bot_priority(body: str) -> list[str]:
    priority: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if not match:
            continue
        label = match.group(1).split("(")[0].strip()
        priority.append(normalize_source_id(label))
    return priority


def workflow_window_at(now: datetime | None = None) -> str:
    """Return U9 window: pre_open | session | after_close (IST)."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(IST)
    t = local.time()
    if time(8, 0) <= t < time(9, 15):
        return "pre_open"
    if time(9, 15) <= t < time(15, 30):
        return "session"
    return "after_close"
