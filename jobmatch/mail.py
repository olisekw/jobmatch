"""SMTP transport — the one place in the app that talks to a mail server.

Split from `jobmatch.digest` for the same reason `obs.py` is split from the two
entrypoints: *what* to say and *how it leaves the building* are different
problems, and only one of them needs a socket. `digest.py` builds a subject and
two bodies; this module knows about ports, TLS and credentials, and nothing
about jobs.

**Unconfigured is the normal case.** No `SMTP_HOST` means `configured()` is
False, the worker skips the digest pass entirely and Settings says so — exactly
how `SENTRY_DSN` behaves in `obs.py`. Mail is never a startup dependency: a
relay that is down must cost a digest, not the scanner.

`send()` raises whatever smtplib raises. Deciding what a failed delivery means
belongs to the caller — for the digest it means "leave the jobs unmarked and
try tomorrow", which is not a decision a transport should be making.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import config

log = logging.getLogger("jobmatch.mail")


def configured():
    """Can this instance send mail at all?

    A host with no From: address is not configured: every relay rejects a
    message without a sender, so answering True would only move the failure to
    delivery time, where it is somebody's missing email rather than a line in
    the log at boot.
    """
    return bool(config.SMTP_HOST and config.MAIL_FROM)


def sender():
    """The From: header — `JobMatch <bot@example.com>`."""
    return formataddr((config.MAIL_FROM_NAME, config.MAIL_FROM))


def build(to, subject, text, html=None, headers=None):
    """One message, plain text with an optional HTML alternative.

    The plain part is written first and is never a stripped-down afterthought:
    it is what a terminal client, a screen reader and every spam filter reads,
    and `set_content` before `add_alternative` is what puts it first in the
    multipart/alternative — clients render the *last* part they understand.
    """
    message = EmailMessage()
    message["From"] = sender()
    message["To"] = to
    message["Subject"] = subject
    for name, value in (headers or {}).items():
        message[name] = value
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def _transport():
    """A connected, authenticated SMTP session.

    Port 465 is implicit TLS (the socket is encrypted before a byte of SMTP);
    587 is plaintext until STARTTLS upgrades it. Getting the pair the wrong way
    round is the usual reason a relay hangs up, so both are configurable and
    each defaults off the other — see `config.SMTP_SSL`.
    """
    context = ssl.create_default_context()
    if config.SMTP_SSL:
        smtp = smtplib.SMTP_SSL(
            config.SMTP_HOST, config.SMTP_PORT,
            timeout=config.SMTP_TIMEOUT, context=context,
        )
    else:
        smtp = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT)
        if config.SMTP_STARTTLS:
            smtp.starttls(context=context)
            smtp.ehlo()
    if config.SMTP_USER:
        smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
    return smtp


def send(to, subject, text, html=None, headers=None):
    """Deliver one message. Returns the recipient; raises on any failure.

    Deliberately one connection per message. The digest sends a handful of
    mails a day and a pooled session that has been idle since yesterday is a
    dead socket at the worst moment — the same reasoning that gave the worker a
    connection per pass rather than one for the life of the process.
    """
    if not configured():
        raise RuntimeError("no SMTP_HOST is configured — mail cannot be sent")
    message = build(to, subject, text, html=html, headers=headers)
    with _transport() as smtp:
        smtp.send_message(message)
    log.info("sent %r to %s", subject, to)
    return to
