"""Resolve harness type + version to a platform-controlled hardened image tag."""
from __future__ import annotations

import os
import pathlib
from typing import Optional

import yaml

_DEFAULT_MANIFEST = pathlib.Path(__file__).resolve().parent / "data" / "image-manifest.yaml"


def manifest_path(override: Optional[str] = None) -> pathlib.Path:
    path = override or os.environ.get("TETHRICOR_IMAGE_MANIFEST")
    return pathlib.Path(path) if path else _DEFAULT_MANIFEST


def load_manifest(override: Optional[str] = None) -> dict:
    return yaml.safe_load(manifest_path(override).read_text(encoding="utf-8")) or {}


def resolve_image(harness_type: str, version: str, override: Optional[str] = None) -> str:
    """Return the hardened image reference for a harness type/version.

    Falls back to the `default` entry when the exact version is not pinned.
    """
    manifest = load_manifest(override)
    images = manifest.get("images", {})
    entry = images.get(harness_type)
    if not entry:
        raise KeyError(f"no image manifest entry for harness type {harness_type!r}")
    image = entry.get(version) or entry.get("default")
    if not image:
        raise KeyError(
            f"no image for {harness_type!r} version {version!r} and no default entry"
        )
    return image
