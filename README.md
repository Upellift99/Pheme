# Pheme

[![CI](https://github.com/Upellift99/Pheme/actions/workflows/ci.yml/badge.svg)](https://github.com/Upellift99/Pheme/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Docker image](https://img.shields.io/badge/ghcr.io-pheme-2496ED?logo=docker&logoColor=white)](https://github.com/Upellift99/Pheme/pkgs/container/pheme)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/Upellift99/Pheme/pulls)

A self-hosted bridge that relays SMS between a Huawei 4G CPE (HiLink API) and a
Matrix room. Incoming SMS are pushed into Matrix; messages typed in the Matrix
room can send SMS back out through the CPE's SIM.

It runs continuously as a Docker container on a Raspberry Pi (or any Linux host)
that has a network interface on the CPE's subnet (`192.168.8.0/24`).

> Tested against a B320-323 ("HUAWEI 4G CPE 5s"), firmware/WebUI 4.0.0.x. The
> HiLink API is shared across the Huawei B-series, so other B-series models
> should work too.

## How it works

Two independent async loops share one Huawei client and one SQLite store:

- **Inbound (SMS → Matrix):** every `POLL_INTERVAL` seconds the inbox is listed;
  any SMS never relayed before is pushed to Matrix and recorded. Dedup is keyed
  on the SMS `Index`, so nothing is relayed twice — even across restarts. By
  default the CPE state is left untouched (no mark-as-read, no delete).
- **Outbound (Matrix → SMS):** the Matrix `/sync` endpoint is long-polled for new
  room messages. Recognised commands send an SMS via the CPE, and a confirmation
  is posted back into the room. The bot ignores its own messages and only acts on
  messages received after startup (the sync token is persisted in SQLite).

A failure in one loop never stops the other, and a network/auth/Matrix error in a
cycle is logged and retried with exponential backoff rather than crashing.

## Command syntax (outbound)

Type these in the bridged Matrix room:

| Command | Action |
| --- | --- |
| `!sms <number> <text>` | Send `<text>` to `<number>`. |
| `!reply <text>` | Reply to the most recent inbound sender. |

Examples:

```
!sms +33612345678 Hello from the CPE
!reply on my way
```

- Unknown or malformed `!` commands get a short usage hint in the room.
- Plain (non-`!`) messages are ignored, so humans can chat freely in the room.
- Set `ALLOW_OUTBOUND=false` to make the bridge strictly read-only.

## Network prerequisites

The CPE's `192.168.8.0/24` network must be directly reachable from the host. The
typical setup is a **dual-network Raspberry Pi**:

- one interface on your main LAN (the Pi's normal route to the internet and your
  Matrix homeserver),
- a second interface on the CPE subnet, connected to the CPE (e.g. the CPE's LAN
  port or its Wi-Fi), with an address in `192.168.8.0/24`.

```
[ Matrix homeserver ] --- main LAN --- [ Raspberry Pi ] --- 192.168.8.0/24 --- [ Huawei CPE ]
                                          (Pheme)
```

Important routing notes:

- **Do not accept a default route from the CPE.** Mobile data may be off or
  metered — the Pi's outbound traffic must stay on the main LAN. Configure the
  CPE interface without a gateway (or with a lower-priority metric).
- With Docker's default bridge network, the container reaches `192.168.8.1`
  through the Pi's NAT with no special configuration. If routing to the CPE
  fails, uncomment `network_mode: host` in `docker-compose.yml` as a fallback.

## Getting a Matrix bot access token

1. Create a dedicated Matrix user for the bot (e.g. `@phemebot:example.org`).
2. Invite it to (and join it into) the room you want to bridge.
3. Obtain an access token for that user. The simplest way:

   ```bash
   curl -XPOST 'https://matrix.example.org/_matrix/client/v3/login' \
     -d '{"type":"m.login.password","identifier":{"type":"m.id.user","user":"phemebot"},"password":"THE_BOT_PASSWORD"}'
   ```

   The response's `access_token` field is your `MATRIX_TOKEN`, and its `user_id`
   field is your `MATRIX_USER_ID` (e.g. `@phemebot:example.org`).

4. Get the room's **internal ID** for `MATRIX_ROOM_ID` (it looks like
   `!abcd...:example.org`, not the human `#alias:example.org`). In Element:
   *Room → Settings → Advanced → Internal room ID*. Copy it verbatim.

> Do not log out that session afterwards, or the token will be invalidated.

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Description |
| --- | --- | --- |
| `HUAWEI_HOST` | `192.168.8.1` | CPE address. |
| `HUAWEI_USER` | `admin` | CPE web UI user. |
| `HUAWEI_PASSWORD` | _(required)_ | CPE web UI password. |
| `MATRIX_HOMESERVER` | _(required)_ | e.g. `https://matrix.example.org`. |
| `MATRIX_TOKEN` | _(required)_ | Bot access token. |
| `MATRIX_USER_ID` | _(required)_ | Bot user id, e.g. `@phemebot:example.org`. |
| `MATRIX_ROOM_ID` | _(required)_ | Room id, e.g. `!abcd...:example.org`. |
| `POLL_INTERVAL` | `60` | Seconds between inbox polls. |
| `STATE_DB` | `/data/state.db` | SQLite state file. |
| `MARK_AS_READ` | `false` | Mark relayed SMS as read on the CPE. |
| `DELETE_AFTER_RELAY` | `false` | Delete relayed SMS from the CPE. |
| `ALLOW_OUTBOUND` | `true` | Set `false` for a read-only bridge. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## Running

### Docker Compose (recommended)

```bash
cp .env.example .env
# edit .env with your CPE password, homeserver, token, user id and room id
mkdir -p ./data && chown -R 1000:1000 ./data
docker compose up -d --build
docker compose logs -f
```

State persists in `./data` (mounted at `/data`). The container runs as a
non-root user (uid 1000), so the bind-mounted `./data` must be writable by that
uid — hence the `chown` above. Skip it and SQLite fails at startup with
`unable to open database file`. (Alternatively, add `user: root` to the service
in `docker-compose.yml` to sidestep ownership entirely.)

The container exposes a healthcheck based on the CPE's `sms_count()` — the
container is reported healthy only while the CPE is reachable.

Prefer the prebuilt multi-arch image instead of building locally? Replace the
`build: .` line in `docker-compose.yml` with:

```yaml
    image: ghcr.io/upellift99/pheme:latest
```

The image is published to GHCR by CI for `linux/amd64`, `linux/arm64` and
`linux/arm/v7`, so it runs on a Raspberry Pi out of the box.

### Locally (development)

```bash
python -m venv venv
./venv/bin/pip install -e ".[dev]"
set -a; source .env; set +a
./venv/bin/python -m pheme
```

Run the tests and linter:

```bash
./venv/bin/pytest -q
./venv/bin/ruff check .
```

## A note on safety

A SIM number exposed this way will receive **smishing** (SMS phishing). Pheme is
deliberately manual: it **never auto-replies and never auto-clicks** anything.
Outbound SMS are only ever sent in response to an explicit `!sms` / `!reply`
command that a human typed in the room. Treat inbound links with the usual
caution.

## License

[MIT](LICENSE).
