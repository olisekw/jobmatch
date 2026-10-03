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
from email.utils import formataddr, formatdate, make_msgid

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


def domain():
    """The name this client answers to: EHLO, and the right of the Message-ID.

    The From: domain, because the alternative is whatever the machine calls
    itself — and in a container that is a 12-hex hostname with no domain in it,
    which smtplib replaces with a bare `[172.18.0.4]`. A private address
    literal, in every relay's log, on every message we ever send.
    """
    return config.MAIL_DOMAIN or config.MAIL_FROM.rpartition("@")[2]


def build(to, subject, text, html=None, headers=None):
    """One message, plain text with an optional HTML alternative.

    The plain part is written first and is never a stripped-down afterthought:
    it is what a terminal client, a screen reader and every spam filter reads,
    and `set_content` before `add_alternative` is what puts it first in the
    multipart/alternative — clients render the *last* part they understand.

    **`Date` and `Message-ID` are ours to write, not the relay's to supply.**
    Neither `EmailMessage` nor `smtplib` adds one, so every digest built before
    this left without either: `Date` is one of the two headers RFC 5322 makes
    mandatory, and a missing `Message-ID` is on Gmail's own list of things a
    bulk sender must not do. Most relays paper over both, which is exactly why
    it would never have been noticed until one did not.

    **The bodies are encoded 7-bit clean**, because nothing here can announce
    otherwise: `smtplib.send_message` only adds `BODY=8BITMIME` to the envelope
    when an *address* needs UTF-8, so the default `Content-Transfer-Encoding:
    8bit` put raw bytes on the wire under an envelope that never declared them.
    A relay without the extension is entitled to strip the high bit or refuse
    the message — and on this board every second Slovak title carries an á.
    """
    message = EmailMessage()
    message["From"] = sender()
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(usegmt=True)
    message["Message-ID"] = make_msgid(domain=domain() or None)
    # RFC 3834: this is a robot. Keeps out-of-office replies from bouncing back
    # at an address nobody reads, and tells a filter what it is looking at.
    message["Auto-Submitted"] = "auto-generated"
    for name, value in (headers or {}).items():
        message[name] = value
    message.set_content(text, cte="quoted-printable")
    if html:
        message.add_alternative(html, subtype="html", cte="quoted-printable")
    return message


def _transport():
    """A connected, authenticated SMTP session.

    Port 465 is implicit TLS (the socket is encrypted before a byte of SMTP);
    587 is plaintext until STARTTLS upgrades it. Getting the pair the wrong way
    round is the usual reason a relay hangs up, so both are configurable and
    each defaults off the other — see `config.SMTP_SSL`.
    """
    context = ssl.create_default_context()
    helo = domain() or None
    if config.SMTP_SSL:
        smtp = smtplib.SMTP_SSL(
            config.SMTP_HOST, config.SMTP_PORT, local_hostname=helo,
            timeout=config.SMTP_TIMEOUT, context=context,
        )
    else:
        smtp = smtplib.SMTP(
            config.SMTP_HOST, config.SMTP_PORT, local_hostname=helo,
            timeout=config.SMTP_TIMEOUT,
        )
        if config.SMTP_STARTTLS:
            smtp.starttls(context=context)
            smtp.ehlo()
    if config.SMTP_USER:
        # Asked of the socket, not of the settings: "we turned TLS on" and "this
        # connection is encrypted" are the same thing only when STARTTLS was
        # actually offered and accepted, and the password is what is at stake.
        if not isinstance(smtp.sock, ssl.SSLSocket) and not config.SMTP_ALLOW_INSECURE_AUTH:
            smtp.close()
            raise RuntimeError(
                "refusing to send SMTP credentials over an unencrypted connection — "
                "set SMTP_STARTTLS=true (port 587) or SMTP_SSL=true (port 465), "
                "or SMTP_ALLOW_INSECURE_AUTH=true if the relay really is local"
            )
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
