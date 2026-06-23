"""
src/scoring/engine.py
─────────────────────
Signal scoring engine. Aggregates component scores into a weighted total.
All weights and thresholds come from config.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src.core.config import get
from src.core.logger import get_logger
from src.strategy.liquidity import SweepResult, liquidity_score
from src.strategy.momentum import MomentumResult, momentum_score
from src.strategy.session_filter import SessionResult, session_score
from src.strategy.structure import BOSResult, bos_score
from src.strategy.trend import TrendDirection, trend_score

log = get_logger(__name__)


@dataclass
class ScoreBreakdown:
    total: float            # 0-100 weighted total
    trend: float            # 0-100 component score
    structure: float
    liquidity: float
    momentum: float
    session: float
    passed: bool
    direction: str          # BUY | SELL | NEUTRAL
    skip_reason: Optional[str] = None


def score_signal(
    symbol: str,
    trend: TrendDirection,
    bos: BOSResult,
    sweep: SweepResult,
    momentum: MomentumResult,
    session: SessionResult,
) -> ScoreBreakdown:
    """
    Combine strategy component outputs into a single confidence score.

    The proposed trade direction is derived from the strongest bullish/bearish
    signal combination (BOS + sweep must agree on direction).

    Returns:
        ScoreBreakdown with total score and per-component breakdown.
    """
    min_score = get("scoring.min_score", 65)
    weights = get("scoring.weights", {})

    w_trend = weights.get("trend", 30)
    w_structure = weights.get("structure", 25)
    w_liquidity = weights.get("liquidity", 20)
    w_momentum = weights.get("momentum", 15)
    w_session = weights.get("session", 10)

    total_weight = w_trend + w_structure + w_liquidity + w_momentum + w_session

    # ── Determine candidate trade direction ──────────────────────────
    from src.strategy.structure import BOSDirection

    if bos.direction == BOSDirection.BULLISH:
        candidate_direction = "BUY"
    elif bos.direction == BOSDirection.BEARISH:
        candidate_direction = "SELL"
    else:
        # No BOS, but we evaluate based on H1 trend to calculate diagnostic scores for the DB
        from src.strategy.trend import TrendDirection
        if trend == TrendDirection.BEARISH:
            candidate_direction = "SELL"
        else:
            candidate_direction = "BUY"

    # ── Compute component scores ─────────────────────────────────────
    s_trend = trend_score(trend, candidate_direction) * 100
    s_structure = bos_score(bos, candidate_direction) * 100
    s_liquidity = liquidity_score(sweep, candidate_direction) * 100
    s_momentum = momentum_score(momentum, candidate_direction) * 100
    s_session = session_score(session) * 100

    # ── Weighted total ───────────────────────────────────────────────
    weighted = (
        s_trend * w_trend +
        s_structure * w_structure +
        s_liquidity * w_liquidity +
        s_momentum * w_momentum +
        s_session * w_session
    ) / total_weight

    # Determine if the signal passes gates
    passed = True
    skip_reason = None
    final_direction = candidate_direction

    # Gate 1: BOS presence (essential trigger of strategy)
    if bos.direction == BOSDirection.NONE:
        passed = False
        final_direction = "NEUTRAL"
        skip_reason = "No Break of Structure detected."

    # Gate 2: Liquidity sweep conflict
    elif sweep.detected and sweep.direction != "NONE":
        if (sweep.direction == "BULLISH" and candidate_direction != "BUY") or \
           (sweep.direction == "BEARISH" and candidate_direction != "SELL"):
            passed = False
            final_direction = "NEUTRAL"
            skip_reason = f"BOS ({bos.direction.value}) conflicts with sweep ({sweep.direction})."

    # Gate 3: Session check
    if passed:
        trade_only_in_session = get("strategy.session.trade_only_in_session", True)
        if trade_only_in_session and not session.in_session:
            passed = False
            skip_reason = "Outside active trading session (London/NY)."

    # Gate 4: Score threshold check
    if passed and weighted < min_score:
        passed = False
        skip_reason = f"Score {weighted:.1f} < threshold {min_score}"

    breakdown = ScoreBreakdown(
        total=round(weighted, 2),
        trend=round(s_trend, 2),
        structure=round(s_structure, 2),
        liquidity=round(s_liquidity, 2),
        momentum=round(s_momentum, 2),
        session=round(s_session, 2),
        passed=passed,
        direction=final_direction,
        skip_reason=skip_reason,
    )

    log.info(
        "Signal [%s %s] score=%.1f (%s) | trend=%.0f struct=%.0f liq=%.0f mom=%.0f sess=%.0f",
        symbol, candidate_direction, weighted,
        "✅ PASS" if passed else "❌ SKIP",
        s_trend, s_structure, s_liquidity, s_momentum, s_session,
    )

    return breakdown
