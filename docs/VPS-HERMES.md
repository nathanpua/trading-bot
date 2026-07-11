# Deploying on a VPS with Hermes Agent

This guide shows how to run the trading bot unattended on a VPS, with
[Hermes Agent](https://hermes-agent.nousresearch.com/) handling the
scheduled execution and delivering reports to your phone via Telegram.

This is the exact setup the bot was developed and runs with. The key idea:

```
 Trading Bot scripts ──► Hermes Cron ──► Telegram
 (~/trading-bot)         (--no-agent)     (your phone)
    │                                        ▲
    │  produce clean monospace tables         │ delivered verbatim
    └──────────────────────────────────────────┘
```

Hermes has a **`--no-agent` cron mode** that runs a shell script on a
schedule and delivers its stdout directly to a messaging channel — no LLM
tokens spent, no interpretation, just the script's output in your chat.
This is perfect for the bot's scripts, which already print clean,
mobile-formatted monospace tables and stay silent on error (empty stdout =
nothing sent).

---

## Prerequisites

| Component | What it is | Where to get it |
|-----------|-----------|-----------------|
| **Linux VPS** | Always-on server (Ubuntu/Debian) | Any cloud provider |
| **Hermes Agent** | AI agent framework with cron + gateway | [Install](https://hermes-agent.nousresearch.com/) |
| **Telegram bot token** | For Hermes to message you | [@BotFather](https://t.me/BotFather) |
| **Alpaca paper keys** | Broker + market data | [Alpaca](https://app.alpaca.markets/paper/dashboard/overview) |
| **Finnhub API key** | Quotes + news feed | [Finnhub](https://finnhub.io/register) |

---

## Step 1 — Install the Trading Bot

```bash
cd ~
git clone https://github.com/nathanpua/trading-bot.git
cd trading-bot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env   # add your ALPACA_API_KEY, ALPACA_SECRET_KEY, FINNHUB_API_KEY
```

Verify it works:

```bash
python autonomous_engine.py --phase report
```

You should see a portfolio snapshot with your paper account's equity and
positions.

---

## Step 2 — Install Hermes Agent

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes setup    # interactive: pick a model provider, set up the gateway
```

### Connect Telegram

```bash
hermes gateway setup    # choose Telegram, paste your bot token from @BotFather
```

Send any message to your Telegram bot, then in that chat run:

```
/sethome
```

This marks the chat as the "home channel" — scheduled jobs deliver here by
default.

### Install the gateway as a background service

```bash
hermes gateway install    # creates a systemd --user service
hermes gateway start
```

**Critical for VPS:** enable lingering so the gateway survives SSH logout:

```bash
sudo loginctl enable-linger $USER
```

Verify it's running:

```bash
hermes gateway status
```

---

## Step 3 — Create the Cron Wrapper Scripts

Hermes cron scripts live under `~/.hermes/scripts/`. Create thin wrappers
that activate the bot's venv and run the bot's scripts:

```bash
mkdir -p ~/.hermes/scripts

# ── Pre-market scan (9:00 AM ET) ──
cat > ~/.hermes/scripts/trading_premarket.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd ~/trading-bot
source .venv/bin/activate
python scripts/premarket_scan.py
EOF

# ── Autonomous trading cycle ──
cat > ~/.hermes/scripts/trading_cycle.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd ~/trading-bot
source .venv/bin/activate
python autonomous_engine.py --phase cycle --execute
EOF

# ── Daily P&L summary (4:00 PM ET) ──
cat > ~/.hermes/scripts/trading_eod.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd ~/trading-bot
source .venv/bin/activate
python scripts/daily_summary.py
EOF

chmod +x ~/.hermes/scripts/trading_*.sh
```

> **Why wrapper scripts?** Hermes cron runs scripts from
> `~/.hermes/scripts/`, but the bot lives in `~/trading-bot`. The wrappers
> bridge that gap by `cd`-ing into the bot dir and activating its venv.
> They also keep the bot repo self-contained — no Hermes-specific files
> inside it.

---

## Step 4 — Schedule the Cron Jobs

Create three scheduled jobs using Hermes's `--no-agent` mode. Each runs its
wrapper script on a cron schedule and delivers stdout to your Telegram chat.

```bash
# Pre-market scan — weekdays 9:00 AM ET (14:00 UTC)
hermes cron create "0 14 * * 1-5" \
  --name "Pre-market scan" \
  --script trading_premarket.sh \
  --no-agent

# Autonomous trading cycle — every 30 min during market hours (9:30–16:00 ET)
hermes cron create "*/30 14-20 * * 1-5" \
  --name "Trading cycle" \
  --script trading_cycle.sh \
  --no-agent

# End-of-day summary — weekdays 4:00 PM ET (21:00 UTC)
hermes cron create "0 21 * * 1-5" \
  --name "EOD summary" \
  --script trading_eod.sh \
  --no-agent
```

These deliver to the **home channel** (the Telegram chat where you ran
`/sethome`) by default.

**List your jobs:**

```bash
hermes cron list
```

---

## How the Delivery Works

| Setting | Effect |
|---------|--------|
| `--no-agent` | Skips the LLM entirely. The script's stdout is the message. |
| `--script X` | Runs `~/.hermes/scripts/X` on each tick. `.sh` → bash, `.py` → python. |
| (no `--deliver`) | Delivers to `origin` — the home channel where the job was created. |

**Silent-on-error is by design.** The bot's scripts (`premarket_scan.py`,
`daily_summary.py`) call `sys.exit(0)` on API errors, producing empty
stdout. Hermes treats empty stdout as "nothing to report" and sends
nothing — so a Finnhub outage at 3 AM won't spam your phone.

**The engine self-gates on market hours.** `trading_cycle.sh` always passes
`--execute`, but the engine checks `is_market_open()` internally: outside
market hours it reports only and places no orders. This makes the cron safe
to run any time.

---

## Step 5 — Verify

**Trigger a job manually** to confirm end-to-end delivery:

```bash
hermes cron run <job-id>     # find IDs with: hermes cron list
```

You should receive the script's output in Telegram within a minute.

**Check the scheduler is alive:**

```bash
hermes cron status
```

---

## Alternative: Agent-Mode Jobs (LLM Interpretation)

If you want Hermes to *interpret* the bot's output rather than pass it
through verbatim (e.g. "summarize today's scan and flag the top 2
setups"), drop `--no-agent` and provide a prompt instead:

```bash
hermes cron create "0 14 * * 1-5" \
  --name "Pre-market analysis" \
  --script trading_premarket.sh \
  "Read the pre-market scan output above. Rank the top 3 buy candidates \
   by conviction and explain the thesis for each in 2 sentences."
```

In this mode, the script's stdout is injected into the agent's prompt as
context, and the agent's response is what gets delivered. This costs LLM
tokens but produces richer analysis. The `--no-agent` mode (Step 4) is
recommended for routine scheduled runs — use agent mode for on-demand deep
dives.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No messages arriving | `hermes gateway status` — is the gateway running? |
| Gateway dies after SSH logout | `sudo loginctl enable-linger $USER` |
| "script not found" | Scripts must be under `~/.hermes/scripts/`, not `~/trading-bot/` |
| Job runs but nothing sent | Script produced empty stdout (silent on error) — run it manually to check |
| Market data errors | Verify `.env` keys: `python -c "import finnhub_client as f; print(f.get_quote('SPY'))"` |
| Alpaca 403 on recent bars | Normal on the free tier — the bot auto-sets `end = now - 1 day` to avoid this |

Check gateway logs for delivery errors:

```bash
grep -i "failed\|error" ~/.hermes/logs/gateway.log | tail -20
```

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────┐
│                    VPS (always-on)                    │
│                                                       │
│  ┌──────────────┐     ┌───────────────────────────┐  │
│  │  Hermes       │     │  Trading Bot               │  │
│  │  Gateway      │     │  (~/trading-bot)           │  │
│  │  (Telegram)   │     │                            │  │
│  │       ▲       │     │  autonomous_engine.py      │  │
│  │       │       │     │  scripts/premarket_scan.py │  │
│  │       │       │     │  scripts/daily_summary.py  │  │
│  │       │       │     └────────────┬──────────────┘  │
│  │       │       │                  │                  │
│  │  ┌────┴───────┴──────────────────┘                 │
│  │  │ Hermes Cron Scheduler                           │
│  │  │ (--no-agent: runs wrappers, delivers stdout)    │
│  │  └────────────────────────────────────┐            │
│  │                                       │            │
│  └───────────────────────────────────────┼────────────┘
│                                          │
└──────────────────────────────────────────┼─────────────┘
                                           │
                                    Alpaca / Finnhub APIs
                                           │
                                    📱 ← Telegram delivery
```

## Reference: Hermes Cron Commands

```bash
hermes cron list              # show all jobs
hermes cron create SCHED      # create (see flags above)
hermes cron edit ID           # modify schedule/prompt/delivery
hermes cron pause ID          # temporarily disable
hermes cron resume ID         # re-enable
hermes cron run ID            # trigger immediately
hermes cron remove ID         # delete
hermes cron status            # is the scheduler running?
```

Full cron docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/cron
