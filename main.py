"""Deep-drawdown reversal buyer for the cbBTC one-minute bars race.

Protocol: agent-fun/bars-replay/v1. The harness sends a hello, then one
batch per minute bar; each batch carries that bar, the fills of the
orders sent on the previous batch, and the account. An order decided on
a batch fills at the next bar's open.

The market model charges for every trade: a full-size round trip pays
the 4 bps fee twice, the 2 bps modelled slippage twice, and constant-
product impact twice against a pool under a million USDC deep -- roughly
35 bps all in. On a day that grinds one way, most signals are worth less
than that. One pattern is not: after cbBTC has fallen hard from its
recent peak and stopped falling, the next two hours drift upward far
more often than they keep falling (on this kit's dev window, closes
150+ bps under their trailing six-hour peak went on to gain about
50 bps over the following two hours on average, and the same rule made
money on the previous race's window too).

So the bot waits in cash for a deep drawdown that has bottomed out:

  * the close sits at least DRAWDOWN_BPS under the highest close of the
    last PEAK_N bars,
  * the lowest close of the last LOW_SPAN bars is at least SETTLE_BARS
    old, so the fall has paused,
  * and the close has bounced REBOUND_BPS off that low.

It then buys with all the cash it holds and manages one position:

  * take profit: sell when the close gains TAKE_PROFIT_BPS on the close
    that decided the entry,
  * trailing stop: sell when the close falls TRAIL_BPS under the highest
    close seen while holding,
  * hard stop: sell when the close falls STOP_BPS under the entry close
    (the "bottom" was a ledge, not a floor).

Fallback: if no drawdown trade has happened by LATE_SEQ and the close
is above its trailing mean, the bot buys once and rides the trend,
leaving on the trailing stop, the hard stop, or a close back under the
mean. A day that only climbs still gets the one trade the race's
guardrails ask for.

All arithmetic is on integers (prices are integers at the symbol's
price scale) and every comparison cross-multiplies instead of dividing,
so the same bars always produce the same orders, byte for byte: no
floats in any decision, no clock, no randomness, no files, no
environment.

Run as the grader runs it: python3 -P -s /bot/main.py, PYTHONHASHSEED=0.
-P keeps this file's own directory off sys.path, so vendor/ is added by
hand below; vendor/makefun_bars.py is the kit's SDK shim, unmodified.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

ASSET = "CBBTC"

# --- tuning (basis points are hundredths of a percent) ---
PEAK_N = 360          # the trailing peak is the highest of this many closes
DRAWDOWN_BPS = 150    # buy only when the close is this far under that peak
LOW_SPAN = 90         # the recent low is read over this many closes
REBOUND_BPS = 15      # the close must sit this far above that low
SETTLE_BARS = 5       # and the low must be at least this many bars old
TAKE_PROFIT_BPS = 150  # bank the reversal once the close gains this on the entry
TRAIL_BPS = 90        # or leave when the close falls this far under the holding peak
STOP_BPS = 150        # hard stop under the entry close
MEAN_N = 360          # trailing mean, used only by the trend fallback
LATE_SEQ = 1200       # the fallback may fire from this batch on
LAST_ENTRY_SEQ = 1395  # entries decided later than this are pointless
BUY_SLIP_BPS = 200    # slippage cap on buys: slippage plus impact plus a gap allowance
SELL_SLIP_BPS = 600   # slippage cap on sells: wide, an exit should not be blocked

MIN_ORDER = 1_000_000  # hello's fees.min_notional_quote_units (1 USDC)


class ReversalBuyer:
    """The strategy's memory across batches.

    closes holds every close seen, oldest first. While a position is
    open, ref_close is the close that decided its entry, peak_close the
    highest close seen since, and kind says which entry opened it
    ("reversal" or "trend"): the exits differ.
    """

    def __init__(self):
        self.closes = []
        self.ref_close = None
        self.ref_pending = None   # entry-decision close of a buy not yet seen filled
        self.peak_close = None
        self.kind = None
        self.kind_pending = None
        self.held_once = False

    # -- helpers -------------------------------------------------------

    def trailing_peak(self):
        if len(self.closes) < PEAK_N:
            return None
        return max(self.closes[-PEAK_N:])

    def above_mean(self, close):
        if len(self.closes) < MEAN_N:
            return False
        return close * MEAN_N > sum(self.closes[-MEAN_N:])

    def drawdown_ready(self, close):
        """A deep fall from the trailing peak that has stopped falling."""
        peak = self.trailing_peak()
        if peak is None or len(self.closes) < LOW_SPAN:
            return False
        # In the drawdown when close <= peak * (1 - DRAWDOWN_BPS/10000).
        if close * 10_000 > peak * (10_000 - DRAWDOWN_BPS):
            return False
        recent = self.closes[-LOW_SPAN:]
        low = min(recent)
        age = 0
        for j in range(len(recent) - 1, -1, -1):
            if recent[j] == low:
                age = len(recent) - 1 - j
                break
        if age < SETTLE_BARS:
            return False
        # Bounced when close >= low * (1 + REBOUND_BPS/10000).
        return close * 10_000 >= low * (10_000 + REBOUND_BPS)

    def should_exit(self, close):
        if self.ref_close is not None:
            if (self.ref_close - close) * 10_000 > STOP_BPS * self.ref_close:
                return True
            if self.kind == "reversal" and \
                    (close - self.ref_close) * 10_000 >= TAKE_PROFIT_BPS * self.ref_close:
                return True
        if self.peak_close is not None and \
                (self.peak_close - close) * 10_000 > TRAIL_BPS * self.peak_close:
            return True
        if self.kind == "trend" and len(self.closes) >= MEAN_N:
            return close * MEAN_N < sum(self.closes[-MEAN_N:])
        return False

    # -- the per-batch decision ----------------------------------------

    def decide(self, state, batch):
        bar = None
        for candidate in batch["bars"]:
            if candidate["symbol"] == ASSET:
                bar = candidate
                break
        if bar is None:
            return []
        close = int(bar["c"])
        self.closes.append(close)

        holding = state.positions.get(ASSET)
        if holding is not None:
            self.held_once = True
            if self.ref_close is None:
                # First batch showing the position: adopt the entry close.
                self.ref_close = self.ref_pending if self.ref_pending is not None else close
                self.kind = self.kind_pending if self.kind_pending is not None else "reversal"
                self.peak_close = close
            elif close > self.peak_close:
                self.peak_close = close
            if self.should_exit(close):
                return [{"side": "sell", "symbol": ASSET, "qty": holding.qty,
                         "max_slippage_bps": SELL_SLIP_BPS}]
            return []

        # Flat. Drop stale references and look for the next entry.
        self.ref_close = None
        self.peak_close = None
        self.kind = None
        if state.warming_up or state.seq > LAST_ENTRY_SEQ:
            return []

        kind = None
        if self.drawdown_ready(close):
            kind = "reversal"
        elif not self.held_once and state.seq >= LATE_SEQ and self.above_mean(close):
            kind = "trend"
        if kind is None:
            return []

        spend = state.cash
        room = state.weight_room(ASSET)
        if room < spend:
            spend = room
        if spend < MIN_ORDER:
            return []
        self.ref_pending = close
        self.kind_pending = kind
        return [{"side": "buy", "symbol": ASSET, "notional_quote_units": spend,
                 "max_slippage_bps": BUY_SLIP_BPS}]


_bot = ReversalBuyer()


def on_hello(state):
    global _bot
    _bot = ReversalBuyer()


def on_batch(state, batch):
    return _bot.decide(state, batch)


if __name__ == "__main__":
    makefun_bars.run(on_batch, on_hello=on_hello)
