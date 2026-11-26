"""A render-golden fixture in code: pyproject, role bindings, deltas -- representative, not any real repo's."""

from __future__ import annotations

from dev_lab.dev.famconfig import Delta

#: The fixture's ``pyproject.toml``: its ``[tool.dev_lab.ci]`` declarations.
PYPROJECT = """\
# A GitHub repo layering its own job permissions over the base CI, and its own ignore lines.
[project]
name = "overrides"

[tool.dev_lab.ci."ci.yml".jobs.review.permissions]
issues = "read"
"""
#: The executor kind each role binds, as :data:`~dev_lab.dev.roles.ROLES_ENV` carries them.
ROLES = {'merge': 'ci', 'promote': 'ci', 'prune': 'ci', 'review': 'ci', 'tests': 'ci'}

DELTAS = {
    '.gitignore': Delta(repo='overrides', added=('/data/', '*.h5'), dropped={}, ceiling=2),
    '.gitattributes': Delta(repo='overrides', added=('*.h5 binary',), dropped={}, ceiling=1),
}
