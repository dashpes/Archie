# Archie

Archie is a two-part system that runs in Docker on a home server.

- The **data service** collects market-wide data, labels news, and detects cross-source confluence.
- The **trading bot** reads that data and trades a cash-only Public.com account with deterministic rules. The bot is in rebuild. See `docs/` when it lands.

## What the data service collects

| Source | Data | Cadence |
|---|---|---|
| SEC EDGAR | Form 4 insider transactions, market-wide | Daily, 06:30 ET |
| SEC EDGAR | 8-K material events | Daily, 06:30 ET |
| Yahoo Finance | Daily OHLCV for insider-active names | Daily, 06:30 ET |
| Senate eFD | Senate trade disclosures | Daily, 06:30 ET |
| RSS | Market-wide headlines with cashtags | Hourly |
| Wikipedia | S&P 500 and Nasdaq-100 membership | Sunday, 05:00 ET |

After the daily collection, the service labels new headlines bullish, bearish, or neutral with a local LLM, then runs the confluence detector. Retention runs on Sunday at 04:00 ET.

## Install

1. Install Docker and Docker Compose on the server.
2. Clone the repository.
3. Copy `.env.example` to `.env` and set the values you need.
4. Copy `config/robo.yaml.example` to `config/robo.yaml` and `config/research.yaml.example` to `config/research.yaml`.
5. Build and start the data service:

```bash
docker compose build
docker compose up -d data
```

The `data/` directory must be on a local disk. SQLite in WAL mode is not safe on NFS, SMB, or CIFS.

### Optional: local LLM

The sentiment labeler uses Ollama. To run Ollama in the same compose project:

1. Set `OLLAMA_HOST=http://ollama:11434` in `.env`.
2. Start the profile: `docker compose --profile ollama up -d`.
3. Pull a model: `docker compose exec ollama ollama pull phi3:mini`.

Without Ollama, the `label` job leaves sentiment empty and the rest of the pipeline continues.

## Operate

Run a job by hand inside the container:

```bash
docker compose exec data investment-data collect --days-back 3
docker compose exec data investment-data label
docker compose exec data investment-data insights
docker compose exec data investment-data universe
docker compose exec data investment-data prune
```

Check the service:

```bash
docker compose ps                      # healthy = heartbeat under 5 minutes old
docker compose logs -f data
docker compose exec data investment-data health data 300
```

Research commands (discovery, top candidates, simulations) sit under `investment-data research --help`.

## How the scheduler works

- One process per container runs a loop with a 60 second tick.
- Each job is a CLI subcommand run as a subprocess with a timeout. A hung fetch is killed. A crash cannot stop the loop.
- Jobs run one at a time, in list order.
- Every attempt is recorded in the `job_runs` table. A job is due when no success exists since its most recent slot, so a missed slot is caught up at the next tick.
- After three consecutive failures of one job, the service sends an email.

## Configuration

Secrets and environment settings live in `.env`. See `.env.example` for each key.

| Key | Purpose |
|---|---|
| `SMTP_*`, `EMAIL_FROM`, `EMAIL_TO` | Email for trade confirmations and failures. Gmail needs an App Password. |
| `SEC_CONTACT_EMAIL` | Contact in the SEC EDGAR User-Agent. Set it to your email. |
| `OLLAMA_HOST` | Ollama endpoint for the sentiment labeler. |
| `PUBLIC_API_TOKEN` | Public.com API secret for the bot. |
| `ROBO_FORCE_DRY_RUN` | Kill switch. Keep `true` until you go live. |
| `RETENTION_*_DAYS` | Rows older than these windows are pruned. `0` keeps everything. |

Non-secret settings live in `config/robo.yaml` and `config/research.yaml`.

## Bot commands

The bot CLI is `investment-robo`. Until the bot pipeline lands, it offers account checks, status, P&L, pause and resume, a notification test, a backtest, and prune:

```bash
docker compose exec data investment-robo check-safety
docker compose exec data investment-robo status
docker compose exec data investment-robo notify-test
```

## Safety guarantees

These hold in code, not in configuration:

1. The bot refuses to run unless the account is a cash account with no margin.
2. The bot never moves money. No deposit, withdrawal, or transfer is wrapped.
3. The bot is long-only. A sell is capped at the held quantity.
4. Every order sends `useMargin=false`. Stop, option, and crypto order shapes are rejected.
5. A buy can never exceed settled cash. Sale proceeds are not reused in the same run.
6. Every order passes the guardrail gate, then the broker preflight, before placement.
7. Dry-run is the default, and `ROBO_FORCE_DRY_RUN` is an independent kill switch.
8. Every proposal, gate decision, preflight, and placement is appended to `logs/robo_audit.jsonl`.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[ai,robo,dev]"
pytest -q
ruff check src tests
```

## License

MIT
