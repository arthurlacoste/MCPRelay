#!/usr/bin/env python3
"""Validate the repository pull-request body contract."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = ("Summary", "Changes", "Testing", "AI assistance")
PLACEHOLDER_MARKERS = ("<!--", "-->")


def section(body: str, name: str) -> str | None:
    match = re.search(
        rf"^##[ \t]+{re.escape(name)}[ \t]*$\n(.*?)(?=^##[ \t]+|\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def meaningful(value: str | None) -> bool:
    if not value:
        return False
    cleaned = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    cleaned = re.sub(r"^[ \t]*[-*][ \t]*\[[ xX]\][ \t]*.*$", "", cleaned, flags=re.MULTILINE)
    return bool(cleaned.strip())


def validate(body: str) -> list[str]:
    errors: list[str] = []
    sections = {name: section(body, name) for name in REQUIRED_SECTIONS}
    for name, content in sections.items():
        if content is None:
            errors.append(f"Missing section: ## {name}")
        elif not meaningful(content):
            errors.append(f"Section is empty: ## {name}")

    ai = sections.get("AI assistance") or ""
    for field in ("Application", "Model"):
        match = re.search(rf"^{field}:[ \t]*(.+)$", ai, flags=re.MULTILINE | re.IGNORECASE)
        if not match or not meaningful(match.group(1)):
            errors.append(f"Missing AI field: {field}: <value>")

    testing = sections.get("Testing") or ""
    if meaningful(testing) and testing.strip().lower() in {"ci", "tests", "passed", "n/a"}:
        errors.append("Testing must list exact commands or explain why tests do not apply")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    body = args.path.read_text(encoding="utf-8")
    errors = validate(body)
    if errors:
        print("Pull request body does not match the required structure:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Pull request body structure: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
