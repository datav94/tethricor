"""Phase 6 — end-to-end + security verification.

Cross-cutting tests that tie the whole thin-abstraction stack together (CLI ->
generators -> mutating webhook -> shim -> mock agent-runtime) and assert the
platform-locked security invariants from IMPLEMENTATION_PLAN.md §"Cross-cutting
invariants" and .cursorrules #1/#2:

  1. local happy path: init -> validate -> local-dev; then a real task cloned in and
     changed files returned as a zip (code IN/OUT) via the runtime contract.
  2. egress default-deny: only {AgentGateway, agent-runtime} reachable.
  3. no execution path runs inside the harness container (shim forwards everything).
  4. the runtime `memory` provider is refused, and the local-only Azure OpenAI escape
     hatch is stripped, for non-local targets.
  5. aks/aci/job happy paths resolve the hardened image, mount identity, and (for aks)
     get a locked security context injected by the webhook.
"""
from __future__ import annotations

import io
import pathlib
import socket
import subprocess
import sys
import threading
import time
import zipfile

import yaml
import pytest
import uvicorn
from typer.testing import CliRunner

_ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("cli", "shim", "local-dev", "webhook"):
    sys.path.insert(0, str(_ROOT / sub))

from tethricor_cli import generators, manifest, security  # noqa: E402
from tethricor_cli.cli import app as cli_app  # noqa: E402
from tethricor_runtime.config import Settings  # noqa: E402
from tethricor_runtime.orchestrator import run_task  # noqa: E402
from mock_sandbox import app as mock_app  # noqa: E402
import app as webhook  # noqa: E402  (webhook/app.py)

runner = CliRunner()


# --------------------------------------------------------------------------
# live mock agent-runtime
# --------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(mock_app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "mock-sandbox did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _git_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    import os

    repo = tmp_path / "srcrepo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True, env=env)
    return repo


# --------------------------------------------------------------------------
# 1. local happy path
# --------------------------------------------------------------------------
def test_cli_init_validate_localdev(tmp_path):
    cfg = tmp_path / "harness.yaml"
    r = runner.invoke(cli_app, [
        "init", "--yes", "--type", "hermes", "--version", "0.17.0",
        "--repo-url", "https://example.test/repo.git", "--sandbox", "remote-runtime", "--out", str(cfg),
    ])
    assert r.exit_code == 0, r.output
    assert cfg.is_file()

    r = runner.invoke(cli_app, ["validate", str(cfg)])
    assert r.exit_code == 0, r.output

    out_dir = tmp_path / "out"
    r = runner.invoke(cli_app, ["local-dev", str(cfg), "--target", "local", "--out-dir", str(out_dir)])
    assert r.exit_code == 0, r.output

    compose = yaml.safe_load((out_dir / "local" / "docker-compose.yaml").read_text())
    sidecar = compose["services"]["harness-sidecar"]
    assert sidecar["image"] == "ghcr.io/your-org/tethricor/hermes-hardened:0.17.0"
    assert sidecar["read_only"] is True
    assert sidecar["user"] == "1001"
    assert sidecar["cap_drop"] == ["ALL"]
    assert {"mock-sandbox", "mock-mcp"} <= set(compose["services"])


def test_local_code_in_and_out(base_url, tmp_path):
    repo = _git_repo(tmp_path)
    cfg_path = tmp_path / "harness.yaml"
    r = runner.invoke(cli_app, [
        "init", "--yes", "--type", "hermes", "--version", "0.17.0",
        "--repo-url", str(repo), "--runtime-profile", "python312", "--sandbox", "remote-runtime",
        "--timeout-seconds", "60", "--out", str(cfg_path),
    ])
    assert r.exit_code == 0, r.output

    config = yaml.safe_load(cfg_path.read_text())
    settings = Settings(
        harness_type=config["harness"]["type"],
        runtime_url=base_url,
        gateway_url="http://gw:8080",
        mcp_url="http://gw:8080/mcp",
        config=config,
    )

    out_zip = tmp_path / "changes.zip"
    script = "open('created_by_task.txt','w').write('x'); print('ok')"
    result = run_task(settings, [sys.executable, "-c", script], output_path=str(out_zip))

    assert result.exit_code == 0
    with zipfile.ZipFile(io.BytesIO(out_zip.read_bytes())) as zf:
        assert "created_by_task.txt" in zf.namelist()  # code OUT


# --------------------------------------------------------------------------
# 2. egress default-deny
# --------------------------------------------------------------------------
def _aks_docs():
    image = "ghcr.io/your-org/tethricor/hermes-hardened:0.17.0"
    config = {"harness": {"type": "hermes", "version": "0.17.0"}, "runtime": {"profile": "python312"}}
    files = generators.GENERATORS["aks"](config, image)
    return list(yaml.safe_load_all(files["aks-manifests.yaml"]))


def _k8s_docs():
    image = "ghcr.io/your-org/tethricor/hermes-hardened:0.17.0"
    config = {"harness": {"type": "hermes", "version": "0.17.0"}, "runtime": {"profile": "python312"}}
    files = generators.GENERATORS["k8s"](config, image)
    return list(yaml.safe_load_all(files["k8s-manifests.yaml"]))


def test_egress_default_deny_only_gateway_and_runtime():
    netpol = next(d for d in _aks_docs() if d["kind"] == "NetworkPolicy")
    assert netpol["spec"]["policyTypes"] == ["Egress"]
    egress = netpol["spec"]["egress"]

    # First rule: only the two platform services (by label selector).
    services = {
        peer["podSelector"]["matchLabels"]["tethricor.internal/service"]
        for peer in egress[0]["to"]
    }
    assert services == {"agentgateway", "agent-runtime"}

    # No allow-all rule (an empty `to`/`{}` would defeat default-deny).
    for rule in egress:
        for peer in rule["to"]:
            assert peer != {}, "allow-all egress peer defeats default-deny"
    # Only DNS is additionally permitted (port 53).
    dns_rule = egress[1]
    assert {p["port"] for p in dns_rule["ports"]} == {53}


def test_k8s_target_has_identical_egress_security_and_no_azure_annotation():
    """The cloud-neutral k8s target must get the same egress default-deny posture as
    aks, but must NOT default to Azure identity federation (identity-mode=none)."""
    docs = _k8s_docs()
    netpol = next(d for d in docs if d["kind"] == "NetworkPolicy")
    services = {
        peer["podSelector"]["matchLabels"]["tethricor.internal/service"]
        for peer in netpol["spec"]["egress"][0]["to"]
    }
    assert services == {"agentgateway", "agent-runtime"}

    deployment = next(d for d in docs if d["kind"] == "Deployment")
    ann = deployment["spec"]["template"]["metadata"]["annotations"]
    assert ann["tethricor.internal/identity-mode"] == "none"

    # aks, by contrast, defaults to Azure Workload Identity federation.
    aks_deployment = next(d for d in _aks_docs() if d["kind"] == "Deployment")
    aks_ann = aks_deployment["spec"]["template"]["metadata"]["annotations"]
    assert aks_ann["tethricor.internal/identity-mode"] == "azure-workload-identity"


# --------------------------------------------------------------------------
# 3. no in-container execution path
# --------------------------------------------------------------------------
def test_shim_has_no_local_execution_path():
    shim_pkg = _ROOT / "shim" / "tethricor_runtime"
    banned = ("subprocess", "os.system(", "os.popen(", "pty.spawn", "os.execv")
    # `testing.py` is the reusable conformance/test kit (executing test doubles for
    # providers to self-certify against); it is never on the forwarded-execution runtime
    # path, so it is exempt from the no-local-exec scan.
    exempt = {"testing.py"}
    for path in shim_pkg.glob("*.py"):
        if path.name in exempt:
            continue
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.name} contains local-execution primitive {token!r}"


# --------------------------------------------------------------------------
# 4. memory provider refused + escape hatch stripped for non-local
# --------------------------------------------------------------------------
def test_webhook_refuses_memory_provider():
    review = {
        "request": {
            "uid": "u1",
            "object": {
                "metadata": {
                    "labels": {webhook.ENABLE_LABEL: "true"},
                    "annotations": {
                        webhook.ANN_SIDECAR_IMAGE: "img:1",
                        webhook.ANN_CONFIG: "cfg",
                        webhook.ANN_RUNTIME_PROVIDER: "memory",
                    },
                },
                "spec": {"containers": [{"name": "app"}]},
            },
        }
    }
    resp = webhook.build_response(review)["response"]
    assert resp["allowed"] is False
    assert "memory" in resp["status"]["message"]


def test_direct_azure_openai_stripped_for_non_local():
    config = {
        "harness": {"type": "hermes", "version": "0.17.0"},
        "runtime": {"profile": "python312"},
        "model": {
            "routing_profile": "gpt-4o-standard",
            "direct_azure_openai": {"endpoint": "https://x.openai.azure.com", "deployment": "gpt-4o"},
        },
    }
    image = "ghcr.io/your-org/tethricor/hermes-hardened:0.17.0"

    # local keeps the escape hatch...
    local_sanitized = security.sanitize_for_target(config, "local")
    local_files = generators.GENERATORS["local"](local_sanitized, image)
    assert "AZURE_OPENAI_ENDPOINT" in local_files["docker-compose.yaml"]

    # ...every non-local target strips it.
    for target in ("k8s", "aks", "aci", "job"):
        sanitized = security.sanitize_for_target(config, target)
        assert "direct_azure_openai" not in sanitized.get("model", {})
        blob = "\n".join(generators.GENERATORS[target](sanitized, image).values())
        assert "AZURE_OPENAI_ENDPOINT" not in blob


# --------------------------------------------------------------------------
# 5. aks/aci/job happy paths: image + identity + injected locked security context
# --------------------------------------------------------------------------
def test_aci_and_job_resolve_image_and_identity():
    image = manifest.resolve_image("openhands", "1.7.0", None)
    config = {"harness": {"type": "openhands", "version": "1.7.0"}, "runtime": {"profile": "python312", "timeout_seconds": 300}}

    aci = yaml.safe_load(generators.GENERATORS["aci"](config, image)["aci-container-group.yaml"])
    assert aci["identity"]["type"] == "UserAssigned"
    sidecar = next(c for c in aci["properties"]["containers"] if c["name"] == "harness-sidecar")
    assert sidecar["properties"]["image"] == image

    job = yaml.safe_load(generators.GENERATORS["job"](config, image)["aca-job.yaml"])
    assert job["identity"]["type"] == "UserAssigned"
    assert job["properties"]["template"]["containers"][0]["image"] == image


def test_aks_deployment_injected_by_webhook_is_hardened():
    """Feed the CLI-generated AKS pod template through the real webhook."""
    docs = _aks_docs()
    deployment = next(d for d in docs if d["kind"] == "Deployment")
    template = deployment["spec"]["template"]

    review = {"request": {"uid": "u2", "object": {"metadata": template["metadata"], "spec": template["spec"]}}}
    resp = webhook.build_response(review)["response"]
    assert resp["allowed"] is True

    import base64
    import json

    ops = json.loads(base64.b64decode(resp["patch"]))
    sidecar = next(o["value"] for o in ops if o["path"] == "/spec/containers/-")

    # hardened image resolved from the manifest (developer cannot override)
    assert sidecar["image"] == "ghcr.io/your-org/tethricor/hermes-hardened:0.17.0"
    # locked security context
    sec = sidecar["securityContext"]
    assert sec["runAsNonRoot"] is True
    assert sec["readOnlyRootFilesystem"] is True
    assert sec["allowPrivilegeEscalation"] is False
    assert sec["capabilities"]["drop"] == ["ALL"]
    # config mounted from the ConfigMap the CLI emitted
    vol = next(o for o in ops if o["path"] == "/spec/volumes")
    assert any(v.get("configMap", {}).get("name") == "tethricor-hermes-config" for v in vol["value"])
    # Azure Workload Identity for OIDC token federation
    assert any("azure.workload.identity~1use" in o["path"] for o in ops)


def test_k8s_deployment_injected_by_webhook_is_hardened_without_azure_identity():
    """Same as above, but through the cloud-neutral `k8s` target: identical hardening
    (image resolution, locked security context, config mount), but NO Azure Workload
    Identity label -- this is what makes the k8s target actually cloud-neutral rather
    than "aks with a different name"."""
    docs = _k8s_docs()
    deployment = next(d for d in docs if d["kind"] == "Deployment")
    template = deployment["spec"]["template"]

    review = {"request": {"uid": "u3", "object": {"metadata": template["metadata"], "spec": template["spec"]}}}
    resp = webhook.build_response(review)["response"]
    assert resp["allowed"] is True

    import base64
    import json

    ops = json.loads(base64.b64decode(resp["patch"]))
    sidecar = next(o["value"] for o in ops if o["path"] == "/spec/containers/-")
    assert sidecar["image"] == "ghcr.io/your-org/tethricor/hermes-hardened:0.17.0"
    sec = sidecar["securityContext"]
    assert sec["runAsNonRoot"] is True and sec["readOnlyRootFilesystem"] is True
    vol = next(o for o in ops if o["path"] == "/spec/volumes")
    assert any(v.get("configMap", {}).get("name") == "tethricor-hermes-config" for v in vol["value"])
    # No Azure Workload Identity label -- unmodified for GKE/EKS/kind/minikube.
    assert not any("azure.workload.identity" in o["path"] for o in ops)
