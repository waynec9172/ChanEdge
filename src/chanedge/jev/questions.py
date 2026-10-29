"""English System One questions. question_set entry-v1. The cache key includes this text."""

from __future__ import annotations

QUESTION_SET = "entry-v1"
MODEL_PIN = "jev-1.14.0"

QUESTIONS: dict[str, object] = {
    "structure": {
        "type": "score",
        "instructions": (
            "Rate Chanlun structure quality from bi and segment overlap, "
            "zhongshu clarity, and whether the breakout is clean."
        ),
        "criteria": ["Very poor", "Poor", "Average", "Good", "Excellent"],
    },
    "location": {
        "type": "score",
        "instructions": (
            "Rate location quality at the zhongshu edge, versus the prior high "
            "or prior low, and inside the higher-timeframe structure."
        ),
        "criteria": ["Poor", "Fair", "Good", "Excellent"],
    },
    "resonance": {
        "type": "score",
        "instructions": (
            "Direction is already allowed. Rate how cleanly the higher timeframe "
            "supports this 15m signal. Do not decide whether the direction matches."
        ),
        "criteria": ["Poor", "Fair", "Good", "Excellent"],
    },
    "volatility_volume": {
        "type": "score",
        "instructions": (
            "ATR is already inside the allowed band. Rate how suitable ATR and "
            "relative volume are, from poor to excellent. Do not decide whether "
            "price is outside the band."
        ),
        "criteria": ["Poor", "Fair", "Good", "Excellent"],
    },
    "signal_bar": {
        "type": "score",
        "instructions": "Rate the signal bar: close location, body share, and wick length.",
        "criteria": ["Poor", "Average", "Good"],
    },
    "session": {
        "type": "score",
        "instructions": (
            "Rate trading quality of this session and market state. "
            "Do not decide whether the session should be skipped."
        ),
        "criteria": ["Poor", "Fair", "Good", "Excellent"],
    },
    "final_decision": {
        "type": "choice",
        "instructions": (
            "Log-only quality vote. Hard rules and the fixed threshold decide "
            "the trade. Do not treat this choice as an order."
        ),
        "criteria": {
            "GO": "Quality is good enough to consider an entry.",
            "NO_GO": "Quality is not good enough.",
        },
    },
}
