"""Deployment artifact generators, one per --target.

Each generator takes the sanitized harness config dict + resolved image and returns a
mapping of {filename: content} to write into the output directory.

Cloud-neutral targets (work on any Kubernetes cluster / plain Docker): `local`, `k8s`.
`aks` is `k8s` with Azure Workload Identity turned on by default (back-compat name).
`aci`/`job` are explicitly Azure-specific opt-in targets (see `azure/`); there is no
fabricated AWS/GCP equivalent.
"""
from __future__ import annotations

from typing import Callable, Dict

from . import aks, compose, k8s
from .azure import aci, job

Generator = Callable[[dict, str], Dict[str, str]]

GENERATORS: Dict[str, Generator] = {
    "local": compose.generate,
    "k8s": k8s.generate,
    "aks": aks.generate,
    "aci": aci.generate,
    "job": job.generate,
}


def available_targets() -> list[str]:
    return list(GENERATORS)
