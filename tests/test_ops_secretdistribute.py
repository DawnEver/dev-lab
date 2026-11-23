"""``secretplace distribute``: one entered secret to every account DECLARING the reach, one consent subject."""

from __future__ import annotations

import hashlib
from pathlib import Path

from lab_commons.hpc.grants import Grant

from dev_lab.ops import secretdistribute
from dev_lab.ops.secretdistribute import Plan, Target, distribute, plan, subject

SECRET = b'access_key_id = "a"\nsecret_access_key = "b"\n'


def _grant(user: str, cluster: str = 'clus') -> Grant:
    return Grant(user=user, cluster_name=cluster, hosts=('login.test',), slurm_account='acct', role='research')


def _clone(tmp_path: Path, files: dict[str, str]) -> Path:
    hosts = tmp_path / 'hosts'
    hosts.mkdir(parents=True)
    for name, text in files.items():
        (hosts / f'{name}.toml').write_text(text, encoding='utf-8')
    return tmp_path


REACH = '[storage.reach.results]\ncredentials_file = "~/.secrets/results"\n'


def test_the_plan_takes_only_accounts_that_declare_the_reach(tmp_path: Path) -> None:
    desk = '[dev]\nos = "x"\n' + REACH
    clone = _clone(tmp_path, {'clus-one': REACH, 'clus-two': '[deploy]\nhost = "x"\n', 'desk': desk, 'here': REACH})
    work = plan('results', clone=clone, grants=[_grant('one'), _grant('two')], this_host='here')
    assert [t.grant.user for t in work.accounts] == ['one']  # 'two' declares no reach: never written
    assert work.by_hand == ('desk',)  # this machine is not listed; a workstation is named for its own enter


def test_two_grants_of_one_account_plan_it_once(tmp_path: Path) -> None:
    """An account is a cluster and a user: two Slurm accounts of it are one write (grantslice.own_grants)."""
    clone = _clone(tmp_path, {'clus-one': REACH, 'other-one': REACH})
    second = Grant(user='one', cluster_name='clus', hosts=('login.test',), slurm_account='acct2', role='research')
    work = plan('results', clone=clone, grants=[_grant('one'), second], this_host='here')
    assert [(t.grant.cluster_name, t.grant.user) for t in work.accounts] == [('clus', 'one')]
    # PLANTED CONTROL: the same user on another cluster is another account, planned on its own line
    both = plan('results', clone=clone, grants=[_grant('one'), _grant('one', 'other')], this_host='here')
    assert [(t.grant.cluster_name, t.grant.user) for t in both.accounts] == [('clus', 'one'), ('other', 'one')]


def test_the_subject_binds_every_target_and_the_content() -> None:
    one = Plan('results', (Target(_grant('one'), '~/s'),), ())
    two = Plan('results', (Target(_grant('one'), '~/s'), Target(_grant('two'), '~/s')), ())
    assert subject(one, SECRET) != subject(two, SECRET)
    assert subject(one, SECRET) != subject(one, SECRET + b'x')
    assert SECRET.decode() not in subject(one, SECRET)


class _Account:
    def __init__(self, *, wrong: bool = False) -> None:
        self.seen: list[tuple[str, str | None]] = []
        self.wrong = wrong

    def __call__(self, command: str, stdin: str | None) -> str:
        self.seen.append((command, stdin))
        if 'sha256sum' in command:
            return 'f' * 64 if self.wrong else hashlib.sha256((stdin or '').encode()).hexdigest()
        if 'storage' in command:
            return 'results: reached'
        return '# the machine file\n[deploy]\nhost = "login.test"\nroot = "/r"\n'  # a declared root is absolute


def test_distribute_writes_the_declared_path_and_checks_it() -> None:
    account, said = _Account(), []
    work = Plan('results', (Target(_grant('one'), '~/.secrets/results'),), ('desk',))
    assert distribute(work, SECRET, connect=lambda _g: account, say=said.append) == 0
    write = account.seen[0]
    assert '"$HOME"/.secrets/results' in write[0]
    assert 'umask 077' in write[0]
    assert write[1] == SECRET.decode()  # the value travels on stdin only
    assert all(SECRET.decode() not in line for line in said)
    assert 'placed' in said[0]
    assert 'reached' in said[0]
    assert 'secretplace enter --remote results' in said[1]


def test_a_write_that_does_not_hash_to_the_secret_is_refused() -> None:
    said: list[str] = []
    work = Plan('results', (Target(_grant('one'), '~/s'),), ())
    assert distribute(work, SECRET, connect=lambda _g: _Account(wrong=True), say=said.append) == 2
    assert 'does not hash' in said[0]


def test_an_unreachable_account_is_named_and_the_rest_still_go() -> None:
    def connect(grant: Grant) -> _Account:
        if grant.user == 'down':
            msg = 'no route'
            raise RuntimeError(msg)
        return _Account()

    said: list[str] = []
    work = Plan('results', (Target(_grant('down'), '~/s'), Target(_grant('up'), '~/s')), ())
    assert distribute(work, SECRET, connect=connect, say=said.append) == 2
    assert said[0].startswith('down: refused -- no route')
    assert said[1].startswith('up: placed')


def test_the_module_reuses_the_action_the_issuer_knows() -> None:
    assert secretdistribute.ACTION == 'ops.secret.place'


FAMILY_REACH = """
[storage.remotes.results]
type = "s3"
[storage.remotes.results.reach]
credentials_file = "~/.secrets/results"
"""


def test_a_family_reach_plans_every_account_and_names_the_rest(tmp_path: Path) -> None:
    """Stated once in the family: every reached account, every workstation named, an unreached account named."""
    clone = _clone(tmp_path, {
        'clus-one': '[deploy]\nhost = "x"\n', 'clus-other': '[deploy]\nhost = "y"\n',
        'desk': '[dev]\nos = "x"\n', 'server': '[ops]\nx = 1\n', 'here': '[dev]\n',
    })  # fmt: skip
    (clone / 'family.toml').write_text(FAMILY_REACH, encoding='utf-8')
    work = plan('results', clone=clone, grants=[_grant('one')], this_host='here')
    assert [(t.grant.user, t.path) for t in work.accounts] == [('one', '~/.secrets/results')]
    assert work.by_hand == ('desk',)  # a workstation; the ops server is no workstation
    assert work.unreached == ('clus-other',)
    nothing = plan('other', clone=clone, grants=[_grant('one')], this_host='here')  # PLANTED: no reach, no target
    assert (nothing.accounts, nothing.by_hand, nothing.unreached) == ((), (), ())
