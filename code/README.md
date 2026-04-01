# easytodo
A minimal Django ToDo API for benchmarking.

## Quick start (Docker)

1. Build and run:

```bash
docker compose up --build
```

2. Import sample data (in another terminal):

```bash
docker compose run --rm web python manage.py import_sample_data
```

The app is available at `http://localhost:8080`.

## Endpoints

- `POST /login`
  - Body: `username`, `password` (form or JSON)
- `POST /logout`
- `POST /createToDo`
  - Body: `title`, `text`, `file` (multipart for file uploads)
- `POST /done`
  - Body: `id` or `todo_id`, optional `done` (true/false)
- `GET /getToDos`
- `POST /ai`
  - Body: `prompt`, optional `model`, optional `num_predict`, optional `seed`, optional `temperature`
  - Response JSON: `{"ok": true, "content": "...", "prompt_tokens": 12, "generated_tokens": 34}`
  - Response header: `X-Prompt-Tokens`
  - Response header: `X-Generated-Tokens`

All endpoints return JSON. `/createToDo`, `/done`, `/getToDos`, and `/deleteAllToDos` require an authenticated session.

## Nginx energy/carbon headers

Nginx reads per-route models from `url_energy.json` and adds response headers on every request.

Formula used:

```text
operational_gCO2eq = energy * grid_intensity
embodied_gCO2eq = embodied_rate * request_time_seconds
total_gCO2eq = operational_gCO2eq + embodied_gCO2eq
```

Supported `energy_model.kind` values:
- `constant`
- `linear`
- `curve` (piecewise linear interpolation with `linear_tail` or `clamp` extrapolation)

Response headers:
- `X-Energy-Value`
- `X-Grid-Intensity`
- `X-Embodied-gCO2eq`
- `X-Operational-gCO2eq`
- `X-Request-Carbon-gCO2eq`
- `X-Request-Time-Sec`
- `X-Data-Size-Bytes`

## Benchmark scripts

Shell scripts in `scripts/` call each endpoint `n` times (1..100000). Examples:

```bash
./scripts/login_bench.sh -n 1000 -u testuser -p testuser
./scripts/create_todo_bench.sh -n 500 -u testuser -p testuser -t 2000 -f 1048576
./scripts/get_todos_bench.sh -n 1000 -u testuser -p testuser
./scripts/ai_bench.sh -n 20 -s mixed
./scripts/ai_bench.sh -n 20 -s medium
./scripts/ai_bench.sh -n 20 -s very-long -b http://nginx
./scripts/ai_bench.sh -n 20 -s mixed -g 128 -r 7 -T 0
./scripts/done_bench.sh -u testuser -p testuser -n 1
./scripts/logout_bench.sh -n 1000
```

`ai_bench.sh` supports `very-short`, `short`, `medium`, `long`, `very-long`, and `mixed`. It prints one line per request with the prompt profile and the prompt/generated token counts returned by `/ai`. By default it also fixes `num_predict=128`, `seed=7`, and `temperature=0` so prompt-length experiments are less affected by response-length drift. The default `mixed` profile cycles through all five prompt lengths so the token counts differ within a single run.

`clickthrough_bench.sh` repeats a full user path instead of a single endpoint batch: login, delete all todos, create one todo, fetch todos, mark the created todo done, fetch todos again, optionally call `/ai`, then logout. This is useful for comparing a measured whole-session benchmark against an offline estimate derived from nginx access logs.

## Offline estimation from nginx logs

The no-header nginx setup writes structured JSON-lines access logs to `code/logs/easytodo_access.jsonl`. These logs include the request path, request time, byte counts, and AI token headers so the registry can be replayed offline.

Example:

```bash
python3 code/scripts/calculate_nginx_log_energy.py code/logs/easytodo_access.jsonl --registry url_energy_no_headers.json
```

## Green Metrics Tool

The usage scenario file is `usage_scenario.yml`. It uses a dedicated benchmark container (`bench`) and runs each script as a flow step.

For estimate-validation experiments, use `usage_scenario_clickthrough_no_header.yml`. It clears the nginx access log and then runs the repeated click-through script without the disclosure headers enabled.


## Sample data

Default sample user:
- Username: `testuser`
- Password: `testuser`

The sample importer reads `sample_data.json` by default. You can point it at another file with:

```bash
python manage.py import_sample_data --path path/to/your.json
```
