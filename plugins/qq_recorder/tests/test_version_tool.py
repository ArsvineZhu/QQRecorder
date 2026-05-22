from __future__ import annotations

from pathlib import Path

from devtools.version_tool import run_set, validate_version


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _config_text(rule_path: str, rule_match: str, rule_replace: str) -> str:
    return f"""
exclude_globs = ["README*", "CHANGELOG*", "AGENTS*", "docs/**"]

[[rules]]
name = "rule"
path = "{rule_path}"
match = '{rule_match}'
replace = '{rule_replace}'
required = true
""".strip()


def _config_text_no_exclude(rule_path: str, rule_match: str, rule_replace: str) -> str:
    return f"""
[[rules]]
name = "rule"
path = "{rule_path}"
match = '{rule_match}'
replace = '{rule_replace}'
required = true
""".strip()


def test_validate_version_accepts_expected_formats():
    assert validate_version("1.2.3")
    assert validate_version("10.20.30.post4")
    assert not validate_version("1.2")
    assert not validate_version("v1.2.3")
    assert not validate_version("1.2.3-post1")


def test_required_rule_miss_returns_error(tmp_path: Path):
    _write(tmp_path / "target.txt", "x = 1\n")
    config = _config_text("target.txt", r"(?m)^version = .+$", 'version = "{version}"')
    _write(tmp_path / "rules.toml", config)

    code = run_set(
        version="1.2.3",
        config_path=tmp_path / "rules.toml",
        apply=False,
        check=False,
        verbose=False,
        root=tmp_path,
    )
    assert code == 2


def test_multiple_match_without_allow_multiple_returns_error(tmp_path: Path):
    _write(
        tmp_path / "target.txt",
        'version = "1.0.0"\nversion = "1.0.0"\n',
    )
    config = _config_text(
        "target.txt",
        r'(?m)^version = "[^"]+"$',
        'version = "{version}"',
    )
    _write(tmp_path / "rules.toml", config)

    code = run_set(
        version="1.2.3",
        config_path=tmp_path / "rules.toml",
        apply=False,
        check=False,
        verbose=False,
        root=tmp_path,
    )
    assert code == 2


def test_uv_lock_only_updates_qqrecorder_entry(tmp_path: Path):
    uv_lock = """
[[package]]
name = "aiosignal"
version = "1.4.0"

[[package]]
name = "qqrecorder"
version = "1.4.1"
source = { editable = "." }
""".strip()
    _write(tmp_path / "uv.lock", uv_lock + "\n")
    config = _config_text(
        "uv.lock",
        r'(?ms)(name = "qqrecorder"\nversion = ")[^"]+(")',
        r"\g<1>{version}\g<2>",
    )
    _write(tmp_path / "rules.toml", config)

    code = run_set(
        version="2.0.0",
        config_path=tmp_path / "rules.toml",
        apply=True,
        check=False,
        verbose=False,
        root=tmp_path,
    )
    assert code == 0
    content = (tmp_path / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "qqrecorder"\nversion = "2.0.0"' in content
    assert 'name = "aiosignal"\nversion = "1.4.0"' in content


def test_dry_run_does_not_write_file(tmp_path: Path):
    _write(tmp_path / "pyproject.toml", 'version = "1.0.0"\n')
    _write(tmp_path / "README.md", "version = 1.0.0 should stay untouched\n")
    config = _config_text(
        "pyproject.toml",
        r'(?m)^version = "[^"]+"$',
        'version = "{version}"',
    )
    _write(tmp_path / "rules.toml", config)

    code = run_set(
        version="1.2.3",
        config_path=tmp_path / "rules.toml",
        apply=False,
        check=False,
        verbose=False,
        root=tmp_path,
    )
    assert code == 0
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == (
        'version = "1.0.0"\n'
    )
    assert "1.0.0" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_check_mode_returns_nonzero_when_different(tmp_path: Path):
    _write(tmp_path / "pyproject.toml", 'version = "1.0.0"\n')
    config = _config_text(
        "pyproject.toml",
        r'(?m)^version = "[^"]+"$',
        'version = "{version}"',
    )
    _write(tmp_path / "rules.toml", config)

    code = run_set(
        version="1.2.3",
        config_path=tmp_path / "rules.toml",
        apply=False,
        check=True,
        verbose=False,
        root=tmp_path,
    )
    assert code == 1


def test_protected_readme_rule_is_blocked_by_default(tmp_path: Path):
    _write(tmp_path / "README.md", "### v1.4.1\n")
    config = _config_text_no_exclude(
        "README.md",
        r"(?m)^### v[0-9]+\.[0-9]+\.[0-9]+$",
        "### v{version}",
    )
    _write(tmp_path / "rules.toml", config)

    code = run_set(
        version="1.5.0",
        config_path=tmp_path / "rules.toml",
        apply=False,
        check=False,
        verbose=False,
        root=tmp_path,
    )
    assert code == 2


def test_protected_readme_rule_can_be_overridden_explicitly(tmp_path: Path):
    _write(tmp_path / "README.md", "### v1.4.1\n")
    config = _config_text_no_exclude(
        "README.md",
        r"(?m)^### v[0-9]+\.[0-9]+\.[0-9]+$",
        "### v{version}",
    )
    _write(tmp_path / "rules.toml", config)

    code = run_set(
        version="1.5.0",
        config_path=tmp_path / "rules.toml",
        apply=True,
        check=False,
        verbose=False,
        root=tmp_path,
        allow_protected_writes=True,
    )
    assert code == 0
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "### v1.5.0\n"
