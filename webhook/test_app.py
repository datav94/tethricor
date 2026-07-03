"""Unit tests for the Tethricor mutating admission webhook."""
from __future__ import annotations

import base64
import json
import pathlib
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from app import (  # noqa: E402
    ANN_CONFIG,
    ANN_HARNESS_TYPE,
    ANN_IDENTITY_MODE,
    ANN_INJECTED,
    ANN_RUNTIME_PROVIDER,
    ANN_SIDECAR_IMAGE,
    ENABLE_LABEL,
    IDENTITY_MODE_AZURE_WORKLOAD_IDENTITY,
    SIDECAR_NAME,
    app,
    build_response,
)

client = TestClient(app)


def _review(labels=None, annotations=None, spec=None, uid="abc-123"):
    pod = {"metadata": {}, "spec": spec if spec is not None else {"containers": [{"name": "app", "image": "app:1"}]}}
    if labels is not None:
        pod["metadata"]["labels"] = labels
    if annotations is not None:
        pod["metadata"]["annotations"] = annotations
    return {"request": {"uid": uid, "object": pod}}


def _enabled_annotations(**overrides):
    ann = {
        ANN_SIDECAR_IMAGE: "registry.example/tethricor/hermes-hardened:1.0",
        ANN_CONFIG: "tethricor-hermes-config",
        ANN_HARNESS_TYPE: "hermes",
        ANN_IDENTITY_MODE: IDENTITY_MODE_AZURE_WORKLOAD_IDENTITY,
    }
    ann.update(overrides)
    return ann


def _patch_ops(resp):
    return json.loads(base64.b64decode(resp["response"]["patch"]))


def test_disabled_pod_is_untouched():
    resp = build_response(_review(labels={"app": "x"}))
    assert resp["response"]["allowed"] is True
    assert "patch" not in resp["response"]


def test_enabled_pod_gets_sidecar_and_identity():
    resp = build_response(
        _review(labels={ENABLE_LABEL: "true", "app": "x"}, annotations=_enabled_annotations())
    )
    assert resp["response"]["allowed"] is True
    assert resp["response"]["patchType"] == "JSONPatch"
    ops = _patch_ops(resp)

    sidecar = next(o["value"] for o in ops if o["path"] == "/spec/containers/-")
    assert sidecar["name"] == SIDECAR_NAME
    assert sidecar["image"] == "registry.example/tethricor/hermes-hardened:1.0"
    sec = sidecar["securityContext"]
    assert sec["runAsNonRoot"] and sec["readOnlyRootFilesystem"]
    assert sec["allowPrivilegeEscalation"] is False
    assert sec["capabilities"]["drop"] == ["ALL"]

    # workload identity label added (identity-mode=azure-workload-identity, the aks flavor)
    assert any("azure.workload.identity~1use" in o["path"] for o in ops)
    # injected marker added
    assert any(o["path"].endswith(ANN_INJECTED.replace("/", "~1")) for o in ops)


def test_cloud_neutral_k8s_target_injects_no_identity_label():
    """identity-mode absent (the plain `k8s` generator's default) -> no Azure label at
    all, so this works unmodified on GKE/EKS/kind/minikube."""
    ann = _enabled_annotations()
    del ann[ANN_IDENTITY_MODE]
    resp = build_response(
        _review(labels={ENABLE_LABEL: "true", "app": "x"}, annotations=ann)
    )
    assert resp["response"]["allowed"] is True
    ops = _patch_ops(resp)
    assert not any("azure.workload.identity" in o["path"] for o in ops)
    # sidecar injection itself is unaffected by identity-mode
    sidecar = next(o["value"] for o in ops if o["path"] == "/spec/containers/-")
    assert sidecar["name"] == SIDECAR_NAME


def test_unrecognized_identity_mode_injects_no_identity_label():
    resp = build_response(
        _review(
            labels={ENABLE_LABEL: "true", "app": "x"},
            annotations=_enabled_annotations(**{ANN_IDENTITY_MODE: "gcp-workload-identity"}),
        )
    )
    ops = _patch_ops(resp)
    assert not any("azure.workload.identity" in o["path"] for o in ops)


def test_volumes_created_when_pod_has_none():
    resp = build_response(
        _review(labels={ENABLE_LABEL: "true"}, annotations=_enabled_annotations())
    )
    ops = _patch_ops(resp)
    vol_op = next(o for o in ops if o["path"] == "/spec/volumes")
    names = {v["name"] for v in vol_op["value"]}
    assert names == {"tethricor-config", "tethricor-tmp"}


def test_volumes_appended_when_pod_has_some():
    spec = {"containers": [{"name": "app"}], "volumes": [{"name": "existing", "emptyDir": {}}]}
    resp = build_response(
        _review(labels={ENABLE_LABEL: "true"}, annotations=_enabled_annotations(), spec=spec)
    )
    ops = _patch_ops(resp)
    appended = [o for o in ops if o["path"] == "/spec/volumes/-"]
    assert {o["value"]["name"] for o in appended} == {"tethricor-config", "tethricor-tmp"}


def test_idempotent_when_sidecar_present():
    spec = {"containers": [{"name": "app"}, {"name": SIDECAR_NAME, "image": "x"}]}
    resp = build_response(
        _review(labels={ENABLE_LABEL: "true"}, annotations=_enabled_annotations(), spec=spec)
    )
    assert resp["response"]["allowed"] is True
    assert "patch" not in resp["response"]


def test_missing_image_denied():
    ann = _enabled_annotations()
    ann.pop(ANN_SIDECAR_IMAGE)
    resp = build_response(_review(labels={ENABLE_LABEL: "true"}, annotations=ann))
    assert resp["response"]["allowed"] is False
    assert ANN_SIDECAR_IMAGE in resp["response"]["status"]["message"]


def test_memory_provider_denied():
    ann = _enabled_annotations(**{ANN_RUNTIME_PROVIDER: "memory"})
    resp = build_response(_review(labels={ENABLE_LABEL: "true"}, annotations=ann))
    assert resp["response"]["allowed"] is False
    assert "memory" in resp["response"]["status"]["message"]


def test_privileged_container_denied():
    spec = {"containers": [{"name": "app", "securityContext": {"privileged": True}}]}
    resp = build_response(
        _review(labels={ENABLE_LABEL: "true"}, annotations=_enabled_annotations(), spec=spec)
    )
    assert resp["response"]["allowed"] is False
    assert "privileged" in resp["response"]["status"]["message"]


def test_host_network_denied():
    spec = {"hostNetwork": True, "containers": [{"name": "app"}]}
    resp = build_response(
        _review(labels={ENABLE_LABEL: "true"}, annotations=_enabled_annotations(), spec=spec)
    )
    assert resp["response"]["allowed"] is False
    assert "hostNetwork" in resp["response"]["status"]["message"]


def test_mutate_endpoint_roundtrip():
    review = _review(labels={ENABLE_LABEL: "true"}, annotations=_enabled_annotations())
    r = client.post("/mutate", json=review)
    assert r.status_code == 200
    assert r.json()["response"]["uid"] == "abc-123"
    assert client.get("/healthz").json() == {"status": "ok"}
