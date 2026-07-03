"""`--target aks`: the cloud-neutral `k8s` generator with Azure Workload Identity
federation turned on by default.

AKS is just Kubernetes plus an Azure-specific identity mechanism, so this is a thin
wrapper — not a separate implementation — kept for backward compatibility with
existing `--target aks` usage. Prefer `--target k8s` for a cluster that isn't AKS (or
that doesn't need Azure Workload Identity); it produces the identical manifest shape
with `identity_mode="none"`.
"""
from __future__ import annotations

from typing import Dict

from . import k8s

# Re-exported for back-compat: code that imported `aks.ENABLE_LABEL` keeps working.
ENABLE_LABEL = k8s.ENABLE_LABEL


def generate(config: dict, image: str) -> Dict[str, str]:
    return k8s.generate(
        config,
        image,
        identity_mode=k8s.IDENTITY_MODE_AZURE_WORKLOAD_IDENTITY,
        manifest_filename="aks-manifests.yaml",
    )
