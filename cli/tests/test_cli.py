"""Unit tests for the tethricor CLI internals."""
from __future__ import annotations

import copy
import pathlib

import pytest
import yaml
from typer.testing import CliRunner

from tethricor_cli import generators, manifest, profiles, schema, security
from tethricor_cli.cli import app
from tethricor_cli.generators import aks, compose

runner = CliRunner()

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"


def _base_config() -> dict:
    return yaml.safe_load((EXAMPLES / "harness.openhands.yaml").read_text(encoding="utf-8"))


# --- schema / examples -------------------------------------------------------

def test_all_examples_validate():
    for path in EXAMPLES.glob("harness.*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert schema.validation_errors(data) == [], f"{path.name} should be valid"


def test_schema_rejects_extra_top_level_field():
    data = _base_config()
    data["deployment"] = {"target": "aks"}
    assert schema.validation_errors(data), "stray top-level field must be rejected"


def test_schema_accepts_custom_harness_type():
    # harness.type is no longer a closed enum: any non-empty name is schema-valid.
    # Whether it's actually runnable is a dynamic registry check (see
    # test_init_rejects_unregistered_harness_type / test_init_accepts_registered_custom_harness),
    # not a schema concern.
    data = _base_config()
    data["harness"]["type"] = "devin"
    assert schema.validation_errors(data) == []


def test_schema_rejects_empty_harness_type():
    data = _base_config()
    data["harness"]["type"] = ""
    assert schema.validation_errors(data)


def test_schema_accepts_optional_runtime_provider():
    data = _base_config()
    assert schema.validation_errors(data) == []  # back-compat: provider omitted
    data["runtime"]["provider"] = "enterprise-runtime"
    assert schema.validation_errors(data) == []


def test_schema_rejects_empty_runtime_provider():
    data = _base_config()
    data["runtime"]["provider"] = ""
    assert schema.validation_errors(data)


# --- init CLI: --sandbox is required (no default provider) -------------------

def _init_args(out: pathlib.Path, *extra: str) -> list:
    return ["init", "--yes", "--type", "hermes", "--repo-url", "https://x/y.git", "--out", str(out), *extra]


def test_init_requires_sandbox(tmp_path):
    # There is no default sandbox provider; omitting --sandbox in non-interactive mode
    # must fail rather than silently writing a config with no runtime.provider.
    out = tmp_path / "h.yaml"
    res = runner.invoke(app, _init_args(out))
    assert res.exit_code != 0
    assert not out.exists()


def test_init_writes_validated_provider(tmp_path):
    out = tmp_path / "h.yaml"
    res = runner.invoke(app, _init_args(out, "--sandbox", "remote-runtime"))
    assert res.exit_code == 0, res.output
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["runtime"]["provider"] == "remote-runtime"


def test_init_accepts_deprecated_enterprise_runtime_alias(tmp_path):
    # Back-compat: enterprise-runtime remains a registered alias for remote-runtime.
    out = tmp_path / "h.yaml"
    res = runner.invoke(app, _init_args(out, "--sandbox", "enterprise-runtime"))
    assert res.exit_code == 0, res.output
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["runtime"]["provider"] == "enterprise-runtime"


def test_init_rejects_unknown_sandbox(tmp_path):
    out = tmp_path / "h.yaml"
    res = runner.invoke(app, _init_args(out, "--sandbox", "bogus-provider"))
    assert res.exit_code != 0
    assert not out.exists()


# --- init/local-dev CLI: custom (non-built-in) harness types ------------------

def test_init_rejects_unregistered_harness_type(tmp_path):
    out = tmp_path / "h.yaml"
    res = runner.invoke(app, [
        "init", "--yes", "--type", "totally-unregistered-harness",
        "--repo-url", "https://x/y.git", "--sandbox", "remote-runtime", "--out", str(out),
    ])
    assert res.exit_code != 0
    assert not out.exists()


def test_init_and_local_dev_accept_registered_custom_harness(tmp_path, monkeypatch):
    """A harness registered only via the SDK's adapter registry (e.g. by a plugin) is
    usable end-to-end through the CLI: init accepts it dynamically (no schema/enum
    change needed), and local-dev generates artifacts for it via --image (there's no
    image-manifest.yaml entry for a harness nobody's shipped a hardened image for)."""
    from tethricor_runtime.adapters import register_harness
    from tethricor_runtime.interfaces import HarnessAdapter

    class _CustomAdapter(HarnessAdapter):
        name = "my-custom-harness"
        default_profile = "python312"
        pre_artifact_argv = None
        entrypoint = ["my-custom-harness", "run"]
        task_arg = "--task"

        def session_env(self, gateway_url, mcp_url):
            return {}

    register_harness("my-custom-harness", _CustomAdapter())

    cfg = tmp_path / "h.yaml"
    res = runner.invoke(app, [
        "init", "--yes", "--type", "my-custom-harness",
        "--repo-url", "https://x/y.git", "--sandbox", "remote-runtime", "--out", str(cfg),
    ])
    assert res.exit_code == 0, res.output
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["harness"]["type"] == "my-custom-harness"
    assert data["runtime"]["profile"] == "python312"  # picked up from the adapter's default_profile

    out_dir = tmp_path / "out"
    res = runner.invoke(app, [
        "local-dev", str(cfg), "--target", "local", "--out-dir", str(out_dir),
        "--image", "example.registry/my-custom-harness:latest",
    ])
    assert res.exit_code == 0, res.output
    compose = yaml.safe_load((out_dir / "local" / "docker-compose.yaml").read_text())
    assert compose["services"]["harness-sidecar"]["image"] == "example.registry/my-custom-harness:latest"


def test_local_dev_unregistered_manifest_entry_requires_image(tmp_path):
    cfg = tmp_path / "h.yaml"
    res = runner.invoke(app, [
        "init", "--yes", "--type", "hermes", "--version", "9.9.9-does-not-exist",
        "--repo-url", "https://x/y.git", "--sandbox", "remote-runtime", "--out", str(cfg),
    ])
    assert res.exit_code == 0, res.output  # hermes falls back to the manifest's "default" entry

    # Force a genuinely unresolvable image lookup to confirm --image unblocks it.
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["harness"]["type"] = "my-other-custom-harness"
    from tethricor_runtime.adapters import register_harness
    from tethricor_runtime.interfaces import HarnessAdapter

    class _OtherAdapter(HarnessAdapter):
        name = "my-other-custom-harness"
        default_profile = "python312"
        pre_artifact_argv = None

        def session_env(self, gateway_url, mcp_url):
            return {}

    register_harness("my-other-custom-harness", _OtherAdapter())
    cfg.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    out_dir = tmp_path / "out"
    res = runner.invoke(app, ["local-dev", str(cfg), "--target", "local", "--out-dir", str(out_dir)])
    assert res.exit_code != 0
    assert "--image" in res.output

    res = runner.invoke(app, [
        "local-dev", str(cfg), "--target", "local", "--out-dir", str(out_dir),
        "--image", "example.registry/other:latest",
    ])
    assert res.exit_code == 0, res.output


# --- profiles ----------------------------------------------------------------

def test_default_profiles_map():
    assert profiles.default_profile("hermes") == "python312"
    assert profiles.default_profile("goose") == "rust"
    assert profiles.default_profile("opencode") == "node20"


def test_feynman_shares_pi_adapter():
    assert profiles.adapter_for("feynman") == "pi"
    assert profiles.adapter_for("pi") == "pi"


# --- image manifest ----------------------------------------------------------

def test_resolve_image_version_and_default():
    assert manifest.resolve_image("openhands", "1.7.0").endswith("openhands-hardened:1.7.0")
    # Unknown version falls back to default.
    assert manifest.resolve_image("openhands", "9.9.9").endswith("openhands-hardened:1.7.0")


def test_resolve_image_unknown_type_raises():
    with pytest.raises(KeyError):
        manifest.resolve_image("devin", "1.0")


# --- security ----------------------------------------------------------------

def test_direct_azure_openai_stripped_for_non_local():
    data = _base_config()
    data["model"]["direct_azure_openai"] = {
        "endpoint": "https://x.openai.azure.com",
        "deployment": "gpt-4o",
    }
    kept = security.sanitize_for_target(copy.deepcopy(data), "local")
    assert "direct_azure_openai" in kept["model"]

    stripped = security.sanitize_for_target(copy.deepcopy(data), "aks")
    assert "direct_azure_openai" not in stripped["model"]


# --- generators --------------------------------------------------------------

def test_local_compose_mounts_config_the_shim_actually_reads():
    """Regression test: Settings.from_env() (shim/tethricor_runtime/config.py) reads
    runtime.provider/profile/timeout_seconds and source.repo_url/ref EXCLUSIVELY from
    the mounted harness.yaml -- none of those have an env var fallback. Without the
    mount, code-IN (git clone) silently never happens and runtime.provider is ignored
    regardless of what sidecar_env() sets."""
    data = _base_config()
    files = compose.generate(data, "img:latest")
    assert "harness.yaml" in files
    written_config = yaml.safe_load(files["harness.yaml"])
    assert written_config["source"]["repo_url"] == data["source"]["repo_url"]
    assert written_config["runtime"]["provider"] == data["runtime"]["provider"]

    compose_doc = yaml.safe_load(files["docker-compose.yaml"])
    sidecar = compose_doc["services"]["harness-sidecar"]
    assert sidecar["volumes"] == ["./harness.yaml:/etc/tethricor/harness.yaml:ro"]
    assert sidecar["environment"]["TETHRICOR_CONFIG_PATH"] == "/etc/tethricor/harness.yaml"


def test_local_compose_includes_escape_hatch_env():
    data = _base_config()
    data["model"]["direct_azure_openai"] = {
        "endpoint": "https://x.openai.azure.com",
        "deployment": "gpt-4o",
    }
    sanitized = security.sanitize_for_target(data, "local")
    files = compose.generate(sanitized, "img:latest")
    assert "AZURE_OPENAI_ENDPOINT" in files["docker-compose.yaml"]
    # The escape hatch's own file (harness.yaml) is what actually carries it into the
    # sidecar via the mount; the env var is supplementary.
    assert "direct_azure_openai" in yaml.safe_load(files["harness.yaml"])["model"]


def test_aks_strips_escape_hatch_and_sets_egress():
    data = _base_config()
    data["model"]["direct_azure_openai"] = {
        "endpoint": "https://x.openai.azure.com",
        "deployment": "gpt-4o",
    }
    sanitized = security.sanitize_for_target(data, "aks")
    files = aks.generate(sanitized, "img:latest")
    manifests = files["aks-manifests.yaml"]
    assert "AZURE_OPENAI_ENDPOINT" not in manifests
    assert "agentgateway" in manifests and "agent-runtime" in manifests
    assert "tethricor.internal/enabled" in manifests


def test_all_targets_generate_nonempty():
    data = _base_config()
    for target, gen in generators.GENERATORS.items():
        files = gen(data, "img:latest")
        assert files, f"{target} produced no files"
        for content in files.values():
            assert content.strip()
