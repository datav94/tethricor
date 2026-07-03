"""`--target k8s`: cloud-neutral Kubernetes artifacts the Mutating Webhook consumes at
admission time.

The CLI does NOT hand-inject the sidecar for Kubernetes targets — the webhook does
that (see `webhook/app.py`). This generator emits: a ConfigMap carrying harness.yaml,
a labeled Deployment the webhook mutates, and a default-deny egress NetworkPolicy
(platform-enforced perimeter). It is pure Kubernetes `AdmissionReview` +
`NetworkPolicy` — no cloud-specific assumptions — so it works unmodified on AKS, GKE,
EKS, kind, minikube, or any other cluster.

Identity federation is opt-in and pluggable via `identity_mode`, stamped as the
`tethricor.internal/identity-mode` pod annotation the webhook reads: the default here
(`"none"`) injects no identity label at all. `aks.py` is the same generator with Azure
Workload Identity federation turned on by default, kept as a back-compat name/shape.
"""
from __future__ import annotations

from typing import Dict

import yaml

from ..security import EGRESS_ALLOWLIST
from ._common import dump_yaml_docs

ENABLE_LABEL = "tethricor.internal/enabled"
ANN_IDENTITY_MODE = "tethricor.internal/identity-mode"

IDENTITY_MODE_NONE = "none"
IDENTITY_MODE_AZURE_WORKLOAD_IDENTITY = "azure-workload-identity"


def generate(
    config: dict,
    image: str,
    *,
    identity_mode: str = IDENTITY_MODE_NONE,
    manifest_filename: str = "k8s-manifests.yaml",
) -> Dict[str, str]:
    name = f"tethricor-{config['harness']['type']}"

    configmap = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": f"{name}-config"},
        "data": {"harness.yaml": yaml.safe_dump(config, sort_keys=False)},
    }

    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "labels": {ENABLE_LABEL: "true"}},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {
                    "labels": {"app": name, ENABLE_LABEL: "true"},
                    "annotations": {
                        # Webhook reads these to resolve/inject the hardened sidecar
                        # and to decide whether to federate any cloud identity.
                        "tethricor.internal/harness-type": config["harness"]["type"],
                        "tethricor.internal/config": f"{name}-config",
                        "tethricor.internal/sidecar-image": image,
                        ANN_IDENTITY_MODE: identity_mode,
                    },
                },
                "spec": {
                    "containers": [
                        {
                            "name": "app",
                            "image": "REPLACE_WITH_YOUR_APP_IMAGE",
                            # The webhook injects the harness sidecar alongside this.
                        }
                    ]
                },
            },
        },
    }

    # Default-deny egress; allow only the gateway + sandbox runtime (by label selector).
    netpol = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": f"{name}-egress"},
        "spec": {
            "podSelector": {"matchLabels": {"app": name}},
            "policyTypes": ["Egress"],
            "egress": [
                {
                    "to": [
                        {"podSelector": {"matchLabels": {"tethricor.internal/service": svc}}}
                        for svc in EGRESS_ALLOWLIST
                    ]
                },
                # Allow DNS resolution.
                {
                    "to": [{"namespaceSelector": {}}],
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                    ],
                },
            ],
        },
    }

    return {manifest_filename: dump_yaml_docs([configmap, deployment, netpol])}
