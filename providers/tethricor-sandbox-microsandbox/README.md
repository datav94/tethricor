# tethricor-sandbox-microsandbox

A pluggable `SandboxProvider` for the Tethricor framework backed by
[microsandbox](https://github.com/superradcompany/microsandbox) — rootless, local-first
libkrun/KVM **microVM** isolation with an OpenAPI/MCP surface (Apache-2.0).

This is the **primary open-source** sandbox pick (FRAMEWORK_EVOLUTION §5.2): adopt, don't
build. Task code runs in an isolated microVM reached over REST, so the harness container
never executes code locally (`.cursorrules` #1).

## Install & select

```bash
pip install -e shim ./providers/tethricor-sandbox-microsandbox
```

Selection is by config or CLI flag — the provider is discovered automatically via the
`tethricor.sandboxes` entry point at `import tethricor`:

```yaml
runtime:
  provider: microsandbox     # there's no default provider; this is one explicit choice
  profile: python312
```

```bash
tethricor init --sandbox microsandbox ...
```

Endpoint/credentials are **platform-injected** via env (never in `harness.yaml`):

- `MICROSANDBOX_URL` (default `http://127.0.0.1:5555`)
- `MICROSANDBOX_API_KEY` (optional)

## Status & caveats

- microsandbox is **pre-1.0 (beta)** — the REST surface is pinned in `_provider.py`; a
  version bump is a one-file change. Verify against your server version.
- Real-backend E2E needs a KVM-capable host; CI conformance runs against a hermetic fake
  mirroring the pinned API (`tests/test_conformance.py`). Every provider must pass
  `tethricor_runtime.testing.assert_sandbox_conformance`.
