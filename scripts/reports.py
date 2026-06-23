"""
scripts/reports.py
──────────────────
Phase 9 — Analytics CLI
Query MySQL and print formatted performance reports.

Usage:
    python scripts/reports.py --period week
    python scripts/reports.py --period month
    python scripts/reports.py --pair XAUUSD
    python scripts/reports.py --session
    python scripts/reports.py --full
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import load_config
from src.core.logger import setup_root_logger

setup_root_logger()

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from src.db.models import TradeHistory, DailyStat, get_session


def _get_session():
    return get_session()


def report_weekly(n_weeks: int = 1):
    """Print weekly performance summary."""
    session = _get_session()
    today = date.today()
    start = today - timedelta(weeks=n_weeks)

    trades = session.query(TradeHistory).filter(
        TradeHistory.closed_at >= start.isoformat()
    ).all()
    session.close()

    if not trades:
        print(f"No trades in the last {n_weeks} week(s).")
        return

    _print_trade_table(trades, f"Last {n_weeks} Week(s) Trade History")
    _print_summary(trades)


def report_monthly():
    """Print monthly performance summary."""
    session = _get_session()
    start = date.today().replace(day=1)

    trades = session.query(TradeHistory).filter(
        TradeHistory.closed_at >= start.isoformat()
    ).all()
    session.close()

    if not trades:
        print(f"No trades this month.")
        return

    _print_trade_table(trades, f"This Month — Trade History ({start.strftime('%B %Y')})")
    _print_summary(trades)


def report_pair(symbol: str):
    """Print per-pair performance breakdown."""
    session = _get_session()
    trades = session.query(TradeHistory).filter_by(symbol=symbol).all()
    session.close()

    if not trades:
        print(f"No trades for {symbol}.")
        return

    _print_trade_table(trades, f"{symbol} — All Trades")
    _print_summary(trades)


def report_sessions():
    """Print session-based performance (London vs NY)."""
    session = _get_session()
    trades = session.query(TradeHistory).all()
    session.close()

    sessions = {}
    for t in trades:
        key = t.session or "UNKNOWN"
        sessions.setdefault(key, []).append(t)

    if HAS_RICH:
        console = Console()
        table = Table(title="Session Performance", box=box.ROUNDED)
        table.add_column("Session", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Total P&L", justify="right")
        table.add_column("Profit Factor", justify="right")

        for sess_name, sess_trades in sorted(sessions.items()):
            wins = [t for t in sess_trades if t.pnl_usd > 0]
            wr = f"{len(wins)/len(sess_trades)*100:.1f}%" if sess_trades else "—"
            gross_p = sum(t.pnl_usd for t in wins)
            gross_l = abs(sum(t.pnl_usd for t in sess_trades if t.pnl_usd <= 0))
            pf = f"{gross_p/gross_l:.2f}" if gross_l > 0 else "∞"
            total = sum(t.pnl_usd for t in sess_trades)
            color = "green" if total >= 0 else "red"
            table.add_row(
                sess_name, str(len(sess_trades)), wr,
                f"[{color}]${total:+.2f}[/{color}]", pf,
            )
        console.print(table)
    else:
        print(f"\n{'Session':<12} {'Trades':>8} {'WinRate':>10} {'P&L':>10} {'PF':>8}")
        print("─" * 52)
        for sess_name, sess_trades in sorted(sessions.items()):
            wins = [t for t in sess_trades if t.pnl_usd > 0]
            wr = f"{len(wins)/len(sess_trades)*100:.1f}%" if sess_trades else "—"
            gross_p = sum(t.pnl_usd for t in wins)
            gross_l = abs(sum(t.pnl_usd for t in sess_trades if t.pnl_usd <= 0))
            pf = f"{gross_p/gross_l:.2f}" if gross_l > 0 else "inf"
            total = sum(t.pnl_usd for t in sess_trades)
            print(f"{sess_name:<12} {len(sess_trades):>8} {wr:>10} ${total:>+9.2f} {pf:>8}")


def _print_trade_table(trades, title: str):
    if HAS_RICH:
        console = Console()
        table = Table(title=title, box=box.ROUNDED, show_header=True)
        table.add_column("Date", style="dim")
        table.add_column("Symbol", style="cyan")
        table.add_column("Dir")
        table.add_column("Lots", justify="right")
        table.add_column("Pips", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Reason")
        table.add_column("Session", style="dim")

        for t in sorted(trades, key=lambda x: x.closed_at):
            color = "green" if t.pnl_usd > 0 else "red"
            dir_color = "green" if t.direction == "BUY" else "red"
            table.add_row(
                t.closed_at.strftime("%Y-%m-%d %H:%M"),
                t.symbol,
                f"[{dir_color}]{t.direction}[/{dir_color}]",
                f"{t.lot_size:.2f}",
                f"{t.pips:+.1f}",
                f"[{color}]${t.pnl_usd:+.2f}[/{color}]",
                t.close_reason or "—",
                t.session or "—",
            )
        console.print(table)
    else:
        print(f"\n{title}")
        print(f"{'Date':<20} {'Symbol':<10} {'Dir':<6} {'Lots':>6} {'Pips':>8} {'P&L':>10} {'Reason':<10}")
        print("─" * 80)
        for t in sorted(trades, key=lambda x: x.closed_at):
            print(f"{t.closed_at.strftime('%Y-%m-%d %H:%M'):<20} {t.symbol:<10} "
                  f"{t.direction:<6} {t.lot_size:>6.2f} {t.pips:>+8.1f} ${t.pnl_usd:>+9.2f} {t.close_reason or '—':<10}")


def _print_summary(trades):
    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    total_pnl = sum(t.pnl_usd for t in trades)
    gross_p = sum(t.pnl_usd for t in wins)
    gross_l = abs(sum(t.pnl_usd for t in losses))
    pf = gross_p / gross_l if gross_l > 0 else float("inf")
    wr = len(wins) / len(trades) * 100 if trades else 0

    print(f"\n  Summary: {len(trades)} trades | Win Rate: {wr:.1f}% | "
          f"Profit Factor: {pf:.2f} | Net P&L: ${total_pnl:+.2f}")


def main():
    parser = argparse.ArgumentParser(description="FX Bot Analytics Reports")
    parser.add_argument("--period", choices=["week", "month", "2week"],
                        help="Reporting period")
    parser.add_argument("--pair", help="Filter by symbol (e.g. XAUUSD)")
    parser.add_argument("--session", action="store_true", help="Session breakdown")
    parser.add_argument("--full", action="store_true", help="All-time report")
    args = parser.parse_args()

    try:
        load_config()
    except Exception as e:
        print(f"Config error: {e}")
        sys.exit(1)

    if args.pair:
        report_pair(args.pair.upper())
    elif args.session:
        report_sessions()
    elif args.period == "week":
        report_weekly(1)
    elif args.period == "2week":
        report_weekly(2)
    elif args.period == "month" or args.full:
        report_monthly()
    else:
        # Default: weekly
        report_weekly(1)


if __name__ == "__main__":
    main()
