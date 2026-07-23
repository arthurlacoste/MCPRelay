from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_pr_body", ROOT / "scripts/validate_pr_body.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

VALID = """## Summary
Fix startup behavior.

## Changes
- Use the venv interpreter.

## Testing
- `pytest -q`

## AI assistance
Application: ChatGPT
Model: GPT-5.6 Thinking
"""


def test_valid_body_passes():
    assert module.validate(VALID) == []


def test_missing_sections_and_ai_metadata_fail():
    errors = module.validate("## Summary\nSomething")
    assert "Missing section: ## Changes" in errors
    assert "Missing AI field: Application: <value>" in errors


def test_placeholder_only_body_fails():
    body = (ROOT / ".github/PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    errors = module.validate(body)
    assert "Section is empty: ## Summary" in errors
    assert "Missing AI field: Model: <value>" in errors
