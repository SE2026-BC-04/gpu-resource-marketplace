# VT-090 Status GET Load Experiment

`run-status-load.mjs` runs exactly 60 concurrent status GET tasks and writes the samples to `results-local.json`. The p95 uses nearest-rank: `sorted[ceil(0.95*n)-1]`, over successful HTTP response latencies. It records successful HTTP responses, HTTP errors, transport errors, and every outcome.

## Default: safe mock mode

From the repository root:

```powershell
& 'D:\Application\node.exe' docs/coursework/vt-090/performance/run-status-load.mjs
```

This starts an in-process HTTP mock bound to `127.0.0.1` on an ephemeral port. It returns one fixed `QUEUED` DTO and delays each reply by 1 ms to make concurrency observable. The report label is `SIMULATED_ONLY`; its p95 is not an application or production result.

## Optional local API mode

This sends only GET requests to a loopback address. Use a retained disposable test Job and an authorized Client token. Never point it at a production host or a shared database. The script rejects non-loopback hosts and does not write the token to the output file.

```powershell
$env:VT090_MODE = 'real'
$env:VT090_ALLOW_REAL_READ_LOAD = 'YES'
$env:VT090_BASE_URL = 'http://127.0.0.1:8000'
$env:VT090_JOB_ID = '<retained disposable test Job UUIDv4>'
$env:VT090_BEARER_TOKEN = '<authorized Client token>'
& 'D:\Application\node.exe' docs/coursework/vt-090/performance/run-status-load.mjs
Remove-Item Env:VT090_MODE,Env:VT090_ALLOW_REAL_READ_LOAD,Env:VT090_BASE_URL,Env:VT090_JOB_ID,Env:VT090_BEARER_TOKEN
```

Real mode has not been run for this coursework. The harness cannot establish whether the API's configured database is disposable; the operator must verify that before setting the explicit allow flag. It reports `API_DATABASE_NOT_INSPECTED` and is not the full ADR-007 736-VU campaign.
