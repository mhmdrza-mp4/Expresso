# Expresso ☕

Expresso tests ExpressVPN servers for you, one by one, and stays connected to the first one that works.

## Demo

![Expresso demo](docs/demo.gif)

## Features

- **Auto Scan & Hold:** Tries servers sequentially and stays connected to the first working location.
- **One-Click Launcher (`launch.py`):**
  - **Instant Toggle:** If already connected, disconnects immediately and exits without loading heavy modules.
  - **Auto-Start & Auto-Close:** If disconnected, opens ExpressVPN if needed, waits for its CLI, runs Expresso, and automatically closes the terminal window 5 seconds after connecting.
- **Quality Check:** After a server connects, measures latency and download speed through the tunnel. Weak servers (by default slower than 300 ms or 2 Mbps) are skipped and the next one is tried, so you don't end up on a far-away server that technically works but crawls. The check uses two public endpoints (`gstatic.com` and `speed.cloudflare.com`), adds about 1-2 seconds, and switches itself off for the run after 6 rejections in case your own connection is the slow part.
- **Smart Ranking & Weighted Random Order:** Remembers every attempt in SQLite (`~/.expresso/history.db`), including latency and speed. Servers are tried in a weighted random order: fast, reliable ones usually come first, but the pick stays random and unknown servers still get a chance. Failing servers are benched with an exponential cool-down.
- **Fast-Path:** Sometimes (50% by default) retries the last good server first, which skips listing all locations. A server that was weak last time is never used for this.
- **Optional Traffic Verification:** Set `VERIFY_TRAFFIC = True` to probe multiple HTTPS endpoints and verify that your public IP changes before accepting a connection.
- **Animated Terminal UI:** Built with [rich](https://github.com/Textualize/rich), featuring a live tunnel animation, stage timers, activity log, and server leaderboard.

## Requirements

- Python 3.9+
- The ExpressVPN app installed, with its command-line tool available (`expressvpnctl` or `expressvpn`)
- `rich`

```bash
pip install rich
```

## Usage

### 1. One-Click Launcher (Recommended for shortcuts)

```bash
python launch.py
```

- **When connected:** Disconnects right away and exits.
- **When disconnected:** Starts ExpressVPN if necessary, runs the scanner, and closes the window automatically once the tunnel is stable.

### 2. Direct Scanner

```bash
python expresso.py                  # scan and connect
python expresso.py --demo           # preview the UI, no ExpressVPN needed
python expresso.py --reset-history  # forget what it has learned
```

Press `Ctrl+C` while scanning to stop and clean up any half-open tunnel. Once connected, pressing `Ctrl+C` closes the window while leaving the VPN connected.

## How it works

![How Expresso works](docs/diagram.svg)

1. **Preflight Check:** Checks the current VPN state (disconnects and exits if already connected via `launch.py`).
2. **History & Ranking:** Sometimes tries the last known good server first, otherwise loads all locations and puts them in a weighted random order based on past success rates, measured speed, and cool-down streaks.
3. **Probe Pipeline:** For each candidate, runs **Reset** -> **Connect** -> **Handshake** -> **Verify**, where Verify measures latency and speed (and, if enabled, checks real HTTPS traffic and that your IP changed).
4. **Result & Loop:** Stops at the first server that passes. Every attempt, including servers rejected for being too slow, is logged to `~/.expresso/history.db`. If all servers in the queue fail, Expresso pauses for 30 seconds before starting the next round.

## Settings

Fine-tune behavior by editing the constants in `config.py`:

| Constant | Default | Description |
| :--- | :--- | :--- |
| `VERIFY_TRAFFIC` | `False` | Require real HTTPS traffic and IP change through the tunnel |
| `QUALITY_CHECK` | `True` | Measure latency and speed after connecting and skip weak servers |
| `QUALITY_MAX_LATENCY_MS` | `300` | Servers with a higher round-trip latency are rejected |
| `QUALITY_MIN_MBPS` | `2.0` | Servers with a lower download speed are rejected (short test, keep it low) |
| `QUALITY_MAX_REJECTS` | `6` | Rejections after which the quality check is switched off for this run |
| `PICK_SHARPNESS` | `5.0` | How strongly the ranking steers the random order (0 = pure random, higher = more greedy) |
| `FAST_PATH_CHANCE` | `0.5` | Chance to retry the last good server first |
| `CONNECT_WAIT` | `8.5` | Max seconds to wait for the `connected` handshake |
| `MANUAL_LOCATIONS` | `[]` | Custom list of locations to test instead of all regions |
| `BENCH_AFTER` | `2` | Consecutive failures before a server is put on hold ("resting") |
| `BENCH_BASE_MIN` | `10` | Initial cool-down in minutes (doubles on each extra failure) |
| `ROUND_PAUSE` | `30` | Pause in seconds between full rounds when every server fails |
| `CLOSE_AFTER` | `5` | Seconds to keep the window open after connecting |
| `READY_TIMEOUT` | `60` | Max seconds to wait for the ExpressVPN service to start |

## Disclaimer

Expresso is an unofficial, independent tool. It is not affiliated with or endorsed by ExpressVPN. Use it at your own risk.