"""The runtime source has one graph identity, not a consumer-conflicting branch variant."""

import tomllib
from pathlib import Path


def test_the_runtime_source_and_lock_use_the_same_bare_git_identity() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    source = manifest['tool']['uv']['sources']['lab-commons']
    assert set(source) == {'git'}, 'a branch override conflicts with downstream bare-URL requirements'
    lock = tomllib.loads((root / 'uv.lock').read_text(encoding='utf-8'))
    (runtime,) = [package for package in lock['package'] if package['name'] == 'lab-commons']
    url, separator, commit = runtime['source']['git'].partition('#')
    assert url == source['git']
    assert separator == '#'
    assert len(commit) == 40
