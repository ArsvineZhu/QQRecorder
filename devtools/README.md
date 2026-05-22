# Devtools

Version tool usage:

```bash
uv run python devtools/version_tool.py set 1.4.2
uv run python devtools/version_tool.py set 1.4.2 --apply
uv run python devtools/version_tool.py set 1.4.2 --check
```

Notes:

- Default mode is dry-run and prints unified diffs.
- Use `--apply` to write files.
- Protected paths (`README*`, `AGENTS*`, `docs/**`) are blocked by default.
- Use `--allow-protected-writes` only when you intentionally need to edit protected docs.
- Rule configuration is in `devtools/version_rules.toml`.
