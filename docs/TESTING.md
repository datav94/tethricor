# Testing Tethricor — How-To Guide

This guide covers three levels of testing:

1. **Test the tool** — the fast Python test suite (CLI, schema, generators, webhook, shim, mocks).
2. **Test the full local stack** — a complete, self-contained `docker compose` bundle that
   runs the whole flow offline and proves **code-IN / code-OUT**.
3. **Test a generated / real harness later** — how to point the same stack at a bundle
   produced by `tethricor local-dev`, or at a real hardened harness image.

---

## 1. Test the tool (pytest)

No containers required. Run the whole suite from the repo root:

```bash
python -m pytest cli/tests webhook/test_app.py local-dev/test_mock_sandbox.py shim/tests tests -q
```

What each group covers:

| Suite | Verifies |
|---|---|
| `cli/tests` | schema contract, example validity, profile mapping, image resolution, generators, escape-hatch stripping |
| `local-dev/test_mock_sandbox.py` | the sandbox runtime double: sessions, async exec, live SSE, artifact zip |
| `webhook/test_app.py` | admission logic: sidecar injection, locked security context, opt-in identity federation, denials |
| `shim/tests` | the exec shim end-to-end against a live mock (clone → exec → SSE → zip → delete) |
| `tests/` | cross-cutting security invariants (egress default-deny, no in-container exec, memory refusal) |

---

## 2. Test the full local stack (self-contained)

The repo ships a complete offline stack at [`docker-compose.test.yaml`](../docker-compose.test.yaml).
It builds everything from source — **no private registry needed**.

### 2.1 What's in it

| Service | Role | Port | Source |
|---|---|---|---|
| `mock-gateway` | OpenAI-compatible **LLM gateway** double (echoes prompts) | 8081 | `local-dev/mock_gateway.py` |
| `mock-mcp` | minimal **MCP** double (dummy tools) | 9090 | `local-dev/mock_mcp.py` |
| `mock-sandbox` | **sandbox runtime** double (sessions/exec/SSE/artifacts) | 8080 | `local-dev/mock_sandbox.py` |
| `harness` | the **exec shim** (local test image); runs one demo task and exits | – | `docker/Dockerfile.harness-local` |

The demo flow:

```
harness (shim) --exec--> mock-sandbox  --clone /samples/demo         (code IN)
                                       --run task, produce changes
               <--zip--- mock-sandbox  --changes.zip -> ./test-harness/out (code OUT)
```

The `harness` task appends a line to `README.md` and creates `GENERATED.txt` **inside the
cloned repo in the sandbox session** — it never runs in the harness container itself.

### 2.2 Run it

```bash
docker compose -f docker-compose.test.yaml up --build
```

You'll see the shim stream the task's stdout (`harness task complete`) and log
`[artifact] wrote /out/changes.zip`. The `harness` service then exits (this is expected;
it is a one-shot task runner). The mocks keep running until you stop them.

### 2.3 Inspect the result (code-OUT)

```bash
# The zip of changed files produced by the task:
unzip -l test-harness/out/changes.zip
# Expect: README.md (modified) and GENERATED.txt (new)
```

### 2.4 Poke the mocks directly (optional)

```bash
# sandbox runtime double
curl localhost:8080/healthz
curl localhost:8080/v1/profiles

# LLM gateway double (OpenAI-compatible)
curl localhost:8081/v1/models
curl -s localhost:8081/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"gpt-4o-standard","messages":[{"role":"user","content":"ping"}]}'

# MCP double
curl localhost:9090/tools
```

### 2.5 Re-run the task / tear down

```bash
docker compose -f docker-compose.test.yaml up --build harness   # re-run just the demo task
docker compose -f docker-compose.test.yaml down -v              # stop and clean up
```

> **Security note:** `Dockerfile.harness-local` is a **test-only** image that packages
> just the shim (no real harness binary) and skips production hardening. The images that
> deploy for real are `docker/Dockerfile.*-hardened` — non-root, read-only rootfs, no
> baked provider keys. The shim still forwards **all** execution to the sandbox runtime here.

---

## 3. Test a generated harness bundle

`tethricor local-dev --target local` emits a `docker-compose.yaml` that wires your
app + the hardened harness sidecar + the three mocks:

```bash
tethricor init --yes --type hermes --version 0.17.0 \
  --repo-url /samples/demo --runtime-profile python312 --sandbox remote-runtime
tethricor local-dev harness.yaml --target local --out-dir tethricor-out
cat tethricor-out/local/docker-compose.yaml
```

The generated `harness-sidecar` uses the **hardened image resolved from the platform
manifest** (e.g. `ghcr.io/your-org/tethricor/hermes-hardened:0.17.0` — replace the
placeholder registry in `cli/tethricor_cli/data/image-manifest.yaml` with your own).
To run that bundle fully locally you need that image available — either:

- **pull/push** the hardened image to a registry your Docker can reach, **or**
- **build it locally first** and retag, e.g.:

  ```bash
  docker build -f docker/Dockerfile.hermes-hardened -t ghcr.io/your-org/tethricor/hermes-hardened:0.17.0 .
  docker compose -f tethricor-out/local/docker-compose.yaml up
  ```

If you only want to validate the **flow** (not a specific harness), prefer the
self-contained stack in section 2 — it builds the sidecar from source.

A harness type with no manifest entry at all (e.g. one you registered yourself via
`register_harness`) needs `tethricor local-dev ... --image <your-image>` instead of
relying on manifest resolution.

---

## 4. Test a real harness later

When you want to exercise an actual harness (Hermes, Pi, OpenHands, Goose, OpenCode)
instead of the shim-only test image, extend the self-contained stack:

1. **Swap the `harness` build** in `docker-compose.test.yaml` to a hardened Dockerfile:

   ```yaml
   harness:
     build:
       context: .
       dockerfile: docker/Dockerfile.hermes-hardened    # or .pi / .openhands / .goose / .opencode
   ```

2. **Point `harness.yaml`** (`test-harness/harness.yaml`) at your source repo and harness:
   set `harness.type`, `harness.version`, `runtime.profile`, `runtime.provider`, and
   `source.repo_url`. For a remote repo, use a real URL the `mock-sandbox` container can
   reach (and remove the git-seed `command:` override on `mock-sandbox`).

3. **Set the task** the harness should run via the `harness` service `command:` (everything
   after `--` is forwarded to the sandbox runtime session).

4. **LLM/MCP routing** is already wired to the mocks via `TETHRICOR_GATEWAY_URL` / `TETHRICOR_MCP_URL`.
   The shim adapter scrubs any direct provider keys and forces gateway routing, so the
   harness cannot bypass the gateway even if you set provider keys in the environment.

5. **The harness's own toolchain must be in the sandbox profile it runs under.** The
   mock-sandbox's `python312`/`node20`/`rust` profiles are bare language images, not
   harness-specific — if your hardened harness image forwards a command like
   `hermes run --task ...`, that binary needs to actually be reachable wherever the
   sandbox session executes it. This is a known gap, not something Tethricor
   provisions for you yet (see `docs/FRAMEWORK_GUIDE.md` §13).

What stays guaranteed regardless of harness:

- **No local execution:** the shim forwards every command to the sandbox runtime; the harness
  container never runs task code/bash directly (`.cursorrules` #1).
- **Gateway-only LLM/MCP:** provider keys are scrubbed; traffic goes to your configured LLM gateway
  (`.cursorrules` #2).
- **Code IN via clone, code OUT via zip:** no git write-back.

---

## Reference: shim environment variables

| Variable | Meaning |
|---|---|
| `TETHRICOR_HARNESS_TYPE` | harness type (selects the adapter) |
| `TETHRICOR_CONFIG_PATH` | path to the mounted `harness.yaml` |
| `TETHRICOR_RUNTIME_URL` | sandbox runtime base URL |
| `TETHRICOR_GATEWAY_URL` | LLM gateway base URL (LLM routing) |
| `TETHRICOR_MCP_URL` | MCP endpoint |

Run `python -m tethricor_runtime` (no args) inside the harness image to print the resolved
settings and security posture without running a task.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `harness` exits immediately with code 0 | Expected — it's a one-shot task runner. Check `test-harness/out/changes.zip`. |
| `changes.zip` empty | The task didn't modify files, or `source.repo_url` didn't clone. Check `mock-sandbox` logs for `cloneError`. |
| `harness` can't reach a service | Ensure you used `-f docker-compose.test.yaml`; services talk over the `tethricor` network by name. |
| Permission denied writing `/out` | On Linux, `chmod 777 test-harness/out` (the test image writes as its container user). |
| Generated bundle fails to pull image | See section 3 — build the hardened image locally or push it to a reachable registry. |
| `tethricor init` fails with "--sandbox is required" | There's no default sandbox provider. Pass `--sandbox remote-runtime` for local dev (or `microsandbox`/`e2b` if installed). |
