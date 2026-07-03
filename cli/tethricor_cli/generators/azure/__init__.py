"""Azure-specific deployment target generators (`aci`, `job`) — opt-in, not cloud-neutral.

Azure Container Instances and Azure Container Apps Jobs have no direct equivalent on
other clouds. Rather than fabricate unverified AWS/GCP stand-ins, these stay
explicitly Azure-only and are labeled as such. Use `--target k8s` (cloud-neutral) or
`--target aks` (Kubernetes + Azure Workload Identity) if you're not on Azure, or don't
want an Azure-flavored artifact.
"""
from __future__ import annotations

from . import aci, job

__all__ = ["aci", "job"]
