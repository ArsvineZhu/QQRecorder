from __future__ import annotations

import argparse
import difflib
import fnmatch
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:\.post\d+)?$")


@dataclass(slots=True)
class Rule:
    path: str
    match: str
    replace: str
    required: bool = True
    allow_multiple: bool = False
    name: str | None = None


@dataclass(slots=True)
class RuleConfig:
    exclude_globs: list[str]
    rules: list[Rule]


@dataclass(slots=True)
class FileChange:
    relative_path: Path
    before: str
    after: str
    match_count: int
    rule_name: str


def validate_version(version: str) -> bool:
    return bool(VERSION_PATTERN.fullmatch(version))


def load_rule_config(config_path: Path) -> RuleConfig:
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Config file not found: {config_path}") from exc

    exclude_globs = raw.get("exclude_globs", [])
    if not isinstance(exclude_globs, list) or not all(
        isinstance(item, str) for item in exclude_globs
    ):
        raise ValueError("exclude_globs must be a string list")

    raw_rules = raw.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError("rules must be a list")
    if not raw_rules:
        raise ValueError("rules must not be empty")

    rules: list[Rule] = []
    for index, item in enumerate(raw_rules):
        rules.append(_parse_rule(item, index))

    return RuleConfig(exclude_globs=list(exclude_globs), rules=rules)


def _parse_rule(item: object, index: int) -> Rule:
    if not isinstance(item, dict):
        raise ValueError(f"rule #{index} must be a table")

    try:
        path = item["path"]
        match = item["match"]
        replace = item["replace"]
    except KeyError as exc:
        raise ValueError(f"rule #{index} missing field: {exc.args[0]}") from exc

    if not all(isinstance(field, str) for field in (path, match, replace)):
        raise ValueError(f"rule #{index} fields path/match/replace must be strings")

    required = item.get("required", True)
    allow_multiple = item.get("allow_multiple", False)
    name = item.get("name")
    if not isinstance(required, bool) or not isinstance(allow_multiple, bool):
        raise ValueError(f"rule #{index} required/allow_multiple must be bool")
    if name is not None and not isinstance(name, str):
        raise ValueError(f"rule #{index} name must be string")

    return Rule(
        path=path,
        match=match,
        replace=replace,
        required=required,
        allow_multiple=allow_multiple,
        name=name,
    )


def _is_excluded(path: Path, exclude_globs: list[str]) -> bool:
    posix_path = path.as_posix()
    for pattern in exclude_globs:
        if fnmatch.fnmatch(posix_path, pattern) or fnmatch.fnmatch(path.name, pattern):
            return True
    return False


def _build_diff(change: FileChange) -> str:
    return "".join(
        difflib.unified_diff(
            change.before.splitlines(keepends=True),
            change.after.splitlines(keepends=True),
            fromfile=str(change.relative_path),
            tofile=str(change.relative_path),
            n=2,
        )
    )


def run_set(  # noqa: C901
    *,
    version: str,
    config_path: Path,
    apply: bool,
    check: bool,
    verbose: bool,
    root: Path,
) -> int:
    if apply and check:
        print("--apply and --check cannot be used together", file=sys.stderr)
        return 2

    if not validate_version(version):
        print(f"Invalid version format: {version}", file=sys.stderr)
        return 2

    try:
        config = load_rule_config(config_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    changes, errors = _evaluate_rules(
        version=version,
        config=config,
        root=root,
        verbose=verbose,
    )

    if errors:
        print("Version update aborted due to rule errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 2

    if not changes:
        print("No changes needed. Files are already up to date.")
        return 0

    print(f"Planned changes: {len(changes)} file(s)")
    for change in changes:
        print(
            f"  - {change.relative_path} via {change.rule_name} "
            f"(matches={change.match_count})"
        )
        print(_build_diff(change))

    if check:
        print("Check mode: differences found.")
        return 1

    if not apply:
        print("Dry-run mode: no files were written. Use --apply to persist changes.")
        return 0

    for change in changes:
        (root / change.relative_path).write_text(change.after, encoding="utf-8")
    print(f"Applied changes to {len(changes)} file(s).")
    return 0


def _evaluate_rules(
    *, version: str, config: RuleConfig, root: Path, verbose: bool
) -> tuple[list[FileChange], list[str]]:
    changes: list[FileChange] = []
    errors: list[str] = []
    for rule in config.rules:
        change, error = _evaluate_rule(
            rule=rule,
            version=version,
            root=root,
            exclude_globs=config.exclude_globs,
            verbose=verbose,
        )
        if error is not None:
            errors.append(error)
            continue
        if change is not None:
            changes.append(change)
    return changes, errors


def _evaluate_rule(  # noqa: C901
    *,
    rule: Rule,
    version: str,
    root: Path,
    exclude_globs: list[str],
    verbose: bool,
) -> tuple[FileChange | None, str | None]:
    relative_path = Path(rule.path)
    if _is_excluded(relative_path, exclude_globs):
        return None, f"Rule points to excluded path: {rule.path}"

    target_path = root / relative_path
    if not target_path.exists():
        return None, f"Target file not found: {rule.path}"

    try:
        pattern = re.compile(rule.match)
    except re.error as exc:
        return None, f"Invalid regex for {rule.path}: {exc}"

    before = target_path.read_text(encoding="utf-8")
    match_count = sum(1 for _ in pattern.finditer(before))
    rule_name = rule.name or rule.path

    if match_count == 0 and rule.required:
        return None, f"{rule_name}: required rule matched 0 times"
    if match_count > 1 and not rule.allow_multiple:
        return None, f"{rule_name}: matched {match_count} times (allow_multiple=false)"
    if match_count == 0:
        if verbose:
            print(f"[skip] {rule_name}: no match")
        return None, None

    replacement = rule.replace.format(version=version)
    limit = 0 if rule.allow_multiple else 1
    after, replaced_count = pattern.subn(replacement, before, count=limit)
    if replaced_count == 0 and rule.required:
        return None, f"{rule_name}: replacement failed"

    if verbose:
        print(f"[match] {rule_name}: {replaced_count} replacement(s)")
    if before == after:
        return None, None
    return (
        FileChange(
            relative_path=relative_path,
            before=before,
            after=after,
            match_count=match_count,
            rule_name=rule_name,
        ),
        None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QQRecorder version management tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set", help="Set repository version")
    set_parser.add_argument("version", help="Target version, e.g. 1.4.2 or 1.4.2.post1")
    set_parser.add_argument(
        "--config",
        default="devtools/version_rules.toml",
        help="Rule config path",
    )
    set_parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to files",
    )
    set_parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when files differ from target version",
    )
    set_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-rule details",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "set":
        return run_set(
            version=args.version,
            config_path=Path(args.config),
            apply=bool(args.apply),
            check=bool(args.check),
            verbose=bool(args.verbose),
            root=Path.cwd(),
        )

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
