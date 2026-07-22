import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from fastmcp import Client
from environment_config import load_gateway_environment
from skill_catalog import MAX_FILE_BYTES, get_skills_root, skills_read, skills_search
import mcp_gateway as gateway
from tool_metadata import TOOL_METADATA


def write_skill(root: Path, skill_id: str, name='Example', description='Example workflow', body='Steps') -> Path:
    package = root / skill_id
    package.mkdir(parents=True, exist_ok=True)
    path = package / 'SKILL.md'
    path.write_text(
        f'---\nname: {name}\ndescription: {description}\n---\n\n{body}\n',
        encoding='utf-8',
    )
    return path


def test_config_env_overrides_default_root(monkeypatch, tmp_path):
    skills_root = tmp_path / 'skills'
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    (config_dir / '.env').write_text(f'MCP_SKILLS_ROOT={skills_root}\n', encoding='utf-8')
    monkeypatch.delenv('MCP_CONFIG_ROOT', raising=False)
    monkeypatch.delenv('MCP_SKILLS_ROOT', raising=False)
    assert load_gateway_environment(tmp_path) is True
    assert get_skills_root() == skills_root


def test_default_root_and_environment_override(monkeypatch, tmp_path):
    monkeypatch.delenv('MCP_SKILLS_ROOT', raising=False)
    assert get_skills_root() == Path('~/.gate/skills').expanduser()
    monkeypatch.setenv('MCP_SKILLS_ROOT', '~/custom-skills')
    assert get_skills_root() == Path('~/custom-skills').expanduser()
    monkeypatch.setenv('MCP_SKILLS_ROOT', str(tmp_path))
    assert get_skills_root() == tmp_path


def test_missing_root_is_empty_and_not_created(tmp_path):
    root = tmp_path / 'missing'
    result = skills_search(root=root)
    assert result['matches'] == []
    assert result['total'] == 0
    assert result['warnings'] == [{
        'code': 'root_missing',
        'message': 'Skills root does not exist. Set MCP_SKILLS_ROOT or create ~/.gate/skills.',
        'path': str(root),
    }]
    assert not root.exists()


def test_recursive_discovery_refreshes_without_restart(tmp_path):
    write_skill(tmp_path, 'nested/alpha', name='Alpha')
    assert [item['id'] for item in skills_search(root=tmp_path)['matches']] == ['nested/alpha']
    write_skill(tmp_path, 'beta', name='Beta')
    assert [item['id'] for item in skills_search(root=tmp_path)['matches']] == ['nested/alpha', 'beta']
    (tmp_path / 'nested/alpha/SKILL.md').unlink()
    assert [item['id'] for item in skills_search(root=tmp_path)['matches']] == ['beta']


def test_frontmatter_multiline_invalid_and_duplicate_names(tmp_path):
    write_skill(tmp_path, 'one', name='Duplicate', description='First')
    write_skill(tmp_path, 'two', name='Duplicate', description='Second')
    package = tmp_path / 'multi'
    package.mkdir()
    (package / 'SKILL.md').write_text(
        '---\nname: Multiline\ndescription: |\n  First line\n  second line\n---\nBody', encoding='utf-8'
    )
    invalid = tmp_path / 'invalid'
    invalid.mkdir()
    (invalid / 'SKILL.md').write_text('---\nname: [broken\n---\n', encoding='utf-8')

    result = skills_search(root=tmp_path, limit=50)
    assert {item['id'] for item in result['matches']} == {'one', 'two', 'multi'}
    assert [item['name'] for item in result['matches']].count('Duplicate') == 2
    assert next(item for item in result['matches'] if item['id'] == 'multi')['description'] == 'First line\nsecond line'
    warning = next(item for item in result['warnings'] if item['path'] == 'invalid/SKILL.md')
    assert warning['code'] == 'invalid_skill'
    assert 'invalid YAML frontmatter' in warning['message']


def test_search_ranking_pagination_and_limit_bounds(tmp_path):
    write_skill(tmp_path, 'deploy', name='Release', description='Ship software')
    write_skill(tmp_path, 'ops/deploy-check', name='Deployment check', description='Validate release')
    write_skill(tmp_path, 'notes', name='Notes', description='Deployment documentation')

    result = skills_search('deploy', root=tmp_path, limit=1)
    assert result['matches'][0]['id'] == 'deploy'
    assert result['total'] == 3
    assert result['has_more'] is True
    second = skills_search('deploy', root=tmp_path, limit=1, offset=1)
    assert second['matches'][0]['id'] == 'ops/deploy-check'
    assert len(skills_search(root=tmp_path, limit=0)['matches']) == 1
    assert skills_search(root=tmp_path, limit=500)['total'] == 3


def test_symlinked_skill_package_is_discovered_and_read_safely(tmp_path):
    external = tmp_path / 'external'
    external.mkdir()
    target = write_skill(external, 'diagnose', name='Diagnose')
    (target.parent / 'guide.txt').write_text('guide', encoding='utf-8')
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'diagnose').symlink_to(target.parent, target_is_directory=True)

    result = skills_search(root=root)
    assert [item['id'] for item in result['matches']] == ['diagnose']
    assert skills_read('diagnose', 'guide.txt', root=root)['content'] == 'guide'

    outside = tmp_path / 'secret.txt'
    outside.write_text('secret', encoding='utf-8')
    (target.parent / 'escape.txt').symlink_to(outside)
    with pytest.raises(ValueError, match='outside the skill package'):
        skills_read('diagnose', 'escape.txt', root=root)


def test_read_skill_and_relative_text_reference(tmp_path):
    skill_file = write_skill(tmp_path, 'nested/example')
    reference = skill_file.parent / 'references' / 'guide.txt'
    reference.parent.mkdir()
    reference.write_text('Reference text', encoding='utf-8')

    skill = skills_read('nested/example', root=tmp_path)
    assert skill['path'] == 'SKILL.md'
    assert skill['content'].startswith('---')
    assert skill['files'] == ['SKILL.md', 'references/guide.txt']
    assert skills_read('nested/example', 'references/guide.txt', root=tmp_path)['content'] == 'Reference text'


@pytest.mark.parametrize('path', ['../outside.txt', '/tmp/outside.txt', './SKILL.md'])
def test_read_rejects_unsafe_paths(tmp_path, path):
    write_skill(tmp_path, 'example')
    with pytest.raises(ValueError):
        skills_read('example', path, root=tmp_path)



@pytest.mark.parametrize('skill_id', [
    '', '.', '..', '../example', '/example', 'nested//example', 'nested\\example', './example',
])
def test_read_rejects_invalid_skill_ids(tmp_path, skill_id):
    write_skill(tmp_path, 'example')
    with pytest.raises(ValueError, match='skill_id'):
        skills_read(skill_id, root=tmp_path)

def test_read_rejects_directory_binary_large_and_outbound_symlink(tmp_path):
    package = write_skill(tmp_path, 'example').parent
    (package / 'folder').mkdir()
    (package / 'binary.dat').write_bytes(b'abc\x00def')
    (package / 'utf8-binary.dat').write_bytes(b'valid utf8\x01payload')
    (package / 'large.txt').write_bytes(b'x' * (MAX_FILE_BYTES + 1))
    outside = tmp_path / 'outside.txt'
    outside.write_text('secret')
    (package / 'link.txt').symlink_to(outside)

    for path in ('folder', 'binary.dat', 'utf8-binary.dat', 'large.txt', 'link.txt'):
        with pytest.raises(ValueError):
            skills_read('example', path, root=tmp_path)


def test_fastmcp_exposes_instructions_skill_tools_and_metadata(monkeypatch, tmp_path):
    write_skill(tmp_path, 'example')
    monkeypatch.setenv('MCP_SKILLS_ROOT', str(tmp_path))

    async def scenario():
        async with Client(gateway.mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            result = await client.call_tool('skills_search', {})
            return client.initialize_result, tools, result.structured_content or result.data

    initialized, tools, result = asyncio.run(scenario())
    assert initialized.instructions.startswith('Before handling a complex or repeatable task')
    assert len(initialized.instructions[:512]) == len(initialized.instructions)
    assert result['matches'][0]['id'] == 'example'
    for name in ('skills_search', 'skills_read'):
        tool = tools[name]
        assert tool.title
        assert tool.description
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is False
    assert set(TOOL_METADATA) <= set(tools)
    for name in TOOL_METADATA:
        tool = tools[name]
        assert tool.title
        assert tool.description
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is not None
        assert tool.annotations.destructiveHint is not None
        assert tool.annotations.idempotentHint is not None
        assert tool.annotations.openWorldHint is not None


def test_skill_tools_can_be_disabled_through_registry(tmp_path):
    config = tmp_path / 'tools.toml'
    config.write_text('[tools]\nskills_search = false\nskills_read = false\n')
    script = '''
import asyncio, sys
sys.path.insert(0, 'src')
from fastmcp import Client
from environment_config import load_gateway_environment
import mcp_gateway
async def main():
    async with Client(mcp_gateway.mcp) as client:
        print(','.join(sorted(tool.name for tool in await client.list_tools())))
asyncio.run(main())
'''
    env = os.environ.copy()
    env['MCP_TOOLS_CONFIG'] = str(config)
    completed = subprocess.run(
        [sys.executable, '-c', script], cwd=Path(__file__).resolve().parent.parent,
        env=env, text=True, capture_output=True, check=True,
    )
    names = completed.stdout.strip().split(',')
    assert 'skills_search' not in names
    assert 'skills_read' not in names
