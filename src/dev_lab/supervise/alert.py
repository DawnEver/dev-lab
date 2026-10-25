"""How a notice reaches a human: four channels, one shape, and no reason to raise.

A supervision run that finds something wrong and cannot say so has done nothing. The predecessor
had this right in outline -- one transport module, channels gated by their own ``enabled`` -- and
wrong in three details this fixes:

* it sent HTML. A deployment alert is a line of text and a link; markup buys nothing and adds an
  escaping bug between a commit subject and a mail client. Everything here is plain text.
* it built its own failure paths so a channel that threw took the others down with it. Each channel
  is delivered independently and reports its own outcome, so one broken webhook cannot silence the
  email beside it.
* its ``urlopen`` carried no verification. The connection goes through an injected ``Transport``
  over :mod:`http.client`, which is this family's established spelling and the reason it exists.

NOTHING HERE DECIDES WHETHER TO SEND. Throttling, deduplication, cooldown and escalation belong to
:mod:`dev_lab.supervise.policy`; a transport that also suppressed would put the rule in two
places, and the predecessor's did exactly that -- half the suppression lived in its state module and
half in its alert module, which is why neither could be read on its own.
"""

from __future__ import annotations

import http.client
import json
import smtplib
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Final

from dev_lab.supervise.transport import BODY_CAP, OK_CEILING, OK_FLOOR, REPLY_KEPT, Transport, https_only, split_url
from dev_lab.supervise.verdict import Severity

__all__ = ['Delivery', 'Notice', 'Notifier', 'Transport']

#: How long a channel is given. Bounded because an alert that blocks is worse than an alert that
#: fails: the cycle it is holding is the one that would have retried.
_TIMEOUT: Final = 15

#: Telegram's API host, and the one path this module posts to.
_TELEGRAM_HOST: Final = 'api.telegram.org'
_RESEND_HOST: Final = 'api.resend.com'

#: What counts as a channel having taken the notice comes from `transport.OK_FLOOR`/`OK_CEILING`.
#: This module kept a private second pair of the same two numbers, which is how two readers of the
#: same rule drift: one of them gets a reason and the other does not.

#: How much of a channel's reply is kept came from here as a second copy of
#: :data:`dev_lab.supervise.transport.REPLY_KEPT`, and the copy is what let the two readers
#: disagree: `transport` was changed to read its body TO A CAP and this one went on calling
#: ``response.read()`` with no argument, which reads to EOF. Two constants that agree today are not
#: one fact, and the second one carried no reason for its number.


@dataclass(frozen=True)
class Notice:
    """One thing to tell a human.

    Attributes:
        subject: one line naming what happened.
        body: the detail, as plain text.
        severity: how loudly this should read.

    """

    subject: str
    body: str
    severity: Severity = Severity.WARNING

    def as_text(self) -> str:
        """Render the notice for a channel with no subject field.

        Returns:
            The severity, the subject and the body, in that order.

        """
        return f'[{self.severity.value.upper()}] {self.subject}\n\n{self.body}'


@dataclass(frozen=True)
class Delivery:
    """What one channel did with a notice.

    Attributes:
        channel: which channel, so a partial failure names itself.
        ok: whether it was handed over.
        detail: what the channel said, for a log line.

    """

    channel: str
    ok: bool
    detail: str = ''


@dataclass(frozen=True)
class Notifier:
    """Deliver a notice to every channel the configuration enabled.

    Attributes:
        config: the merged configuration, read for its ``alerts`` table.
        transport: how a connection is made. Defaults to the one that refuses plain HTTP, because
            every channel that carries a credential goes through it.

    """

    config: Mapping[str, Any]
    transport: Transport = https_only

    def send(self, notice: Notice) -> list[Delivery]:
        """Deliver *notice* to each enabled channel, independently.

        Args:
            notice: what to send.

        Returns:
            One delivery per enabled channel, in a fixed order. An empty list means nothing was
            enabled, which is a configuration a caller may want to report rather than an error.

        """
        alerts = self.config.get('alerts', {})
        deliveries: list[Delivery] = []
        email = alerts.get('email', {})
        if email.get('enabled'):
            deliveries.append(self._email(notice, email))
        telegram = alerts.get('telegram', {})
        if telegram.get('enabled'):
            deliveries.append(self._telegram(notice, telegram))
        webhook = alerts.get('webhook', {})
        if webhook.get('enabled'):
            deliveries.append(self._webhook(notice, webhook))
        return deliveries

    def _email(self, notice: Notice, cfg: Mapping[str, Any]) -> Delivery:
        """Deliver over the configured mail method.

        Args:
            notice: what to send.
            cfg: the ``alerts.email`` table.

        Returns:
            What the channel did.

        """
        if cfg.get('method', 'smtp') == 'resend':
            return self._resend(notice, cfg)
        return self._smtp(notice, cfg)

    def _message(self, notice: Notice, cfg: Mapping[str, Any]) -> EmailMessage:
        """Build the message both mail methods send.

        Args:
            notice: what to send.
            cfg: the ``alerts.email`` table.

        Returns:
            A plain-text message with the configured prefix on its subject.

        """
        message = EmailMessage()
        message['Subject'] = f'{cfg.get("subject_prefix", "")}{notice.subject}'.strip()
        message['From'] = str(cfg.get('sender', ''))
        message['To'] = ', '.join(str(one) for one in cfg.get('recipients', []))
        message.set_content(notice.body)
        return message

    def _smtp(self, notice: Notice, cfg: Mapping[str, Any]) -> Delivery:
        """Relay the message through the configured SMTP host.

        Args:
            notice: what to send.
            cfg: the ``alerts.email`` table.

        Returns:
            What the relay did.

        """
        message = self._message(notice, cfg)
        try:
            with smtplib.SMTP(str(cfg.get('host', 'localhost')), int(cfg.get('port', 25)), timeout=_TIMEOUT) as relay:
                if cfg.get('use_tls'):
                    relay.starttls()
                if cfg.get('username'):
                    relay.login(str(cfg['username']), str(cfg.get('password', '')))
                relay.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            return Delivery(channel='email', ok=False, detail=f'smtp: {exc}')
        return Delivery(channel='email', ok=True)

    def _resend(self, notice: Notice, cfg: Mapping[str, Any]) -> Delivery:
        """Post the message to Resend's API.

        ``resend`` is imported here rather than at the top of the module because it is an optional
        dependency: a target that relays over SMTP must not need it installed to import this file.

        Args:
            notice: what to send.
            cfg: the ``alerts.email`` table.

        Returns:
            What the API did.

        """
        payload = {
            'from': str(cfg.get('sender', '')),
            'to': [str(one) for one in cfg.get('recipients', [])],
            'subject': f'{cfg.get("subject_prefix", "")}{notice.subject}'.strip(),
            'text': notice.body,
        }
        return self._post(
            'email',
            'https',
            _RESEND_HOST,
            '/emails',
            payload,
            headers={'Authorization': f'Bearer {cfg.get("api_key", "")}'},
        )

    def _telegram(self, notice: Notice, cfg: Mapping[str, Any]) -> Delivery:
        """Post the notice to a Telegram chat.

        Args:
            notice: what to send.
            cfg: the ``alerts.telegram`` table.

        Returns:
            What the API did.

        """
        payload = {'chat_id': str(cfg.get('chat', '')), 'text': notice.as_text()}
        path = f'/bot{cfg.get("token", "")}/sendMessage'
        return self._post('telegram', 'https', _TELEGRAM_HOST, path, payload, headers={})

    def _webhook(self, notice: Notice, cfg: Mapping[str, Any]) -> Delivery:
        """Post the notice to a webhook.

        Args:
            notice: what to send.
            cfg: the ``alerts.webhook`` table.

        Returns:
            What the endpoint did.

        """
        payload = {'text': notice.as_text(), 'subject': notice.subject, 'severity': notice.severity.value}
        try:
            scheme, host, path = split_url(str(cfg.get('url', '')))
        except ValueError as exc:
            return Delivery(channel='webhook', ok=False, detail=str(exc))
        headers = {str(k): str(v) for k, v in (cfg.get('headers') or {}).items()}
        return self._post('webhook', scheme, host, path, payload, headers=headers)

    def _post(
        self,
        channel: str,
        scheme: str,
        host: str,
        path: str,
        payload: Mapping[str, object],
        *,
        headers: Mapping[str, str],
    ) -> Delivery:
        """POST a JSON body and report what came back.

        Args:
            channel: the channel's name, for the delivery.
            scheme: the URL's scheme, which the transport needs to choose a connection class.
            host: the host to reach.
            path: the request path.
            payload: the JSON body.
            headers: extra request headers.

        Returns:
            What the endpoint did. A connection that failed is a delivery that failed, never an
            exception: the other channels still have to be told.

        """
        body = json.dumps(payload).encode('utf-8')
        try:
            connection = self.transport(scheme, host, _TIMEOUT)
            try:
                connection.request('POST', path, body=body, headers={'Content-Type': 'application/json', **headers})
                response = connection.getresponse()
                # READ TO A CAP, NOT TO EOF. This call had no argument, so a channel that dribbles a
                # body -- slowly, or in chunks -- is read into THIS process's memory until it stops,
                # and this process is the supervisor, whose own cgroup is 300M. The identical defect
                # was fixed in `transport.fetch_json` and left standing here, because the two were
                # written as two constants that happened to hold the same number.
                detail = response.read(BODY_CAP).decode('utf-8', 'replace')[:REPLY_KEPT]
                ok = OK_FLOOR <= response.status < OK_CEILING
                return Delivery(channel=channel, ok=ok, detail=detail)
            finally:
                connection.close()
        except (OSError, ValueError, http.client.HTTPException) as exc:
            return Delivery(channel=channel, ok=False, detail=f'{type(exc).__name__}: {exc}')
