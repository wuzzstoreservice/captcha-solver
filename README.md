# Captcha Solver

Self-hosted CAPTCHA solver API. **MVP: Cloudflare Turnstile only.**

Built for local bots/automation (bind `127.0.0.1` by default). Compatible with the legacy Turnstile API used by projects like `grok-register-web`:

- `GET /turnstile?url=...&sitekey=...` → `{ "errorId": 0, "taskId": "..." }`
- `GET /result?id=...` → `{ "status": "processing" }` or `{ "status": "ready", "solution": { "token": "..." } }`

Also provides a versioned API:

- `POST /v1/task`
- `GET /v1/task/{id}`
- `GET /health`
- OpenAPI: `/docs`

## Requirements

- Linux VPS / desktop
- Python 3.11+
- RAM: ~1 GB free recommended for 1× Camoufox worker
- Camoufox browser (`python -m camoufox fetch`)

## Install

```bash
git clone https://github.com/wuzzstoreservice/captcha-solver.git
cd captcha-solver
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-browser.txt
python -m camoufox fetch
cp config.example.yaml config.yaml
```

### Dev / mock mode (no browser)

```bash
export CAPTCHA_SOLVER_MOCK_SOLVER=true
uvicorn app.main:app --host 127.0.0.1 --port 5080
```

### Production (real Camoufox)

```bash
uvicorn app.main:app --host 127.0.0.1 --port 5080
# or systemd:
sudo cp systemd/captcha-solver.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now captcha-solver
curl -s http://127.0.0.1:5080/health
```

## Config

Environment variables (prefix `CAPTCHA_SOLVER_`):

| Variable | Default | Notes |
|---|---|---|
| `HOST` | `127.0.0.1` | keep localhost |
| `PORT` | `5080` | parallel to older `:5072` solvers |
| `THREAD` | `1` | browser pool size |
| `HEADLESS` | `true` | |
| `DEBUG` | `false` | |
| `MOCK_SOLVER` | `false` | unit tests / CI |
| `BROWSER_RECYCLE_EVERY` | `50` | recycle Camoufox after N uses (0=off) |
| `SOLVE_TIMEOUT_SECONDS` | `120` | |
| `MAX_QUEUE` | `20` | 429 when full |

Optional `config.yaml` (see `config.example.yaml`). Optional `proxies.txt` (one proxy per line) when task has no `proxy`.

## Metrics

```bash
curl -s http://127.0.0.1:5080/metrics
```

Returns queue depth, success/fail counters, latency p50/p95, browser recycle count, and per-solver stats.

## PM2

```bash
pm2 start ecosystem.config.cjs
pm2 logs captcha-solver
pm2 restart captcha-solver
```

Systemd unit under `systemd/` is optional; this host prefers PM2.

## Usage

### Legacy curl

```bash
curl -sG 'http://127.0.0.1:5080/turnstile' \
  --data-urlencode 'url=https://example.com' \
  --data-urlencode 'sitekey=0x4AAAA...'

curl -s 'http://127.0.0.1:5080/result?id=TASK_ID'
```

### v1 JSON

```bash
curl -s http://127.0.0.1:5080/v1/task \
  -H 'content-type: application/json' \
  -d '{"type":"turnstile","url":"https://example.com","sitekey":"0x4AAAA..."}'
```

### Python client

```python
from client.captcha_client import CaptchaClient

c = CaptchaClient("http://127.0.0.1:5080")
token = c.solve_turnstile(
    "https://example.com",
    "0x4AAAA...",
    proxy="http://user:pass@host:port",  # optional
)
print(token)
```

## Tests

```bash
source .venv/bin/activate
export CAPTCHA_SOLVER_MOCK_SOLVER=true
pytest -q
```

## Smoke

```bash
chmod +x scripts/smoke_turnstile.sh
./scripts/smoke_turnstile.sh
SMOKE_SITEKEY=0x4AAAA... ./scripts/smoke_turnstile.sh
```

## Security

- Default bind is **localhost only**. Do not expose publicly without reverse-proxy auth.
- Do not log full proxy credentials (client should treat them as secrets).
- Systemd unit sets `MemoryMax=1500M` for small VPS.

## Roadmap (later)

- `cf_clearance`
- reCAPTCHA v3
- AWS WAF
- API key auth
- OCR / image captcha

## License

MIT
