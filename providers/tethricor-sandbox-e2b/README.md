# tethricor-sandbox-e2b

A pluggable `SandboxProvider` for the Tethricor framework backed by
[E2B](https://github.com/e2b-dev/E2B) — Firecracker **microVM** sandboxes with excellent
DX (Apache-2.0). This is the **developer/managed** pick (FRAMEWORK_EVOLUTION §5.2):
adopt, don't build. Task code runs in an E2B microVM reached over the SDK — never in the
harness container (`.cursorrules` #1).

## Install & select

```bash
pip install -e shim "./providers/tethricor-sandbox-e2b[sdk]"   # [sdk] pulls the e2b SDK
```

Discovered automatically via the `tethricor.sandboxes` entry point at `import tethricor`:

```yaml
runtime:
  provider: e2b
  profile: python312          # maps to an E2B template
```

```bash
tethricor init --sandbox e2b ...
```

Credentials are **platform-injected** via `E2B_API_KEY` (never in `harness.yaml`).

## Architecture

The provider is a thin SandboxProvider shell over an `E2BSandboxClient` **seam**. The
real binding (`_sdk.py`) wraps the `e2b` SDK and is imported lazily; CI conformance runs
against a fake seam (`tests/`), so the contract translation is verified without keys.

## Status & caveats

- **Azure gap:** E2B self-host infra does not officially target Azure — use managed E2B
  or GCP/AWS self-host for dev/CI; **not** for on-prem Azure prod. Prefer `microsandbox`
  or `remote-runtime` pointed at your own service there.
- Must pass `tethricor_runtime.testing.assert_sandbox_conformance` (it does; see `tests/`).
