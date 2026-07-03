"""Tethricor Kubernetes Mutating Admission Webhook.

Injects the hardened harness **sidecar** into pods that opt in via the enablement
label, following the sidecar pattern (.cursorrules #3). Pure Kubernetes
`AdmissionReview` logic — no cloud-specific dependencies — so it runs unmodified on
AKS, GKE, EKS, kind, minikube, or any other cluster. It reads the annotations the
CLI's `k8s`/`aks` generator stamps onto the pod template:

  - tethricor.internal/enabled        (label) "true"          -> opt-in gate
  - tethricor.internal/harness-type   (annotation)             -> TETHRICOR_HARNESS_TYPE
  - tethricor.internal/config         (annotation) ConfigMap   -> mounted harness.yaml
  - tethricor.internal/sidecar-image  (annotation) image ref   -> resolved hardened image
  - tethricor.internal/identity-mode  (annotation) "none" | "azure-workload-identity"
                                       -> whether/which identity federation label to add

Platform-locked guarantees enforced here (developer cannot opt out):
  - sidecar runs non-root, read-only rootfs, no privilege escalation, all caps dropped
  - opt-in cloud identity federation (e.g. Azure Workload Identity) label added when
    the generator requests it via identity-mode; omitted entirely otherwise, so this
    works unmodified on clusters with a different (or no) identity mechanism
  - insecure pod configs are REFUSED (hostNetwork/hostPID/hostIPC, privileged
    containers, or a request to use the sandbox runtime's `memory` provider)

This webhook does NOT itself execute anything and never lets the harness run code
locally — execution is forwarded to the sandbox runtime by the injected shim.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="tethricor-mutating-webhook")

ENABLE_LABEL = "tethricor.internal/enabled"
ANN_HARNESS_TYPE = "tethricor.internal/harness-type"
ANN_CONFIG = "tethricor.internal/config"
ANN_SIDECAR_IMAGE = "tethricor.internal/sidecar-image"
ANN_RUNTIME_PROVIDER = "tethricor.internal/runtime-provider"
ANN_INJECTED = "tethricor.internal/injected"
ANN_IDENTITY_MODE = "tethricor.internal/identity-mode"

# Opt-in identity federation modes. Anything other than IDENTITY_MODE_AZURE_WORKLOAD_IDENTITY
# (including the annotation being absent) means: inject no identity label at all, which
# is the right behavior on clusters with a different (or no) identity mechanism.
IDENTITY_MODE_AZURE_WORKLOAD_IDENTITY = "azure-workload-identity"

SIDECAR_NAME = "harness"
CONFIG_VOLUME = "tethricor-config"
TMP_VOLUME = "tethricor-tmp"
CONFIG_MOUNT = "/etc/tethricor"
CONFIG_PATH = f"{CONFIG_MOUNT}/harness.yaml"

# Cluster service endpoints the shim talks to (overridable via the webhook's own env).
RUNTIME_URL = os.environ.get("TETHRICOR_RUNTIME_URL", "http://agent-runtime.tethricor.svc.cluster.local:8080")
GATEWAY_URL = os.environ.get("TETHRICOR_GATEWAY_URL", "http://agentgateway.tethricor.svc.cluster.local:8080")
MCP_URL = os.environ.get("TETHRICOR_MCP_URL", "http://agentgateway.tethricor.svc.cluster.local:8080/mcp")


def _security_context() -> Dict[str, object]:
    return {
        "runAsNonRoot": True,
        "runAsUser": 1001,
        "readOnlyRootFilesystem": True,
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
    }


def _sidecar_container(image: str, harness_type: str) -> Dict[str, object]:
    return {
        "name": SIDECAR_NAME,
        "image": image,
        "env": [
            {"name": "TETHRICOR_HARNESS_TYPE", "value": harness_type},
            {"name": "TETHRICOR_CONFIG_PATH", "value": CONFIG_PATH},
            {"name": "TETHRICOR_RUNTIME_URL", "value": RUNTIME_URL},
            {"name": "TETHRICOR_GATEWAY_URL", "value": GATEWAY_URL},
            {"name": "TETHRICOR_MCP_URL", "value": MCP_URL},
        ],
        "securityContext": _security_context(),
        "volumeMounts": [
            {"name": CONFIG_VOLUME, "mountPath": CONFIG_MOUNT, "readOnly": True},
            # read-only rootfs => provide a writable scratch dir
            {"name": TMP_VOLUME, "mountPath": "/tmp"},
        ],
        "resources": {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        },
    }


def _escape(token: str) -> str:
    """RFC 6901 JSON Pointer escaping."""
    return token.replace("~", "~0").replace("/", "~1")


def _deny_reason(pod_spec: dict) -> Optional[str]:
    """Return a message if the pod violates a platform-locked security invariant."""
    for field in ("hostNetwork", "hostPID", "hostIPC"):
        if pod_spec.get(field) is True:
            return f"{field} is not permitted for Tethricor-enabled pods"
    for container in pod_spec.get("containers", []):
        sec = container.get("securityContext") or {}
        if sec.get("privileged") is True:
            return f"privileged container {container.get('name')!r} is not permitted"
    return None


def build_response(review: dict) -> dict:
    request = review.get("request", {})
    uid = request.get("uid", "")
    pod = request.get("object", {}) or {}
    metadata = pod.get("metadata", {}) or {}
    labels = metadata.get("labels", {}) or {}
    annotations = metadata.get("annotations", {}) or {}
    spec = pod.get("spec", {}) or {}

    def allow(patch_ops: Optional[List[dict]] = None) -> dict:
        response: Dict[str, object] = {"uid": uid, "allowed": True}
        if patch_ops:
            payload = base64.b64encode(json.dumps(patch_ops).encode()).decode()
            response["patchType"] = "JSONPatch"
            response["patch"] = payload
        return {"apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview", "response": response}

    def deny(message: str) -> dict:
        return {
            "apiVersion": "admission.k8s.io/v1",
            "kind": "AdmissionReview",
            "response": {"uid": uid, "allowed": False, "status": {"code": 403, "message": message}},
        }

    # Not opted in -> pass through untouched.
    if labels.get(ENABLE_LABEL) != "true":
        return allow()

    # Refuse the memory provider outside local (defense-in-depth; DESIGN_NOTES §8).
    if annotations.get(ANN_RUNTIME_PROVIDER) == "memory":
        return deny("agent-runtime 'memory' provider is not permitted for deployed targets")

    violation = _deny_reason(spec)
    if violation:
        return deny(violation)

    # Idempotency: never inject twice.
    already = annotations.get(ANN_INJECTED) == "true" or any(
        c.get("name") == SIDECAR_NAME for c in spec.get("containers", [])
    )
    if already:
        return allow()

    image = annotations.get(ANN_SIDECAR_IMAGE)
    config_map = annotations.get(ANN_CONFIG)
    harness_type = annotations.get(ANN_HARNESS_TYPE, "")
    if not image:
        return deny(f"missing required annotation {ANN_SIDECAR_IMAGE}")
    if not config_map:
        return deny(f"missing required annotation {ANN_CONFIG}")

    ops: List[dict] = [
        {"op": "add", "path": "/spec/containers/-", "value": _sidecar_container(image, harness_type)},
    ]

    # Volumes: create the array if the pod has none, else append.
    config_volume = {"name": CONFIG_VOLUME, "configMap": {"name": config_map}}
    tmp_volume = {"name": TMP_VOLUME, "emptyDir": {}}
    if spec.get("volumes"):
        ops.append({"op": "add", "path": "/spec/volumes/-", "value": config_volume})
        ops.append({"op": "add", "path": "/spec/volumes/-", "value": tmp_volume})
    else:
        ops.append({"op": "add", "path": "/spec/volumes", "value": [config_volume, tmp_volume]})

    # Opt-in cloud identity federation, driven by the generator-stamped annotation.
    # Absent/unrecognized values inject nothing -- correct on clusters that use a
    # different (or no) identity mechanism (GKE Workload Identity, EKS IRSA, plain
    # service accounts, ...). Only the Azure flavor is implemented today; add another
    # `elif identity_mode == "..."` branch here for a future one.
    if annotations.get(ANN_IDENTITY_MODE) == IDENTITY_MODE_AZURE_WORKLOAD_IDENTITY:
        if labels:
            ops.append({"op": "add", "path": f"/metadata/labels/{_escape('azure.workload.identity/use')}", "value": "true"})
        else:
            ops.append({"op": "add", "path": "/metadata/labels", "value": {"azure.workload.identity/use": "true"}})

    # Injected marker.
    if annotations:
        ops.append({"op": "add", "path": f"/metadata/annotations/{_escape(ANN_INJECTED)}", "value": "true"})
    else:
        ops.append({"op": "add", "path": "/metadata/annotations", "value": {ANN_INJECTED: "true"}})

    return allow(ops)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/mutate")
async def mutate(request: Request):
    review = await request.json()
    return JSONResponse(build_response(review))


if __name__ == "__main__":
    cert_dir = os.environ.get("TETHRICOR_TLS_DIR", "/tls")
    cert = os.path.join(cert_dir, "tls.crt")
    key = os.path.join(cert_dir, "tls.key")
    kwargs = {"host": "0.0.0.0", "port": int(os.environ.get("PORT", "8443"))}
    if os.path.exists(cert) and os.path.exists(key):
        kwargs.update(ssl_certfile=cert, ssl_keyfile=key)
    uvicorn.run(app, **kwargs)
