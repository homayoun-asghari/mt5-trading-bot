# MT5 Trading Bot — a live-running system on a demo account

An always-on MetaTrader 5 bot that traded six instruments on 15-minute bars, built between July 2024 and February 2025. It woke one second after every bar close, refused to trade around red-impact economic releases, flattened itself on a 2% daily drawdown, stood down over the weekend, and retrained its own models once a month.

**The strategy did not work.** The models behind it were validated with random train/test splits on overlapping rolling-window features, and the per-bar edge was two to three orders of magnitude smaller than the spread. A cost-aware simulation of the same rule returned **−11.75%**. That investigation is a separate repository: **[fx-ml-postmortem](https://github.com/homayoun-asghari/fx-ml-postmortem)** — read it before you read anything here as an endorsement of the signal.

What is left is the operational engineering, which is the genuinely good part and is independent of whether the signal had an edge. This README is mostly about that, and about the four bugs that shipped.

## Provenance

> Reconstructed in 2026 from a filesystem archive. This code was never under version control at the time. **Commit dates are the real modification times of the original files**, recovered with `stat`, accurate to the second. Commits dated 2026 are this README and the `.env.example`, and are labelled as such.
>
> One limit worth stating: a modification time is not an authorship time. It records when a file was last written, which for a copied or re-saved file is later than when the work was done. This drive holds duplicated trees, so some files were certainly moved between them. These dates are therefore a faithful transcription of the filesystem's timeline and a **floor** on when the work happened — not independent proof of authorship on that date.

Two ordering notes, both real:

- `U4.ipynb` (mtime `2025-01-11T06:26:18`) is committed **before** `U3.ipynb` (mtime `2025-01-20T18:08:04`), against the numbering. The two files are byte-identical apart from two lines that are active in U4 and commented out in U3, so the later mtime is the later state. Nothing was reordered for narrative; the filenames are simply misleading.
- No date in this repository was inferred. Every one came from an mtime.

> Three files — `training/train_USDJPY.ipynb`, `bot/check_and_trade.py` and `bot/fetch_news.ipynb` — were found in a later coverage sweep of the archive and committed afterwards, at their own real mtimes. They therefore sit at the tip of the branch while carrying 2024 dates.

## Timeline

| Date | File | What changed |
|---|---|---|
| 2024-07-30 | `lineage/2024-07-30_MT5.ipynb` | First broker connection, first manual order |
| 2024-08-02 | `lineage/2024-08-02_U2_M15.ipynb` | First unattended loop, aligned to the M15 close |
| 2024-08-06 | `lineage/2024-08-06_U2_4H.ipynb` | Same loop on H4 |
| 2024-09-17 | `lineage/2024-09-17_U2_15min.ipynb` | Stacked classifiers, HMM regimes, GARCH, Kalman |
| 2024-09-22 | `bot/config.py`, `bot/utils.py` | ForexFactory calendar parsing |
| 2024-09-27 | `lineage/2024-09-27_U3_monolith.ipynb` | 2,163 lines: training and trading in one file |
| 2024-10-01 | `lineage/2024-10-01_U_V4.ipynb` | Training split out; Selenium news scraping added |
| 2024-11-18 | `bot/2024-11-18_U.ipynb` | **Production.** 4 instruments, all the risk controls |
| 2024-11-30 | `bot/2024-11-30_U2.ipynb` | Retrain loop table-driven; SL suppression deleted |
| 2024-12-31 → 2025-01-25 | `training/` | Six per-pair model notebooks |
| 2025-01-11 | `bot/2025-01-11_U4.ipynb` | 6 instruments, trailing TP to the middle band |
| 2025-01-20 | `bot/2025-01-20_U3.ipynb` | Middle-band exit disabled |
| 2025-02-12 | `bot/2025-02-12_M.ipynb` | ML removed. Never ran — see below |

## The operational engineering

### Bar-boundary alignment, not `sleep(900)`

The loop never sleeps a fixed interval. It computes the exact next M15 boundary in broker time and busy-waits in one-second steps until one second past it:

```python
def get_next_bar_time(interval):
    now = datetime.strptime(get_mt5_time(), '%Y-%m-%d %H:%M:%S')
    if interval == mt5.TIMEFRAME_M15:
        minutes_past = now.minute % 15
        minutes_to_next_bar = (15 - minutes_past) % 15
        if minutes_to_next_bar == 0:
            minutes_to_next_bar = 15
        return now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_next_bar)
```

```python
next_check_time = next_bar_time + timedelta(seconds=1)
...
while MT5 < next_check_time:
    time.sleep(1)
    MT5 = datetime.strptime(get_mt5_time(), '%Y-%m-%d %H:%M:%S')
```

`sleep(900)` accumulates the loop body's own runtime as drift and eventually reads a bar that has not closed. This does not. All times come from `pytz.timezone('Etc/GMT-2')`, the broker's zone, never from the local clock.

### Red-news blackout, scraped from ForexFactory

`news_fetch()` drives Selenium over `forexfactory.com/calendar`, scrolls until `window.pageYOffset` stops changing, reads `calendar__table`, and maps the impact-icon CSS class to a colour through `ICON_COLOR_MAP`. It keeps only red-impact events in USD/EUR/GBP/CAD/AUD, converts their times to broker time, and writes `<Month>_news.csv`.

The loop then blocks, and flattens, across the window:

```python
while news_time - timedelta(minutes=29) <= MT5 < news_time + timedelta(minutes=15):
    open_position = get_open_position()
    if open_position:
        close_position(open_position)
        logging.info("Closed open position due to upcoming news event.")
```

29 minutes before, 15 minutes after. The calendar is re-scraped daily and again every Monday morning.

### 2% daily drawdown kill switch

`update_today_balance()` is scheduled at 00:07 broker time and snapshots the account balance into a module-level `today_balance`. Every signal is checked against it:

```python
current_balance = mt5.account_info().balance
daily_drawdown_balance_limit = today_balance - (today_balance * 0.02)
if current_balance < daily_drawdown_balance_limit:
    logging.info('We already hit the daily drawdown limit, ...')
    continue
```

It blocks new entries. It does not close an open position, and it is checked only on the entry path.

### Friday 21:21 flatten

```python
if MT5.weekday() >= 5 or (MT5.weekday() == 4 and MT5.time() >= datetime.strptime("21:21", "%H:%M").time()):
    if open_position:
        close_position(open_position)
    send_email('Market closed', ...)
    while MT5.weekday() >= 5 or (...):
        time.sleep(333)
        MT5 = datetime.strptime(get_mt5_time(), '%Y-%m-%d %H:%M:%S')
    news_fetch()
```

Nothing is carried over a weekend gap. The bot parks itself in a 333-second poll until Monday, then re-scrapes the calendar before resuming.

### Signal staleness check

```python
time_diff = MT5 - signal_time
if time_diff > timedelta(minutes=30):
    logging.info("The signal is old.")
    if open_position:
        close_position(open_position)
    continue
```

`signal_time` is the timestamp of the last bar the model actually saw. If the broker feed stalls or `copy_rates_from_pos` returns a stale frame, no order is sent on it.

### SL-repeat suppression (present once, then deleted)

`bot/2024-11-18_U.ipynb` walks `mt5.history_deals_get` backwards and refuses to re-enter in the direction that just got stopped out, within the same correlated instrument group, for 12 hours:

```python
ticker_group_a = ['EURUSD_i', 'GBPUSD_i']
ticker_group_b = ['XAGUSD_i', 'XAUUSD_i']
time_sl_check = (MT5 - timedelta(hours=12)).replace(tzinfo=None)
...
if (ticker in ticker_group_a and deal_symbol in ticker_group_a) or \
   (ticker in ticker_group_b and deal_symbol in ticker_group_b):
    if ((deal_type == 1 and current_signal == 1) or (deal_type == 0 and current_signal == -1)) and \
       comment_sl_check and deal_time_mt5 >= time_sl_check:
        skip_signal = True
        break
```

This is the most thoughtful risk control in the project — it recognises that EURUSD and GBPUSD are one bet, not two. **It was removed twelve days later in `bot/2024-11-30_U2.ipynb`, with no comment explaining why, and never came back.**

### Colour-coded logging

```python
GREEN = "\033[92m"
RESET = "\033[0m"

class CustomFormatter(logging.Formatter):
    def format(self, record):
        log_msg = super().format(record)
        return f"{GREEN}{log_msg}{RESET}"
```

One `logging.basicConfig` to `trading_journal.log`, plus a stdout handler with this formatter, so a long-running terminal session is readable at a glance while the file stays plain.

### Clean shutdown

```python
try:
    check_and_trade(stop_event, news_df)
except KeyboardInterrupt:
    print("Interrupted by user")
finally:
    mt5.shutdown()
    print("MetaTrader 5 connection closed")
```

`stop_event = Event()` is the loop condition, so the loop is stoppable from another thread, and the broker connection is always torn down.

### Monthly gated self-retrain

`retrain()` refits each pair's model, computes accuracy, Sharpe, max drawdown and cumulative strategy return, and overwrites the stored `.joblib` **only if the new metrics beat the old ones**, emailing the new model file as an attachment either way.

This looks like risk control. It is a ratchet: both sides of the comparison are in-sample, so the gate systematically selects for whichever refit overfits the recent window hardest. It is error #7 in the postmortem.

## What is wrong with it

**1 — `bot/2025-02-12_M.ipynb` never ran. `KeyError` on the first signal.**

The Bollinger columns are created under one set of names:

```python
df[["lower", "mid", "upper", "bandwidth", "percent"]] = ta.bbands(df["Close"], length=21, std=2.5)
```

and read under another:

```python
((df['Close'] < df['lowerBB']) & (df["macdh_daily"] > 0)),
((df['Close'] > df['upperBB']) & (df["macdh_daily"] < 0)),
```

`lowerBB` and `upperBB` are never assigned anywhere in the file. `get_signal()` raises `KeyError` the first time it is called, which is the first bar. Verified against the file.

The same notebook has a second, independent defect: `get_signal()` returns 11 values, one call site unpacks 9 and another unpacks 12. Neither would have worked either.

**2 — `lineage/2024-10-01_U_V4.ipynb` never ran. `AttributeError` on the first signal.**

```python
df[["lowerBB2", "midBB", "upperBB2", "bandwidthBB2", "percentBB2"]] = ta.bbands(df["Close"], length=21, std=2)
...
upper = df.upper.values[-1]
lower = df.lower.values[-1]
```

`df.upper` is attribute access for a column named `upper`, which this frame does not have — and `DataFrame.upper` is not a method either. `AttributeError` on the first call. Verified against the file.

**3 — `schedule_retrain()` does not schedule monthly.**

```python
time_diff = (schedule_time - now).total_seconds()
schedule.every(time_diff).seconds.do(retrain)
```

`schedule.every(n).seconds` creates a *repeating* job at that interval. The first fire lands on the 21st; every fire after that lands `time_diff` seconds later, which is not the 21st of anything. In `U3`/`U4` this is replaced by calling `retrain()` inside the weekend branch, which makes it weekly rather than monthly. Neither matches the intent.

**4 — The drawdown kill switch is weaker than it reads.**

It gates entries only. An open position that runs past the 2% line is not closed by it, and `today_balance` is a `global` mutated from a scheduled thread with no lock.

**5 — The models are not trustworthy, and the bot's own gate makes that worse.**

Every notebook under `training/` validates with `train_test_split` on 15-minute bars carrying overlapping rolling-window features. Adjacent bars land on both sides of the split with near-identical feature vectors. See `fx-ml-postmortem` for the full accounting.

**6 — These are notebooks.** No packaging, no tests, no dependency pinning, top-level side effects at import (`news_fetch()` runs on cell execution, `today_balance = mt5.account_info().balance` at module scope). Every failure path is one broad `except Exception` that logs, emails and sleeps 60 seconds.

**7 — It ran against `Alpari-MT5-Demo`.** The orders were real orders, sent through the real API, with real slippage semantics — on a demo server. No live capital was ever at risk through this code, and no live P&L exists to report.

## Credentials

The originals had the MT5 account number, MT5 password, mail account and mail password as string literals in the first cell of every notebook. They have been replaced by `os.environ[...]` reads by an automated scrubber, so none of them appear in this repository. See `.env.example`.

The MT5 credentials were for `Alpari-MT5-Demo` accounts, not funded ones. This README does not assert that the underlying accounts or the mail credential have been changed at the provider.

## What is not committed

Nothing here runs as-is, on purpose:

- **The six `.joblib` model files** (~2.5 MB each). Each is a pickled scikit-learn/XGBoost object graph. Loading a pickle executes code, they are unversioned against the library releases that produced them, and they carry no information a reader can inspect. Left as archive artefacts.
- **The twelve M15 OHLC CSVs** (~5 MB each, EURUSD/GBPUSD/XAUUSD/XAGUSD/USDCAD/AUDUSD at various dates). Broker data, large, and reproducible from `mt5.copy_rates_range`.
- **`final_test.ipynb`**, the cross-instrument evaluation from 2025-01-26. It is the first exhibit in `fx-ml-postmortem`, where its numbers are taken apart line by line, and duplicating it here would separate the claim from its refutation.

## Layout

```
lineage/    July - October 2024: broker connection to first self-running bot
bot/        November 2024 - February 2025: the production versions
training/   per-pair model notebooks that produce the .joblib files
.env.example
```

## Building

There is no build. These are Jupyter notebooks against a live MetaTrader 5 terminal on Windows, `pandas-ta`, `scikit-learn`, `xgboost`, `hmmlearn`, `selenium` with a Chrome driver, and `schedule`. `bot/config.py` and `bot/utils.py` must sit next to whichever bot notebook you open. Set the variables in `.env.example` in your environment first.

---

Read `fx-ml-postmortem` alongside this. The bot is the part that was built well; the postmortem is the part that establishes it was built well around nothing.

## Attribution

**`bot/config.py` and `bot/utils.py` are not mine.** They are taken essentially verbatim from
[fizahkhalid/forex_factory_calendar_news_scraper](https://github.com/fizahkhalid/forex_factory_calendar_news_scraper)
— `ALLOWED_ELEMENT_TYPES`, `EXCLUDED_ELEMENT_TYPES`, `ICON_COLOR_MAP`, `read_json`, `contains_day_or_month`
and `find_pattern_category` are that author's code, down to the comments. The repository was cloned onto my
drive in September 2024 with its `.git` intact and no local commits. The economic-news blackout in this bot
depends on them, so they are committed here rather than omitted, but the parsing work is not mine.

A second scraper, [AtaCanYmc/ForexFactoryScrapper](https://github.com/AtaCanYmc/ForexFactoryScrapper), was also
on the drive and is not used by this bot.

Everything else in `bot/`, `lineage/` and `training/` is my own.

