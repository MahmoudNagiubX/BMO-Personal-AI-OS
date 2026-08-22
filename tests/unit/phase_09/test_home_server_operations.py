"""Unit and security governance tests for home server operational tooling."""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "infrastructure/home_server/scripts"
COMMON_CONFIG = SCRIPTS_DIR / "common_config.sh"


def _find_bash() -> str | None:
    """Find a usable bash executable on Windows or Linux."""
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if git_bash.is_file():
        return str(git_bash)
    git_usr_bash = Path(r"C:\Program Files\Git\usr\bin\bash.exe")
    if git_usr_bash.is_file():
        return str(git_usr_bash)
    candidate = shutil.which("bash")
    if candidate and "system32" not in candidate.lower() and "windowsapps" not in candidate.lower():
        return candidate
    return None


def _secure_stat_path(tmp_path: Path) -> Path:
    """Provide deterministic secure-mode stat output for Git Bash on Windows."""
    fake_bin = tmp_path / "secure-stat-bin"
    fake_bin.mkdir(exist_ok=True)
    fake_stat = fake_bin / "stat"
    fake_stat.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "-c" && "$2" == "%a" ]]; then printf \'600\\n\';\n'
        'elif [[ "$1" == "-c" && "$2" == "%u" ]]; then printf \'0\\n\';\n'
        "else exit 1; fi\n",
        encoding="utf-8",
    )
    fake_stat.chmod(0o755)
    return fake_bin


def test_no_known_or_default_production_passwords_in_operational_scripts() -> None:
    """Ensure no default credentials or fallback passwords exist in operational scripts."""
    fallback_patterns = [
        ":-bmo_password",
        ":-bmo_user",
        ":-bmo_personal_ai_os",
    ]
    for script in SCRIPTS_DIR.glob("*.sh"):
        content = script.read_text(encoding="utf-8")
        for bad in fallback_patterns:
            assert bad not in content, (
                f"Found forbidden credential pattern '{bad}' in {script.name}"
            )
        if script.name != "common_config.sh":
            for bad in ["bmo_password", "bmo_dev_only", "bmo_ci_only"]:
                assert bad not in content, f"Found '{bad}' in {script.name}"
        else:
            assert "FORBIDDEN_PASSWORDS" in content
            assert '"bmo_password"' in content


def test_deployment_and_rollback_use_locked_dependencies() -> None:
    """Ensure deploy_release.sh and rollback_release.sh use uv frozen lockfiles."""
    deploy_script = (SCRIPTS_DIR / "deploy_release.sh").read_text(encoding="utf-8")
    rollback_script = (SCRIPTS_DIR / "rollback_release.sh").read_text(encoding="utf-8")

    pairs = [
        (deploy_script, "deploy_release.sh"),
        (rollback_script, "rollback_release.sh"),
    ]
    for script_content, name in pairs:
        assert "sync --frozen --no-dev" in script_content, f"Missing frozen lock sync in {name}"
        assert "pip install --upgrade pip" not in script_content, (
            f"Found mutable pip upgrade in {name}"
        )
        assert "pip install -e" not in script_content, f"Found unconstrained pip install in {name}"


def test_rollback_performs_full_runtime_verification() -> None:
    """Ensure rollback_release.sh verifies target build SHA, migration revision, and health."""
    rollback_script = (SCRIPTS_DIR / "rollback_release.sh").read_text(encoding="utf-8")
    assert "/health/ready" in rollback_script
    assert "/version" in rollback_script
    assert "alembic_version" in rollback_script
    assert "TARGET_MIGRATION" in rollback_script
    assert "TARGET_COMMIT" in rollback_script


def test_listener_bindings_remain_strictly_loopback() -> None:
    """Ensure PostgreSQL and Core API deployment configs use loopback 127.0.0.1 exclusively."""
    deploy_pg = (SCRIPTS_DIR / "deploy_postgres.sh").read_text(encoding="utf-8")
    common_cfg = (SCRIPTS_DIR / "common_config.sh").read_text(encoding="utf-8")
    service_path = ROOT / "infrastructure/home_server/systemd/bmo-core.service"
    service_file = service_path.read_text(encoding="utf-8")

    assert "127.0.0.1:5432:5432" in deploy_pg
    assert "--host 127.0.0.1" in service_file
    assert "0.0.0.0" not in deploy_pg
    assert "0.0.0.0" not in service_file
    assert "DEFAULT_POSTGRES_IMAGE" in common_cfg
    expected_image = (
        "pgvector/pgvector:pg16-bookworm@sha256:"
        "ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b"
    )
    assert expected_image in common_cfg


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Home-server permission semantics are validated in Linux CI",
)
def test_deploy_postgres_fails_closed_when_credentials_absent(tmp_path: Path) -> None:
    """Ensure deploy_postgres.sh fails closed when database credentials are not provided."""
    bash = _find_bash()
    if not bash:
        pytest.skip("Bash executable not available for script execution test")

    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")

    script = SCRIPTS_DIR / "deploy_postgres.sh"
    env = os.environ.copy()
    env["BMO_CONFIG_FILE"] = str(empty_env).replace("\\", "/")
    for inherited in (
        "BMO_DATABASE_URL",
        "BMO_POSTGRES_USER",
        "BMO_POSTGRES_PASSWORD",
        "BMO_POSTGRES_DB",
        "BMO_POSTGRES_HOST",
        "BMO_POSTGRES_PORT",
        "BMO_POSTGRES_IMAGE",
        "SUDO_UID",
    ):
        env.pop(inherited, None)
    env["PATH"] = f"{_secure_stat_path(tmp_path).as_posix()}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
        [bash, str(script).replace("\\", "/")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Error:" in result.stderr
    assert "missing" in result.stderr.lower()


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Home-server permission semantics are validated in Linux CI",
)
def test_backup_fails_closed_when_passphrase_missing(tmp_path: Path) -> None:
    """Ensure backup_database.sh fails closed when independent passphrase file is absent."""
    bash = _find_bash()
    if not bash:
        pytest.skip("Bash executable not available for script execution test")

    cfg = tmp_path / "core.env"
    cfg.write_text(
        "BMO_DATABASE_URL=postgresql+psycopg://valid_user:ValidStrongPass123!@127.0.0.1:5432/valid_db\n",
        encoding="utf-8",
    )
    non_existent_passphrase = tmp_path / "does_not_exist_passphrase.txt"

    script = SCRIPTS_DIR / "backup_database.sh"
    env = os.environ.copy()
    env["BMO_CONFIG_FILE"] = str(cfg).replace("\\", "/")
    env.pop("SUDO_UID", None)
    env["PATH"] = f"{_secure_stat_path(tmp_path).as_posix()}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
        [
            bash,
            str(script).replace("\\", "/"),
            str(tmp_path).replace("\\", "/"),
            str(non_existent_passphrase).replace("\\", "/"),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert (
        "Independent backup passphrase file not found" in result.stderr
        or "not found" in result.stderr.lower()
    )
    # Confirm it did not fall back to database password
    assert "using BMO_DB_PASSWORD as encryption key" not in result.stdout
    assert "using BMO_DB_PASSWORD as encryption key" not in result.stderr


@pytest.mark.parametrize(
    "invalid_commit",
    [
        "../../etc/passwd",
        "HEAD~1",
        "main",
        "0123456789abcdef",  # too short
        "0123456789abcdef0123456789abcdef0123456G",  # non-hex character 'G'
        "24297a9c8ce8ce8d386874949aa3d87e0881d9cc; rm -rf /",
    ],
)
def test_commit_sha_validation_rejects_malformed_and_traversal_input(
    invalid_commit: str, tmp_path: Path
) -> None:
    """Ensure deploy_release.sh and rollback_release.sh reject invalid or malicious commit input."""
    bash = _find_bash()
    if not bash:
        pytest.skip("Bash executable not available for script execution test")

    for script_name in ["deploy_release.sh", "rollback_release.sh"]:
        script = SCRIPTS_DIR / script_name
        args = [bash, str(script).replace("\\", "/"), invalid_commit]
        if script_name == "rollback_release.sh":
            args.append("20260820_0005")

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "Invalid commit SHA" in result.stderr or "Error:" in result.stderr


def test_deploy_release_rejects_commit_sha_mismatch(tmp_path: Path) -> None:
    """Ensure deploy_release.sh rejects deployment if directory HEAD does not match commit."""
    bash = _find_bash()
    if not bash:
        pytest.skip("Bash executable not available for script execution test")

    fake_commit_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    releases_dir = tmp_path / "venom/core/releases" / fake_commit_a
    releases_dir.mkdir(parents=True)
    (releases_dir / "pyproject.toml").write_text("[project]\nname='bmo'\n", encoding="utf-8")
    (releases_dir / "uv.lock").write_text("", encoding="utf-8")

    git_bin = shutil.which("git")
    if not git_bin:
        pytest.skip("git not available for commit mismatch test")

    subprocess.run([git_bin, "init"], cwd=releases_dir, capture_output=True, check=True)
    subprocess.run(
        [git_bin, "config", "user.email", "test@test.com"],
        cwd=releases_dir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        [git_bin, "config", "user.name", "test"],
        cwd=releases_dir,
        capture_output=True,
        check=True,
    )
    subprocess.run([git_bin, "add", "."], cwd=releases_dir, capture_output=True, check=True)
    subprocess.run(
        [git_bin, "commit", "-m", "init"], cwd=releases_dir, capture_output=True, check=True
    )

    script = SCRIPTS_DIR / "deploy_release.sh"
    env = os.environ.copy()
    env["HOME"] = str(tmp_path).replace("\\", "/")

    result = subprocess.run(
        [bash, str(script).replace("\\", "/"), fake_commit_a],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "does not match requested commit" in result.stderr


def _run_common_function(
    bash: str, function: str, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    source = shlex.quote(str(COMMON_CONFIG).replace("\\", "/"))
    command = f'source {source}; {function} "$1" "$2"'
    return subprocess.run(
        [bash, "-c", command, "bmo-test", *[arg.replace("\\", "/") for arg in args]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _create_git_release(tmp_path: Path) -> tuple[Path, str]:
    git_bin = shutil.which("git")
    if not git_bin:
        pytest.skip("git not available for release identity test")
    release = tmp_path / "release"
    release.mkdir()
    (release / "pyproject.toml").write_text("[project]\nname='bmo'\n", encoding="utf-8")
    (release / "uv.lock").write_text("", encoding="utf-8")
    (release / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    subprocess.run([git_bin, "init"], cwd=release, capture_output=True, check=True)
    subprocess.run([git_bin, "config", "user.email", "test@test.com"], cwd=release, check=True)
    subprocess.run([git_bin, "config", "user.name", "test"], cwd=release, check=True)
    subprocess.run([git_bin, "add", "."], cwd=release, capture_output=True, check=True)
    subprocess.run([git_bin, "commit", "-m", "init"], cwd=release, capture_output=True, check=True)
    sha = subprocess.check_output([git_bin, "rev-parse", "HEAD"], cwd=release, text=True).strip()
    return release, sha


def test_release_identity_requires_git_metadata_and_resolvable_head(tmp_path: Path) -> None:
    bash = _find_bash()
    if not bash:
        pytest.skip("Bash executable not available for script execution test")
    missing = tmp_path / "missing"
    missing.mkdir()
    missing_result = _run_common_function(bash, "verify_release_identity", str(missing), "0" * 40)
    assert missing_result.returncode != 0

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / ".git").mkdir()
    invalid_result = _run_common_function(bash, "verify_release_identity", str(invalid), "0" * 40)
    assert invalid_result.returncode != 0


def test_release_identity_rejects_wrong_head_and_dirty_tree(tmp_path: Path) -> None:
    bash = _find_bash()
    if not bash:
        pytest.skip("Bash executable not available for script execution test")
    release, sha = _create_git_release(tmp_path)

    wrong = _run_common_function(bash, "verify_release_identity", str(release), "0" * 40)
    assert wrong.returncode != 0
    assert "does not match requested commit" in wrong.stderr

    (release / "mutation.txt").write_text("dirty\n", encoding="utf-8")
    dirty = _run_common_function(bash, "verify_release_identity", str(release), sha)
    assert dirty.returncode != 0
    assert "uncommitted source mutations" in dirty.stderr


def test_release_identity_accepts_correct_clean_exact_head(tmp_path: Path) -> None:
    bash = _find_bash()
    if not bash:
        pytest.skip("Bash executable not available for script execution test")
    release, sha = _create_git_release(tmp_path)
    result = _run_common_function(bash, "verify_release_identity", str(release), sha)
    assert result.returncode == 0, result.stderr


def _run_permission_check(
    bash: str, path: Path, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    source = shlex.quote(str(COMMON_CONFIG).replace("\\", "/"))
    command = f'source {source}; check_config_file_permissions "$1"'
    return subprocess.run(
        [bash, "-c", command, "bmo-test", str(path).replace("\\", "/")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(
    platform.system() != "Linux", reason="POSIX mode semantics are validated in Linux CI"
)
def test_secret_mode_0600_passes_and_broad_modes_are_remediated(tmp_path: Path) -> None:
    bash = _find_bash()
    if not bash:
        pytest.skip("Bash executable not available for script execution test")
    secret = tmp_path / "secret"
    secret.write_text("synthetic\n", encoding="utf-8")
    for mode in (0o600, 0o640, 0o660, 0o644):
        os.chmod(secret, mode)
        result = _run_permission_check(bash, secret)
        assert result.returncode == 0, result.stderr
        assert secret.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(
    platform.system() != "Linux", reason="POSIX mode semantics are validated in Linux CI"
)
def test_secret_mode_chmod_failure_fails_closed(tmp_path: Path) -> None:
    bash = _find_bash()
    if not bash:
        pytest.skip("Bash executable not available for script execution test")
    secret = tmp_path / "secret"
    secret.write_text("synthetic\n", encoding="utf-8")
    os.chmod(secret, 0o640)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_chmod = fake_bin / "chmod"
    fake_chmod.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    fake_chmod.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin.as_posix()}{os.pathsep}{env.get('PATH', '')}"
    result = _run_permission_check(bash, secret, env=env)
    assert result.returncode != 0
    assert "Failed to restrict" in result.stderr


def test_rollback_requires_explicit_model_gateway_health_contract() -> None:
    rollback = (SCRIPTS_DIR / "rollback_release.sh").read_text(encoding="utf-8")
    assert 'MODEL_GATEWAY_HEALTH_URL="http://127.0.0.1:8000/health/model-gateway"' in rollback
    assert '"Error: Model Gateway readiness check failed' in rollback
    assert "|| curl -fsS http://127.0.0.1:8000/health" not in rollback


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Home-server shell semantics are validated in Linux CI"
)
def test_rollback_model_gateway_failure_is_nonzero(tmp_path: Path) -> None:
    """Prove rollback cannot report success when its model-gateway check fails."""
    bash = _find_bash()
    if not bash:
        pytest.skip("Bash executable not available for script execution test")
    git_bin = shutil.which("git")
    if not git_bin:
        pytest.skip("git not available for rollback test")

    staging, sha = _create_git_release(tmp_path)
    release = tmp_path / "venom/core/releases" / sha
    release.parent.mkdir(parents=True)
    shutil.move(str(staging), str(release))
    venv_bin = release / ".venv/bin"
    venv_bin.mkdir(parents=True)
    alembic = venv_bin / "alembic"
    alembic.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    alembic.chmod(0o755)

    config = tmp_path / "venom/config/core.env"
    config.parent.mkdir(parents=True)
    config.write_text(
        "BMO_DATABASE_URL=postgresql+psycopg://valid_user:ValidStrongPass123!@127.0.0.1:5432/valid_db\n",
        encoding="utf-8",
    )
    config.chmod(0o600)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "uv").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (fake_bin / "systemctl").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (fake_bin / "docker").write_text(
        "#!/usr/bin/env bash\nprintf '20260820_0005\\n'\n", encoding="utf-8"
    )
    (fake_bin / "curl").write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        "  *'/health/model-gateway'*) exit 22;;\n"
        "  *'/health/ready'*) printf 'ready\\n'; exit 0;;\n"
        f"  *'/version'*) printf '{{\"build_sha\":\"{sha}\"}}'; exit 0;;\n"
        "  *) exit 0;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (fake_bin / "stat").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "-c" && "$2" == "%a" ]]; then printf \'600\\n\';\n'
        'elif [[ "$1" == "-c" && "$2" == "%u" ]]; then printf \'0\\n\';\n'
        "else exit 1; fi\n",
        encoding="utf-8",
    )
    for command in fake_bin.iterdir():
        command.chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(tmp_path).replace("\\", "/")
    env["BMO_CONFIG_FILE"] = str(config).replace("\\", "/")
    env.pop("SUDO_UID", None)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    rollback = SCRIPTS_DIR / "rollback_release.sh"
    result = subprocess.run(
        [
            bash,
            str(rollback).replace("\\", "/"),
            sha,
            "20260820_0005",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Model Gateway readiness check failed" in result.stderr
    assert "successfully completed and verified" not in result.stdout
