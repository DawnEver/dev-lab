"""One config file plus the environment, and the contradictions it refuses."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.supervise.config import DEFAULTS, load_config


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / 'supervise.toml'
    path.write_text(text, encoding='utf-8')
    return path


def test_a_missing_file_still_yields_every_default(tmp_path: Path) -> None:
    """A daemon must start before its config has been written, so it can report that it has none."""
    config = load_config(tmp_path / 'absent.toml', environ={})
    assert config['cycle']['interval'] == DEFAULTS['cycle']['interval']
    assert config['components'] == {}


def test_the_file_is_merged_over_the_defaults_not_swapped_for_them(tmp_path: Path) -> None:
    """A config naming one field keeps every default it did not name."""
    path = _write(tmp_path, '[cycle]\ninterval = 60\n')
    config = load_config(path, environ={})
    assert config['cycle']['interval'] == 60
    assert config['cycle']['check_timeout'] == DEFAULTS['cycle']['check_timeout']


def test_the_environment_wins_over_the_file(tmp_path: Path) -> None:
    """A deployment overrides; it does not edit the file it deployed."""
    path = _write(tmp_path, '[cycle]\ninterval = 60\n')
    config = load_config(path, environ={'SUPERVISE_CYCLE__INTERVAL': '15'})
    assert config['cycle']['interval'] == 15


def test_an_override_builds_a_nested_key_path(tmp_path: Path) -> None:
    """A double underscore separates the levels, so a deep key needs no special syntax."""
    environ = {'SUPERVISE_ALERTS__EMAIL__SUBJECT_PREFIX': '[wdg] '}
    config = load_config(tmp_path / 'absent.toml', environ=environ)
    assert config['alerts']['email']['subject_prefix'] == '[wdg] '


def test_an_override_addresses_a_key_that_contains_an_underscore(tmp_path: Path) -> None:
    """THE REGRESSION. The separator must not be able to appear inside a key.

    The predecessor split on a single ``_``, so ``..._CYCLE_CHECK_TIMEOUT`` addressed
    ``cycle.check.timeout`` -- a key that did not exist. It was created beside the real
    ``check_timeout``, the override read as applied, and the setting it named was never touched.
    """
    config = load_config(tmp_path / 'absent.toml', environ={'SUPERVISE_CYCLE__CHECK_TIMEOUT': '45'})
    assert config['cycle']['check_timeout'] == 45
    assert 'check' not in config['cycle'], 'the separator split a key that contains one'


def test_an_override_is_cast_to_the_type_it_spells(tmp_path: Path) -> None:
    """A false written as a bool must not arrive as the non-empty string 'false'."""
    environ = {
        'SUPERVISE_ALERTS__EMAIL__ENABLED': 'false',
        'SUPERVISE_CYCLE__CHECK_TIMEOUT': '45',
        'SUPERVISE_TARGET__NAME': 'webapp',
    }
    config = load_config(tmp_path / 'absent.toml', environ=environ)
    assert config['alerts']['email']['enabled'] is False
    assert config['cycle']['check_timeout'] == 45
    assert config['target']['name'] == 'webapp'


def test_a_list_valued_key_is_set_as_a_comma_separated_list(tmp_path: Path) -> None:
    """A list-valued key is split, because an environment variable can only hold a string.

    THE REGRESSION: without the split, `recipients` arrives as one string and the mail path, which
    joins it, addresses the message to its CHARACTERS.
    """
    environ = {'SUPERVISE_ALERTS__EMAIL__RECIPIENTS': 'a@example.org, b@example.org'}
    config = load_config(tmp_path / 'absent.toml', environ=environ)
    assert config['alerts']['email']['recipients'] == ['a@example.org', 'b@example.org']


def test_a_single_recipient_is_still_a_list(tmp_path: Path) -> None:
    """One address is the common case and must not become a string that iterates into letters."""
    environ = {'SUPERVISE_ALERTS__EMAIL__RECIPIENTS': 'only@example.org'}
    config = load_config(tmp_path / 'absent.toml', environ=environ)
    assert config['alerts']['email']['recipients'] == ['only@example.org']


def test_a_variable_without_the_prefix_is_ignored(tmp_path: Path) -> None:
    """The namespace is the prefix; the rest of the environment is not ours to read."""
    config = load_config(tmp_path / 'absent.toml', environ={'HOME': '/root', 'WATCH_CYCLE__INTERVAL': '7'})
    assert config['cycle']['interval'] == DEFAULTS['cycle']['interval']


def test_a_second_prefix_can_be_used(tmp_path: Path) -> None:
    """Two supervisors on one host set different prefixes rather than sharing a namespace."""
    config = load_config(tmp_path / 'absent.toml', environ={'OPS_CYCLE__INTERVAL': '9'}, prefix='OPS_')
    assert config['cycle']['interval'] == 9


def test_loading_does_not_let_one_config_mutate_the_next(tmp_path: Path) -> None:
    """The defaults are a module constant; a run that appends to a list must not change them."""
    config = load_config(tmp_path / 'absent.toml', environ={})
    config['alerts']['email']['recipients'].append('leaked@example.org')
    fresh = load_config(tmp_path / 'absent.toml', environ={})
    assert fresh['alerts']['email']['recipients'] == []
    assert DEFAULTS['alerts']['email']['recipients'] == []


def test_the_config_records_where_it_came_from(tmp_path: Path) -> None:
    """A refusal that cannot name its file sends a reader to the wrong one."""
    path = tmp_path / 'absent.toml'
    assert load_config(path, environ={})['_config_path'] == str(path)


def test_an_email_channel_with_no_recipients_is_refused(tmp_path: Path) -> None:
    """Enabled with nowhere to send is every alert silently dropped."""
    path = _write(tmp_path, "[alerts.email]\nenabled = true\nsender = 'supervise@example.org'\n")
    with pytest.raises(ValueError, match='recipients'):
        load_config(path, environ={})


def test_an_smtp_channel_with_no_sender_is_refused(tmp_path: Path) -> None:
    """A relay refuses a message with no envelope sender, so this must not reach one."""
    path = _write(tmp_path, "[alerts.email]\nenabled = true\nrecipients = ['ops@example.org']\n")
    with pytest.raises(ValueError, match='sender'):
        load_config(path, environ={})


def test_a_disabled_channel_is_not_validated(tmp_path: Path) -> None:
    """A channel nobody turned on is allowed to be half-written."""
    path = _write(tmp_path, '[alerts.email]\nenabled = false\n')
    assert load_config(path, environ={})['alerts']['email']['enabled'] is False


def test_a_telegram_channel_missing_its_chat_is_refused(tmp_path: Path) -> None:
    """A token with no chat posts nowhere, and would fail at the first anomaly."""
    path = _write(tmp_path, "[alerts.telegram]\nenabled = true\ntoken = 'x'\n")
    with pytest.raises(ValueError, match='token or its chat'):
        load_config(path, environ={})


def test_a_webhook_on_plain_http_is_refused(tmp_path: Path) -> None:
    """A URL the channel will always refuse must not load as though it were configured.

    The transport refuses plain HTTP because a webhook's configured headers carry a secret. Left
    to the send path, that refusal would arrive as a failed delivery on the first anomaly -- a
    config that reads as set and does nothing. Refused here, it names itself.
    """
    path = _write(tmp_path, "[alerts.webhook]\nenabled = true\nurl = 'http://hooks.example.org/x'\n")
    with pytest.raises(ValueError, match='not https'):
        load_config(path, environ={})


def test_a_webhook_over_https_is_accepted(tmp_path: Path) -> None:
    """Refusing plain HTTP must not refuse the case the channel exists for."""
    path = _write(tmp_path, "[alerts.webhook]\nenabled = true\nurl = 'https://hooks.example.org/x'\n")
    assert load_config(path, environ={})['alerts']['webhook']['enabled'] is True


def test_a_disabled_webhook_is_not_validated(tmp_path: Path) -> None:
    """A channel nobody turned on is allowed to be half-written."""
    path = _write(tmp_path, "[alerts.webhook]\nenabled = false\nurl = 'http://hooks.example.org/x'\n")
    assert load_config(path, environ={})['alerts']['webhook']['enabled'] is False


@pytest.mark.parametrize('interval', ['0', '-5'])
def test_a_non_positive_interval_is_refused(tmp_path: Path, interval: str) -> None:
    """An interval of zero is a supervisor that polls as fast as it can, which is a livelock."""
    path = _write(tmp_path, f'[cycle]\ninterval = {interval}\n')
    with pytest.raises(ValueError, match='positive integer'):
        load_config(path, environ={})
