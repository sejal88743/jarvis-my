"""Public market research and simulated strategy backtests. Never places orders."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf
from backtesting import Backtest, Strategy
from backtesting.lib import crossover


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_WATCHLIST_PATH = _base_dir() / "config" / "market_watchlist.json"
_ALLOWED_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"}
_ALLOWED_INTERVALS = {"1d", "1wk"}
_SYMBOL_RE = re.compile(r"^[A-Z0-9^=][A-Z0-9^=._-]{0,19}$")


def _symbol(value: str) -> str:
    result = str(value or "").strip().upper()
    if not _SYMBOL_RE.fullmatch(result):
        raise ValueError("Enter a valid Yahoo Finance symbol, for example AAPL or ^NSEI.")
    return result


def _load_watchlist() -> list[str]:
    try:
        data = json.loads(_WATCHLIST_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return list(dict.fromkeys(
        item for item in (str(value).strip().upper() for value in data)
        if _SYMBOL_RE.fullmatch(item)
    ))


def _save_watchlist(symbols: list[str]) -> None:
    _WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _WATCHLIST_PATH.write_text(
        json.dumps(list(dict.fromkeys(symbols)), indent=2),
        encoding="utf-8",
    )


def _search(query: str) -> str:
    query = str(query or "").strip()
    if not query:
        return "Give a company, index, or ticker to search."
    try:
        results = yf.Search(query, max_results=8, news_count=0).quotes
    except Exception:
        return "Market search failed. Check the internet connection or try a ticker symbol."

    matches = []
    for quote in results or []:
        symbol = str(quote.get("symbol", "")).strip()
        if not symbol:
            continue
        name = quote.get("shortname") or quote.get("longname") or "Unknown name"
        kind = quote.get("quoteType") or "security"
        exchange = quote.get("exchange") or quote.get("exchDisp") or ""
        matches.append(f"{symbol} | {name} | {kind}" + (f" | {exchange}" if exchange else ""))
    return "\n".join(matches[:8]) if matches else f"No market symbols found for '{query}'."


def _history(symbol: str, period: str, interval: str) -> pd.DataFrame:
    if period not in _ALLOWED_PERIODS:
        raise ValueError(f"Period must be one of: {', '.join(sorted(_ALLOWED_PERIODS))}.")
    if interval not in _ALLOWED_INTERVALS:
        raise ValueError("Interval must be 1d or 1wk.")

    data = yf.Ticker(symbol).history(
        period=period,
        interval=interval,
        auto_adjust=True,
        actions=False,
        timeout=20,
    )
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if data.empty or any(column not in data.columns for column in needed):
        raise ValueError(f"No OHLC history is available for {symbol}.")
    data = data[needed].dropna().sort_index()

    # Do not use a still-forming daily or weekly candle for the current period.
    last = data.index[-1]
    now = pd.Timestamp.now(tz=data.index.tz) if data.index.tz is not None else pd.Timestamp.now()
    if interval == "1d" and last.date() == now.date():
        data = data.iloc[:-1]
    elif interval == "1wk" and last.isocalendar()[:2] == now.isocalendar()[:2]:
        data = data.iloc[:-1]
    if len(data) < 60:
        raise ValueError("At least 60 completed bars are needed for this analysis.")

    data.index = pd.DatetimeIndex(data.index).tz_localize(None)
    return data


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    loss = -change.clip(upper=0).ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    relative_strength = gain / loss.replace(0, float("nan"))
    result = 100 - (100 / (1 + relative_strength))
    result = result.mask((loss == 0) & (gain > 0), 100)
    result = result.mask((loss == 0) & (gain == 0), 50)
    return result.fillna(50)


def _validate_windows(fast: int, slow: int) -> None:
    if fast < 5 or slow < 20 or fast >= slow or slow > 250:
        raise ValueError("Use windows where 5 <= fast < slow <= 250.")


def _analysis(symbol: str, data: pd.DataFrame, fast: int, slow: int) -> str:
    _validate_windows(fast, slow)
    close = data["Close"].astype(float)
    fast_sma = close.rolling(fast).mean()
    slow_sma = close.rolling(slow).mean()
    rsi = _rsi(close)
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    price = float(close.iloc[-1])
    fast_value = float(fast_sma.iloc[-1])
    slow_value = float(slow_sma.iloc[-1])
    rsi_value = float(rsi.iloc[-1])
    macd_value = float(macd.iloc[-1])
    signal_value = float(macd_signal.iloc[-1])

    if price > fast_value > slow_value and macd_value > signal_value and rsi_value < 70:
        signal = "BUY SETUP"
    elif price < fast_value < slow_value and macd_value < signal_value:
        signal = "SELL / REDUCE SETUP"
    else:
        signal = "HOLD / NO CONFIRMED SETUP"

    recent = data.tail(20)
    support = float(recent["Low"].min())
    resistance = float(recent["High"].max())
    last_day = data.index[-1].date().isoformat()
    return (
        f"{symbol} | data through {last_day}\n"
        f"Rule-based signal: {signal} (not a guarantee or an order).\n"
        f"Adjusted close: {price:.2f} | SMA{fast}: {fast_value:.2f} | SMA{slow}: {slow_value:.2f}\n"
        f"RSI14: {rsi_value:.1f} | MACD: {macd_value:.3f} | MACD signal: {signal_value:.3f}\n"
        f"20-bar range: support {support:.2f} / resistance {resistance:.2f}.\n"
        "Indicators use completed candles only. Confirm quotes, liquidity, and your risk limits independently."
    )


class _SmaCrossStrategy(Strategy):
    fast_window = 20
    slow_window = 50

    def init(self):
        def sma(values, window):
            return pd.Series(values).rolling(window).mean().to_numpy()

        self.fast_sma = self.I(sma, self.data.Close, self.fast_window)
        self.slow_sma = self.I(sma, self.data.Close, self.slow_window)

    def next(self):
        if crossover(self.fast_sma, self.slow_sma):
            if self.position:
                self.position.close()
            self.buy()
        elif crossover(self.slow_sma, self.fast_sma) and self.position:
            self.position.close()


def _backtest(symbol: str, data: pd.DataFrame, fast: int, slow: int,
              cash: float, commission_bps: float) -> str:
    _validate_windows(fast, slow)
    if cash < 1000 or cash > 100_000_000:
        raise ValueError("Starting cash must be between 1,000 and 100,000,000.")
    if commission_bps < 0 or commission_bps > 200:
        raise ValueError("Commission must be between 0 and 200 basis points.")

    test = Backtest(
        data,
        _SmaCrossStrategy,
        cash=cash,
        commission=commission_bps / 10_000,
        exclusive_orders=True,
        trade_on_close=False,
        finalize_trades=True,
    )
    stats = test.run(fast_window=fast, slow_window=slow)
    return (
        f"SIMULATED BACKTEST ONLY — {symbol}, SMA {fast}/{slow}, "
        f"{data.index[0].date()} to {data.index[-1].date()}\n"
        f"Strategy return: {stats.get('Return [%]', float('nan')):.2f}% | "
        f"Buy/hold: {stats.get('Buy & Hold Return [%]', float('nan')):.2f}%\n"
        f"Max drawdown: {stats.get('Max. Drawdown [%]', float('nan')):.2f}% | "
        f"Trades: {int(stats.get('# Trades', 0))} | "
        f"Win rate: {stats.get('Win Rate [%]', float('nan')):.1f}%\n"
        f"Sharpe: {stats.get('Sharpe Ratio', float('nan')):.2f} | "
        f"Commission: {commission_bps:g} bps per trade. Slippage, taxes, and live execution are not modeled."
    )


def market_analyst(parameters: dict, player=None) -> str:
    """Search public market data, manage a local watchlist, analyze, or backtest."""
    params = parameters or {}
    action = str(params.get("action", "analyze")).strip().lower()
    symbol = str(params.get("symbol", "")).strip()

    try:
        if action == "search":
            return _search(params.get("query", ""))

        if action == "watchlist":
            symbols = _load_watchlist()
            message = "Watchlist is empty." if not symbols else "Local watchlist: " + ", ".join(symbols)
            if player:
                player.write_log(f"SYS: {message}")
            return "Watchlist details were displayed locally and were not shared."

        if action == "add":
            selected = _symbol(symbol)
            symbols = _load_watchlist()
            if selected not in symbols:
                symbols.append(selected)
                _save_watchlist(symbols)
            if player:
                player.write_log(f"SYS: Added {selected} to the local market watchlist.")
            return "Watchlist updated locally; its contents were not shared."

        if action == "remove":
            selected = _symbol(symbol)
            symbols = _load_watchlist()
            if selected not in symbols:
                return f"{selected} is not on the local watchlist."
            symbols.remove(selected)
            _save_watchlist(symbols)
            if player:
                player.write_log(f"SYS: Removed {selected} from the local market watchlist.")
            return "Watchlist updated locally; its contents were not shared."

        if action not in {"analyze", "backtest"}:
            return "Use search, add, remove, watchlist, analyze, or backtest."
        selected = _symbol(symbol)
        period = str(params.get("period", "2y")).strip().lower()
        interval = str(params.get("interval", "1d")).strip().lower()
        data = _history(selected, period, interval)
        fast = int(params.get("fast_window", 20))
        slow = int(params.get("slow_window", 50))

        if action == "analyze":
            return _analysis(selected, data, fast, slow)
        return _backtest(
            selected,
            data,
            fast,
            slow,
            float(params.get("starting_cash", 100_000)),
            float(params.get("commission_bps", 10)),
        )
    except (TypeError, ValueError) as exc:
        return f"Market analysis could not run: {exc}"
    except Exception:
        return "Market data or backtest failed. Check the ticker, internet connection, and available history."


TOOL = {
    "name": "market_analyst",
    "description": (
        "Search public stock/index symbols, maintain a local watchlist, calculate technical indicators, "
        "and run historical simulated backtests. Signals are estimates, never guarantees. "
        "This tool has no broker connection and cannot place trades."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "search | add | remove | watchlist | analyze | backtest",
            },
            "query": {"type": "STRING", "description": "Company, index, or ticker to search."},
            "symbol": {"type": "STRING", "description": "Yahoo Finance ticker, e.g. AAPL or ^NSEI."},
            "period": {
                "type": "STRING",
                "description": "History window: 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, or max. Default 2y.",
            },
            "interval": {"type": "STRING", "description": "Candle interval: 1d or 1wk. Default 1d."},
            "fast_window": {"type": "INTEGER", "description": "Fast SMA window, 5-100. Default 20."},
            "slow_window": {"type": "INTEGER", "description": "Slow SMA window, greater than fast and at most 250. Default 50."},
            "starting_cash": {"type": "NUMBER", "description": "Simulated starting cash for backtest. Default 100000."},
            "commission_bps": {"type": "NUMBER", "description": "Simulated commission in basis points per trade. Default 10."},
        },
        "required": ["action"],
    },
    "handler": market_analyst,
}