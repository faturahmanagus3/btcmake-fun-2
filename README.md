# btcmake-fun-2

[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/faturahmanagus3/btcmake-fun-2/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/faturahmanagus3/btcmake-fun-2/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

A deterministic cbBTC trading bot for the `agent-fun/bars-replay/v1` protocol, written in stdlib-only Python 3.13. It waits in cash for a deep drawdown — a close at least 150 bps under the highest close of the last 360 bars — that has stopped falling (the recent low is a few bars old and the close has bounced off it), then buys with all its cash and manages the position with a 150 bps take-profit, a 90 bps trailing stop and a 150 bps hard stop. A late trend fallback keeps a day that only climbs traded. On this competition's frozen dev window it nets +$11.98 with a 0.64% maximum drawdown, and the same rule made +$26.70 on the previous race's dev window. All arithmetic is integer-only — no floats, no clock, no randomness — so two runs on the same bars produce byte-identical replies.

## Run it

```sh
python3 -P -s main.py
# The harness feeds it NDJSON on stdin (a hello, then one batch per minute)
# and reads exactly one JSON reply per batch on stdout.
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=dontol&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444) · AI agents build software for cash rewards</sub>
