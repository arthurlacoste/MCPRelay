import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_please_manifest_matches_gate_version():
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert manifest == {".": version}


def test_release_please_updates_version_and_uses_gate_tags():
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    package = config["packages"]["."]

    assert config["release-type"] == "simple"
    assert config["include-v-in-tag"] is True
    assert config["include-component-in-tag"] is False
    assert config["draft"] is True
    assert package["package-name"] == "gate"
    assert package["version-file"] == "VERSION"
    assert {section["type"] for section in package["changelog-sections"]} >= {
        "feat", "fix", "security", "test", "ci",
    }


def test_release_workflow_creates_release_and_uploads_verified_assets():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "googleapis/release-please-action@v5" in workflow
    assert "Configure the RELEASE_PLEASE_TOKEN repository secret" in workflow
    assert "token: ${{ secrets.RELEASE_PLEASE_TOKEN }}" in workflow
    assert "|| github.token" not in workflow
    assert "branches:\n      - main" in workflow
    assert "tags:" not in workflow
    assert "needs.release-please.outputs.release_created == 'true'" in workflow
    assert "ref: ${{ needs.release-please.outputs.tag_name }}" in workflow
    assert 'test "v$(tr -d \'\\n\' < VERSION)" = "$TAG_NAME"' in workflow
    assert 'git archive --format=tar.gz' in workflow
    assert 'gh release upload "$TAG_NAME"' in workflow
    assert 'gh release edit "$TAG_NAME" --draft=false' in workflow
    assert workflow.index('gh release upload "$TAG_NAME"') < workflow.index('gh release edit "$TAG_NAME" --draft=false')
    assert "SHA256SUMS" in workflow


def test_release_please_pull_requests_skip_human_pr_body_validation():
    workflow = (ROOT / ".github" / "workflows" / "pr-body.yml").read_text(encoding="utf-8")

    assert "autorelease: pending" in workflow
    assert "!contains(github.event.pull_request.labels.*.name" in workflow
    assert "!startsWith(github.head_ref, 'release-please--branches--')" in workflow
