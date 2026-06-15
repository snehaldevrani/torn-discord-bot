# Real-Time Market Surveillance & Alerting System

A high-throughput, asynchronous data pipeline that monitors marketplace activity across a large-scale online platform, detects high-value seller transactions in real time, and delivers enriched, actionable alerts to a Discord community.

---

## Overview

This system continuously polls a platform's official API alongside third-party data sources to identify sellers completing significant transactions, tracks their status over time, and surfaces time-sensitive opportunities to end users through a Discord bot. It is built around an asynchronous event pipeline — **discovery → detection → tracking → enrichment → alerting** — backed by a persistent SQLite data store, and is designed to run unattended on a low-resource cloud instance with self-healing operational characteristics.

**At a glance:**

- **2.4M+ API requests processed daily** (~80–100 GB of traffic)
- **99%+ uptime** on AWS EC2 via systemd process supervision and CloudWatch alarms
- **200+ daily active users** served through a Discord-based alerting interface
- Multi-source data enrichment with adaptive rate limiting and resilience against anti-bot protections

---

## Key Features

### High-Throughput Async Pipeline
- Fully asynchronous architecture (`asyncio` + `aiohttp`) sustaining millions of requests per day
- Rotating discovery scheduler samples the monitored catalog in batches across rolling time windows, balancing coverage against available API budget
- Configurable batch size, concurrency, and inter-batch delays to maintain throughput without tripping upstream rate limits

### Snapshot-Based Sale Detection
- Maintains per-seller inventory snapshots and diffs them on every polling cycle
- Detects partial sales, full delistings, and quantity/price changes
- Produces a normalized transaction record for every detected event, persisted to an audit log

### Configurable Target Tracking & Business Rule Engine
- Accumulates transaction value per seller into a running total used to prioritize alerts
- Multi-condition lifecycle management — sellers are actively tracked, escalated, or dropped based on live status signals (availability, location/state changes, recent activity)
- Region-aware value adjustments and resets driven by external status data
- Allowlist support for prioritized entities and denylist support for excluded entities
- Automatic cleanup of stale targets after a configurable inactivity window

### Real-Time, Enriched Discord Alerting
- Rich embed-based alerts including transaction history, time-since-last-activity, current status, and a secondary risk/strength estimate pulled from an enrichment API
- Smart channel routing — alerts can be split across channels based on enriched scoring thresholds
- One-click action buttons embedded directly in alert messages
- Slash-command interface for runtime administration (channel configuration, allowlists, thresholds, key registration)

### Resilient API Key Management
- Pooled, round-robin key rotation across administrator-provided and community-registered API keys
- Per-key rate-limit tracking with automatic cooldown and recovery
- Automatic detection and retirement of invalid or expired keys, with notifications sent to administrators and affected users
- Persistent key storage so the pool survives process restarts

### Operational Reliability
- Lightweight HTTP health-check endpoint reporting uptime, processing cycle count, and memory usage for external monitoring
- systemd-managed process lifecycle on AWS EC2
- CloudWatch alarms covering both service-level and instance-level health
- Structured, leveled logging throughout for observability and troubleshooting
- Persistent SQLite storage (via `aiosqlite`) for snapshots, tracked targets, alert history, transaction logs, and configuration

---

## Architecture

```
                         ┌────────────────────────────┐
                         │  Marketplace Data Aggregator │
                         │     (third-party API)        │
                         └──────────────┬───────────────┘
                                         │ rotating discovery batches
                                         ▼
┌─────────────────┐           ┌───────────────────────┐           ┌────────────────────────┐
│   Key Manager     │◄────────►│     Monitor Loop        │──────────►│     Sale Detector        │
│ (rotation, rate   │           │   (cycle orchestration) │           │ (per-seller snapshot     │
│  limiting, key     │           └───────────┬─────────────┘           │  diffing)                │
│  lifecycle)        │                       │                         └───────────┬──────────────┘
└─────────┬──────────┘                       ▼                                     │
          │                        ┌───────────────────────┐                       │
          └───────────────────────►│  Platform Profile API   │                     │
                                    │  Client (key-rotated)    │                     │
                                    └───────────┬─────────────┘                     │
                                                 │                                   │
                                                 ▼                                   ▼
                                       ┌─────────────────────────────────────────────────┐
                                       │              Target Tracker                       │
                                       │  (value accumulation + business rule engine)      │
                                       └──────────────────────┬────────────────────────────┘
                                                                ▼
                                                      ┌────────────────────┐
                                                      │      Alerter         │
                                                      │ (embed formatting,   │
                                                      │  risk enrichment)    │
                                                      └──────────┬───────────┘
                                                                 ▼
                                                      ┌────────────────────┐
                                                      │    Discord Bot       │
                                                      │ (alert delivery,     │
                                                      │  slash commands)     │
                                                      └────────────────────┘

         Persistent layer: SQLite (aiosqlite) — snapshots, tracked targets,
         alert/transaction logs, API key pool, channel & allowlist configuration
```

---

## Project Structure

```
.
├── main.py                      # Entry point: config load, DB init, health server, bot startup
├── config.yaml                  # Runtime configuration (catalog, thresholds, messaging)
├── core/
│   ├── monitor.py                # Orchestration loop & rotating discovery scheduler
│   ├── detector.py               # Snapshot-diffing sale detection
│   ├── tracker.py                # Target accumulation & business rule engine
│   └── alerter.py                # Alert formatting & delivery
├── api/
│   ├── platform_client.py        # Official platform API client (key-rotated)
│   ├── aggregator_client.py       # Third-party marketplace data aggregator client
│   ├── enrichment_client.py       # Third-party risk/stats enrichment client
│   └── key_manager.py             # API key pool, rotation, rate limiting, lifecycle
├── bot/
│   ├── discord_bot.py             # Bot lifecycle, events, monitoring task
│   └── commands.py                # Slash command implementations
├── database/
│   ├── db.py                      # Schema definition & connection management
│   └── models.py                  # Data access layer
└── utils/
    ├── formatters.py               # Currency/time formatting & embed construction
    ├── parsers.py                  # API response parsing & normalization
    └── logger.py                   # Centralized logging configuration
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language / Runtime | Python 3.11+, `asyncio` |
| HTTP clients | `aiohttp` (platform & internal APIs), `curl_cffi` with browser impersonation (anti-bot resilient client) |
| Bot framework | `discord.py` (slash commands, rich embeds, interactive views) |
| Database | SQLite via `aiosqlite` |
| Configuration | YAML + environment variables (`python-dotenv`) |
| Monitoring | Lightweight `aiohttp` health-check server, `psutil` |
| Deployment | AWS EC2, systemd, CloudWatch |

---

## Data Model

The persistence layer is a single SQLite database covering:

- **Snapshot state** — per-seller inventory snapshots used for diff-based sale detection
- **Tracked targets** — active monitoring state, accumulated transaction value, status flags, and travel/location metadata
- **Alert log** — full history of alerts sent, for analytics and de-duplication
- **Transaction log** — append-only audit trail of every detected sale
- **Dropped targets / dropped keys** — operational history for tuning and debugging
- **Configuration tables** — monitored catalog items, alert channel routing, filtered/secondary channel rules, allowlists, and the API key registry

Indexes are maintained on high-churn lookup paths (transaction history by seller, alert history by time and seller) to keep query latency low as the dataset grows.

---

## Setup & Deployment

### Prerequisites
- Python 3.11+
- A Discord application/bot token with the required intents enabled
- One or more API keys for the platform's official API

### Installation
```bash
git clone https://github.com/snehaldevrani/realtime-market-surveillance.git
cd realtime-market-surveillance
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Create a `.env` file with the following:
```
DISCORD_BOT_TOKEN=<your_bot_token>
ADMIN_DISCORD_ID=<your_discord_user_id>
PORT=8080
```

Define monitoring parameters in `config.yaml`, including the catalog of items to track, alert thresholds (minimum accumulated value, minimum inactivity period), status-based messaging, and any seeded allowlist/denylist entries.

### Running
```bash
python main.py
```

On startup, the application validates the environment, initializes the database schema, loads the API key pool, starts the health-check server, and connects the Discord bot — which in turn begins the monitoring loop.

### Production Deployment
The system is designed to run as a systemd-managed service on AWS EC2:
- A systemd unit ensures automatic restart on failure or instance reboot
- CloudWatch alarms monitor both system-level (instance) and application-level (process) health
- The built-in `/health` endpoint exposes uptime, monitoring cycle count, and memory usage for integration with external uptime checks

---

## Administration

Runtime configuration is managed through Discord slash commands, including:
- Alert channel configuration and secondary/filtered channel routing
- API key registration (for community-contributed key pools) and admin key management
- Allowlist and denylist management for tracked entities
- Rate limit and threshold tuning

---

## License

This project is provided for portfolio and demonstration purposes.
