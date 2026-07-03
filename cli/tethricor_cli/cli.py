"""tethricor — Tethricor developer CLI.

Commands:
  init       Generate a validated harness.yaml (interactive or via flags).
  validate   Validate an existing harness.yaml against the contract schema.
  local-dev  Generate deployment artifacts for a --target (local|aks|aci|job).
"""
from __future__ import annotations

import pathlib
from typing import List, Optional

import typer
import yaml

from . import generators, manifest, profiles, schema, security
from .models import (
    DirectAzureOpenAI,
    Harness,
    HarnessConfig,
    Mcp,
    Model,
    Output,
    Runtime,
    Source,
)

app = typer.Typer(add_completion=False, help="Tethricor developer CLI.")


def _available_sandboxes() -> List[str]:
    """Installed sandbox providers, including entry-point plugins when the SDK is present.

    Falls back to the always-available generic REST client if the SDK isn't installed
    standalone. There is no "blessed" default provider — see `docs/agent_context` for why.
    """
    try:
        import tethricor  # noqa: F401  # importing triggers plugin discovery

        from tethricor_runtime.registry import available_sandboxes

        return available_sandboxes()
    except Exception:
        return ["remote-runtime"]


def _available_harness_types() -> List[str]:
    """Installed harness adapters: the built-ins plus any registered plugins.

    Mirrors `_available_sandboxes()`: prefers the live SDK registry (which includes
    entry-point-discovered custom adapters), falls back to the static built-in list
    when the SDK isn't installed standalone.
    """
    try:
        import tethricor  # noqa: F401  # importing triggers plugin discovery

        from tethricor_runtime.adapters import available_harnesses

        return available_harnesses()
    except Exception:
        return profiles.known_types()


def _default_profile_for(harness_type: str) -> Optional[str]:
    """Best-effort default runtime profile for a harness type.

    Tries the static built-in map first (works without the SDK installed), then the
    live adapter registry (covers custom-registered harnesses), then gives up — callers
    must fall back to requiring an explicit --runtime-profile.
    """
    if harness_type in profiles.HARNESSES:
        return profiles.default_profile(harness_type)
    try:
        import tethricor  # noqa: F401

        from tethricor_runtime.adapters import adapter_for

        return adapter_for(harness_type).default_profile
    except Exception:
        return None


def _write_config(config: HarnessConfig, out_path: pathlib.Path) -> None:
    data = config.to_ordered_dict()
    errors = schema.validation_errors(data)
    if errors:
        typer.secho("Generated config failed schema validation:", fg=typer.colors.RED)
        for e in errors:
            typer.secho(f"  - {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if out_path.parent and not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    typer.secho(f"Wrote {out_path}", fg=typer.colors.GREEN)


@app.command()
def init(
    harness_type: Optional[str] = typer.Option(None, "--type", help="Harness type."),
    version: Optional[str] = typer.Option(None, "--version", help="Harness version."),
    routing_profile: Optional[str] = typer.Option(None, "--routing-profile"),
    repo_url: Optional[str] = typer.Option(None, "--repo-url"),
    ref: str = typer.Option("main", "--ref"),
    runtime_profile: Optional[str] = typer.Option(
        None, "--runtime-profile", help="Defaults from the harness type if omitted."
    ),
    timeout_seconds: int = typer.Option(600, "--timeout-seconds"),
    sandbox: Optional[str] = typer.Option(
        None,
        "--sandbox",
        help="Sandbox provider. Required — there is no default (e.g. remote-runtime, microsandbox, e2b). Validated against the installed registry.",
    ),
    skills: Optional[List[str]] = typer.Option(None, "--skill", help="Repeatable."),
    mcp_servers: Optional[List[str]] = typer.Option(None, "--mcp-server", help="Repeatable."),
    output_mode: str = typer.Option("zip-download", "--output-mode"),
    out: pathlib.Path = typer.Option(pathlib.Path("harness.yaml"), "--out"),
    non_interactive: bool = typer.Option(False, "--yes", help="Do not prompt; use flags/defaults."),
) -> None:
    """Generate a validated harness.yaml.

    Both --type and --sandbox are required (interactively prompted if omitted): there is
    no default harness or sandbox provider. Built-in harness types are hermes, pi,
    feynman, openhands, goose, opencode; a custom-registered HarnessAdapter's name also
    works. Built-in sandbox providers depend on what's installed (at minimum
    `remote-runtime`; optionally `microsandbox`, `e2b`, or your own plugin).
    """
    known = _available_harness_types()
    available_sandboxes = _available_sandboxes()

    if not non_interactive:
        if harness_type is None:
            harness_type = typer.prompt(f"Harness type {known}")
        if version is None:
            version = typer.prompt("Harness version", default="latest")
        if routing_profile is None:
            routing_profile = typer.prompt("Model routing profile", default="gpt-4o-standard")
        if repo_url is None:
            repo_url = typer.prompt("Source repo URL")
        if sandbox is None:
            sandbox = typer.prompt(f"Sandbox provider {available_sandboxes}")

    if harness_type not in known:
        typer.secho(f"Unknown harness type {harness_type!r}; choose one of {known}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    version = version or "latest"
    routing_profile = routing_profile or "gpt-4o-standard"
    if not repo_url:
        typer.secho("--repo-url is required", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if not sandbox:
        typer.secho(
            f"--sandbox is required; installed providers: {available_sandboxes}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    if sandbox not in available_sandboxes:
        typer.secho(
            f"Unknown sandbox provider {sandbox!r}; installed providers: {available_sandboxes}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    resolved_profile = runtime_profile or _default_profile_for(harness_type)
    if not resolved_profile:
        typer.secho(
            f"No default runtime profile known for harness type {harness_type!r}; pass --runtime-profile explicitly.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    config = HarnessConfig(
        harness=Harness(type=harness_type, version=version),
        model=Model(routing_profile=routing_profile),
        skills=list(skills or []),
        mcp=Mcp(servers=list(mcp_servers or [])),
        runtime=Runtime(profile=resolved_profile, timeout_seconds=timeout_seconds, provider=sandbox),
        source=Source(repo_url=repo_url, ref=ref),
        output=Output(mode=output_mode),
    )
    _write_config(config, out)


@app.command()
def validate(
    config_path: pathlib.Path = typer.Argument(pathlib.Path("harness.yaml")),
) -> None:
    """Validate an existing harness.yaml against the contract schema."""
    if not config_path.is_file():
        typer.secho(f"No such file: {config_path}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    errors = schema.validation_errors(data)
    if errors:
        typer.secho(f"INVALID {config_path}", fg=typer.colors.RED)
        for e in errors:
            typer.secho(f"  - {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho(f"VALID {config_path}", fg=typer.colors.GREEN)


@app.command("local-dev")
def local_dev(
    config_path: pathlib.Path = typer.Argument(pathlib.Path("harness.yaml")),
    target: str = typer.Option("local", "--target", help="local|k8s|aks|aci|job"),
    out_dir: pathlib.Path = typer.Option(pathlib.Path("tethricor-out"), "--out-dir"),
    image_manifest: Optional[str] = typer.Option(None, "--image-manifest"),
    image: Optional[str] = typer.Option(
        None,
        "--image",
        help="Explicit hardened image to use, bypassing the image manifest. Required for "
        "harness types with no image-manifest.yaml entry (e.g. a custom-registered adapter).",
    ),
) -> None:
    """Generate deployment artifacts for a target from a harness.yaml."""
    if target not in generators.available_targets():
        typer.secho(
            f"Unknown target {target!r}; choose one of {generators.available_targets()}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    if not config_path.is_file():
        typer.secho(f"No such file: {config_path}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    errors = schema.validation_errors(data)
    if errors:
        typer.secho(f"INVALID {config_path}:", fg=typer.colors.RED)
        for e in errors:
            typer.secho(f"  - {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    # Platform security enforcement (e.g. strip local-only escape hatch for non-local).
    sanitized = security.sanitize_for_target(data, target)
    if target != "local" and data.get("model", {}).get("direct_azure_openai"):
        typer.secho(
            "note: stripped model.direct_azure_openai (local-only) for non-local target",
            fg=typer.colors.YELLOW,
        )

    if image is None:
        try:
            image = manifest.resolve_image(
                sanitized["harness"]["type"], str(sanitized["harness"]["version"]), image_manifest
            )
        except KeyError as exc:
            typer.secho(
                f"image resolution failed: {exc}. Pass --image explicitly for harness "
                "types with no image-manifest.yaml entry.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)

    files = generators.GENERATORS[target](sanitized, image)

    target_dir = out_dir / target
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        (target_dir / filename).write_text(content, encoding="utf-8")
        typer.secho(f"Wrote {target_dir / filename}", fg=typer.colors.GREEN)
    typer.secho(f"Resolved image: {image}", fg=typer.colors.CYAN)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
