"""Classify India headlines into tone / topics / symbols / macro flags (Part U)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Common NSE underlyings + indices for U3 symbol tags.
_KNOWN_SYMBOLS: tuple[str, ...] = (
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "RELIANCE",
    "TCS",
    "INFY",
    "INFOSYS",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "ITC",
    "LT",
    "AXISBANK",
    "KOTAKBANK",
    "BHARTIARTL",
    "HINDUNILVR",
    "BAJFINANCE",
    "MARUTI",
    "TATAMOTORS",
    "WIPRO",
    "HCLTECH",
    "SUNPHARMA",
    "TITAN",
    "ULTRACEMCO",
    "NTPC",
    "POWERGRID",
    "ONGC",
    "COALINDIA",
    "ADANIENT",
    "ADANIPORTS",
)

_SYMBOL_ALIASES: dict[str, str] = {
    "INFOSYS": "INFY",
    "HDFC BANK": "HDFCBANK",
    "ICICI BANK": "ICICIBANK",
    "STATE BANK": "SBIN",
    "SBI": "SBIN",
    "BAJAJ FINANCE": "BAJFINANCE",
    "TATA MOTORS": "TATAMOTORS",
    "HCL TECH": "HCLTECH",
    "SUN PHARMA": "SUNPHARMA",
    "BHARTI AIRTEL": "BHARTIARTL",
    "HINDUSTAN UNILEVER": "HINDUNILVR",
}

_EARNINGS_RE = re.compile(
    r"\b(earnings|results|quarterly|q[1-4]\b|pat\b|guidance|profit.?after.?tax)\b",
    re.I,
)
_MACRO_RE = re.compile(
    r"\b(rbi|inflation|gdp|fii|dii|crude|repo|mpc|macro|policy|yields?)\b",
    re.I,
)
_SEBI_RE = re.compile(r"\b(sebi|circular|regulator(?:y)?|compliance|ban|penalty)\b", re.I)
_CORP_RE = re.compile(
    r"\b(dividend|bonus|split|buyback|merger|demerger|rights.?issue|corporate.?action)\b",
    re.I,
)
_SECTOR_RE = re.compile(
    r"\b(it\b|banking|pharma|auto|metal|energy|realty|fmcg|psu|midcap|sector)\b",
    re.I,
)
_POST_SHOCK_RE = re.compile(
    r"\b(crash|circuit|panic|crisis|meltdown|bloodbath|black.?swan|sell-?off|"
    r"flash.?crash|war\b|geopolitical.?shock|post-?shock)\b",
    re.I,
)
_BULLISH_RE = re.compile(
    r"\b(rally|surge|jump|soar|gains?|record.?high|upgrade|bullish|rebound|recovery)\b",
    re.I,
)
_BEARISH_RE = re.compile(
    r"\b(plunge|slump|weak|downgrade|bearish|tumble|fall(?:s|ing)?|drop(?:s|ped)?|"
    r"sell.?off|cut.?chatter|guidance.?cut)\b",
    re.I,
)
_BREAKING_RE = re.compile(r"\b(breaking|flash|urgent|just.?in)\b", re.I)

# Trust tier weight for dominant_tone aggregation — mirrors Market_News.txt's
# "For the AI trading bot" priority order (Tier 1 official/regulatory down to
# Tier 4 aggregator/TV). Higher tiers dominate when sources disagree on tone.
_SOURCE_TRUST_WEIGHT: dict[str, float] = {
    "nse": 2.0,
    "sebi": 2.0,
    "reuters": 1.5,
    "moneycontrol": 1.0,
    "economic_times": 1.0,
    "pulse": 0.6,
    "cnbc_tv18": 0.6,
}
_DEFAULT_TRUST_WEIGHT = 1.0


def _trust_weight(source_id: str) -> float:
    return _SOURCE_TRUST_WEIGHT.get(source_id, _DEFAULT_TRUST_WEIGHT)


@dataclass
class ClassifiedHeadline:
    title: str
    summary: str
    source: str
    source_id: str
    time_published: str
    tone: str  # bullish | neutral | bearish
    sentiment_label: str
    sentiment_score: float
    topics: list[str] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    relevance_to_trade: str | None = None


def classify_headline(
    *,
    title: str,
    summary: str = "",
    source: str,
    source_id: str,
    time_published: str,
    tickers_hint: list[str] | None = None,
) -> ClassifiedHeadline:
    text = f"{title}. {summary}"
    topics = _extract_topics(text, source_id)
    tickers = _extract_symbols(text, tickers_hint)
    tone, label, score = _score_tone(text)
    relevance = _relevance(topics, tickers, tone)
    return ClassifiedHeadline(
        title=title.strip(),
        summary=(summary or title).strip(),
        source=source,
        source_id=source_id,
        time_published=time_published,
        tone=tone,
        sentiment_label=label,
        sentiment_score=score,
        topics=topics,
        tickers=tickers,
        relevance_to_trade=relevance,
    )


def _extract_topics(text: str, source_id: str) -> list[str]:
    topics: list[str] = []
    if _EARNINGS_RE.search(text):
        topics.append("earnings")
    if _MACRO_RE.search(text):
        topics.append("macro")
    if _SEBI_RE.search(text) or source_id == "sebi":
        topics.append("sebi_regulatory")
    if _CORP_RE.search(text):
        topics.append("corporate_action")
    if _SECTOR_RE.search(text):
        topics.append("sector")
    if _POST_SHOCK_RE.search(text):
        topics.append("post_shock")
    if not topics:
        topics.append("financial_markets")
    return list(dict.fromkeys(topics))


def _extract_symbols(text: str, hints: list[str] | None) -> list[str]:
    found: list[str] = []
    upper = text.upper()
    for alias, canon in _SYMBOL_ALIASES.items():
        if alias in upper:
            found.append(canon)
    for sym in _KNOWN_SYMBOLS:
        if re.search(rf"\b{re.escape(sym)}\b", upper):
            found.append(_SYMBOL_ALIASES.get(sym, sym))
    for hint in hints or []:
        canon = _SYMBOL_ALIASES.get(hint.upper(), hint.upper())
        found.append(canon)
    # Prefer INFY over INFOSYS duplicate
    normalized = []
    for s in found:
        normalized.append("INFY" if s == "INFOSYS" else s)
    return list(dict.fromkeys(normalized))


def _score_tone(text: str) -> tuple[str, str, float]:
    if _POST_SHOCK_RE.search(text):
        return "bearish", "Somewhat-Bearish", -0.55
    bull = len(_BULLISH_RE.findall(text))
    bear = len(_BEARISH_RE.findall(text))
    if bull > bear and bull > 0:
        return "bullish", "Somewhat-Bullish", min(0.65, 0.15 * bull)
    if bear > bull and bear > 0:
        return "bearish", "Somewhat-Bearish", max(-0.65, -0.15 * bear)
    return "neutral", "Neutral", 0.0


def _relevance(topics: list[str], tickers: list[str], tone: str) -> str:
    if "post_shock" in topics:
        return "Post-shock / crisis tone — flagged for visibility (SH-4 news overlay); no automated block"
    if "earnings" in topics:
        sym = tickers[0] if tickers else "name"
        return f"Earnings / event risk for {sym} — gamma earnings_gap_mode candidate"
    if "sebi_regulatory" in topics:
        return "Regulatory surprise — elevate macro_risk_flags"
    if tickers and tone == "bearish":
        return f"Adverse tone vs {', '.join(tickers[:3])} — flagged for review"
    if tickers:
        return f"Symbol-tagged overlay for {', '.join(tickers[:3])}"
    return "Macro / market context for SH-4 overlay"


def aggregate_packet_flags(
    items: list[ClassifiedHeadline],
) -> dict[str, object]:
    """Roll classified items into Part U summary fields."""
    if not items:
        return {
            "dominant_tone": "neutral",
            "dominant_sentiment": "Neutral",
            "topics": [],
            "symbol_tags": [],
            "earnings_mentions": 0,
            "macro_risk_flags": ["No curated headlines available"],
            "news_not_blocking": True,
            "news_event_imminent": False,
            "news_post_shock": False,
            "news_impact": "none",
            "interpretation": "No Market_News headlines ingested this cycle.",
        }

    tone_scores = {"bullish": 0.0, "neutral": 0.0, "bearish": 0.0}
    topics: list[str] = []
    symbols: list[str] = []
    earnings = 0
    flags: list[str] = []
    post_shock = False
    event_imminent = False

    for item in items:
        weight = _trust_weight(item.source_id)
        tone_scores[item.tone] = (
            tone_scores.get(item.tone, 0.0) + (abs(item.sentiment_score) + 0.25) * weight
        )
        topics.extend(item.topics)
        symbols.extend(item.tickers)
        if "earnings" in item.topics:
            earnings += 1
            event_imminent = True
        if "post_shock" in item.topics:
            post_shock = True
        if "sebi_regulatory" in item.topics:
            flags.append("regulatory_surprise")
        if "macro" in item.topics and item.tone == "bearish":
            flags.append("macro_agitation")

    # Dominant = highest weighted tone (neutral wins ties toward calm).
    dominant_tone = max(
        ("neutral", "bullish", "bearish"),
        key=lambda t: (tone_scores.get(t, 0.0), 1 if t == "neutral" else 0),
    )
    if post_shock:
        dominant_tone = "bearish"

    sentiment_map = {
        "bullish": "Somewhat-Bullish",
        "bearish": "Somewhat-Bearish",
        "neutral": "Neutral",
    }
    topic_set = list(dict.fromkeys(topics))
    symbol_set = list(dict.fromkeys(symbols))

    if post_shock:
        flags.append("post-shock")
        flags.append("crisis_tone")
    if earnings >= 2:
        flags.append("elevated_earnings_coverage")
    elif earnings == 1:
        flags.append("company_event_coverage")
    if "sebi_regulatory" in topic_set and "regulatory_surprise" not in flags:
        flags.append("regulatory_surprise")

    flags = list(dict.fromkeys(flags))
    news_not_blocking = not post_shock and dominant_tone != "bearish"
    if event_imminent and dominant_tone == "bearish":
        news_impact = "early_exit"
    elif _any_breaking_bullish(items):
        news_impact = "rehedge_aggressive"
    elif dominant_tone == "bearish":
        news_impact = "early_exit"
    else:
        news_impact = "none"

    interpretation = _interpretation(
        dominant_tone=dominant_tone,
        topics=topic_set,
        earnings=earnings,
        post_shock=post_shock,
        flags=flags,
    )
    return {
        "dominant_tone": dominant_tone,
        "dominant_sentiment": sentiment_map[dominant_tone],
        "topics": topic_set,
        "symbol_tags": symbol_set,
        "earnings_mentions": earnings,
        "macro_risk_flags": flags,
        "news_not_blocking": news_not_blocking,
        "news_event_imminent": event_imminent,
        "news_post_shock": post_shock,
        "news_impact": news_impact,
        "interpretation": interpretation,
    }


def _any_breaking_bullish(items: list[ClassifiedHeadline]) -> bool:
    for item in items:
        blob = f"{item.title} {item.summary}"
        if _BREAKING_RE.search(blob) and item.tone == "bullish":
            return True
    return False


def _interpretation(
    *,
    dominant_tone: str,
    topics: list[str],
    earnings: int,
    post_shock: bool,
    flags: list[str],
) -> str:
    if post_shock:
        return (
            "Crisis / post-shock tone in curated India headlines — "
            "tagged bearish and flagged for visibility (SH-4 news overlay); "
            "no automated flatten or block."
        )
    parts = [
        f"Dominant tone {dominant_tone} from Market_News.txt priority sources.",
    ]
    if earnings:
        parts.append(
            f"{earnings} earnings/event mention(s) — prefer gamma earnings_gap_mode over plain long-vega."
        )
    if "macro" in topics:
        parts.append("Macro coverage present — cross-check FII/DII and RBI/policy flags.")
    if flags:
        parts.append(f"Flags: {', '.join(flags)}.")
    parts.append("Quant signals remain primary; news overlays SH-4 selection.")
    return " ".join(parts)
