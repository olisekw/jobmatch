"""The SMTP transport, driven against a real SMTP server.

`tests/test_digest.py` replaces `mail.send` with a recorder, which is right for
asking *what the digest says* — but it means that until this file, nothing in
the suite had ever built an `EmailMessage` and put it on a socket. Everything
below the recorder was unproven: the TLS modes, the credentials, the envelope,
and every byte of the message as a relay would actually receive it.

So `Sink` is a real SMTP server — small, but it speaks the protocol: EHLO,
STARTTLS, AUTH, MAIL FROM, RCPT TO, DATA. It records the envelope, whether the
socket was encrypted when each command arrived, and the raw bytes of the
message. The assertions are made against *what arrived*, never against the
`EmailMessage` object, because the object is the half that was never in doubt.

Three defects were found by writing it, each of which a relay would have hidden
until one did not: no `Date` and no `Message-ID` on any message we have ever
sent; a `Content-Transfer-Encoding: 8bit` body put on the wire under an
envelope that never declared `BODY=8BITMIME`; and credentials handed to an
unencrypted socket without a word of complaint.

What is still Oliver's, and cannot be covered here: a real relay, SPF and DKIM
signatures over real DNS, and whether an inbox files it under Primary or Spam.
"""

import base64
import datetime
import email
import email.policy
import socket
import ssl
import tempfile
import threading
import unittest

import config
from jobmatch import db, digest, mail
from tests.test_digest import BASE_URL, DigestTestCase

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:                                     # pragma: no cover
    x509 = None


def selfsigned(host="localhost"):
    """→ (certfile, keyfile) for a throwaway certificate valid for `host`."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    directory = tempfile.mkdtemp()
    certfile, keyfile = f"{directory}/cert.pem", f"{directory}/key.pem"
    with open(certfile, "wb") as handle:
        handle.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(keyfile, "wb") as handle:
        handle.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    return certfile, keyfile


class Delivery:
    """One connection, as the relay saw it."""

    def __init__(self):
        self.ehlo_name = None
        self.mail_from = None
        self.rcpt_to = []
        self.data = b""
        self.auth = None
        self.auth_encrypted = None
        self.data_encrypted = None


class Sink(threading.Thread):
    """An SMTP server on 127.0.0.1. `refuse_data` makes it reject the message."""

    def __init__(self, implicit_tls=False, starttls=True, refuse_data=False):
        super().__init__(daemon=True)
        self.certfile, self.keyfile = selfsigned()
        self.implicit_tls = implicit_tls
        self.offer_starttls = starttls
        self.refuse_data = refuse_data
        self.deliveries = []
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.port = self.listener.getsockname()[1]
        self.closed = False

    # ── lifecycle ────────────────────────────────────────────

    def run(self):
        while not self.closed:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def stop(self):
        self.closed = True
        try:
            self.listener.close()
        except OSError:
            pass

    def context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.certfile, self.keyfile)
        return context

    @property
    def last(self):
        return self.deliveries[-1]

    # ── the protocol ─────────────────────────────────────────

    def _serve(self, conn):
        got = Delivery()
        self.deliveries.append(got)
        encrypted = False
        try:
            if self.implicit_tls:
                conn = self.context().wrap_socket(conn, server_side=True)
                encrypted = True
            stream = conn.makefile("rb")

            def say(line):
                conn.sendall(line.encode() + b"\r\n")

            say("220 sink.test ESMTP")
            while True:
                raw = stream.readline()
                if not raw:
                    return
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                verb = line.split(" ")[0].upper()
                if verb in ("EHLO", "HELO"):
                    got.ehlo_name = line.partition(" ")[2]
                    offers = ["250-sink.test", "250-8BITMIME", "250-SIZE 33554432"]
                    if self.offer_starttls and not encrypted:
                        offers.append("250-STARTTLS")
                    offers += ["250-AUTH LOGIN PLAIN", "250 HELP"]
                    for offer in offers:
                        say(offer)
                elif verb == "STARTTLS":
                    say("220 go ahead")
                    conn = self.context().wrap_socket(conn, server_side=True)
                    stream = conn.makefile("rb")
                    encrypted = True
                elif verb == "AUTH":
                    got.auth_encrypted = encrypted
                    got.auth = self._auth(line, stream, say)
                    say("235 ok")
                elif verb == "MAIL":
                    got.mail_from = line.partition(":")[2].strip()
                    say("250 ok")
                elif verb == "RCPT":
                    got.rcpt_to.append(line.partition(":")[2].strip())
                    say("250 ok")
                elif verb == "DATA":
                    got.data_encrypted = encrypted
                    say("354 send it")
                    got.data = self._read_data(stream)
                    say("550 no" if self.refuse_data else "250 queued as 1")
                elif verb == "QUIT":
                    say("221 bye")
                    return
                else:
                    say("250 ok")
        except OSError:
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _auth(line, stream, say):
        words = line.split()
        if len(words) > 1 and words[1].upper() == "PLAIN":
            blob = words[2] if len(words) > 2 else ""
            if not blob:
                say("334 ")
                blob = stream.readline().decode().strip()
            parts = base64.b64decode(blob).split(b"\0")
            return parts[1].decode(), parts[2].decode()
        say("334 " + base64.b64encode(b"Username:").decode())
        user = base64.b64decode(stream.readline().strip()).decode()
        say("334 " + base64.b64encode(b"Password:").decode())
        password = base64.b64decode(stream.readline().strip()).decode()
        return user, password

    @staticmethod
    def _read_data(stream):
        body = []
        while True:
            chunk = stream.readline()
            if not chunk or chunk in (b".\r\n", b".\n"):
                return b"".join(body)
            # Dot-stuffing, undone: a line of the message that began with "."
            # left here with one prepended.
            body.append(chunk[1:] if chunk.startswith(b"..") else chunk)


@unittest.skipIf(x509 is None, "cryptography is needed to make a test certificate")
class SocketTestCase(unittest.TestCase):
    """Points `config` at a `Sink`, and makes the client trust its certificate."""

    MESSAGE = ("92%  Senior Python vývojár\n"
               "      Košice · plný úväzok\n"
               "      https://board.test/1\n")

    def start(self, implicit_tls=False, starttls=True, refuse_data=False, trust=True):
        sink = Sink(implicit_tls=implicit_tls, starttls=starttls, refuse_data=refuse_data)
        sink.start()
        self.addCleanup(sink.stop)
        config.SMTP_HOST, config.SMTP_PORT = "localhost", sink.port
        config.SMTP_SSL, config.SMTP_STARTTLS = implicit_tls, starttls
        if trust:
            # The one thing a throwaway certificate needs told. `mail` builds
            # its own context on purpose, so this replaces the constructor
            # rather than reaching into the module.
            real = ssl.create_default_context
            ssl.create_default_context = lambda *a, **kw: real(cafile=sink.certfile)
            self.addCleanup(setattr, ssl, "create_default_context", real)
        return sink

    def setUp(self):
        self._config = {key: getattr(config, key) for key in (
            "SMTP_HOST", "SMTP_PORT", "SMTP_SSL", "SMTP_STARTTLS", "SMTP_USER",
            "SMTP_PASSWORD", "SMTP_TIMEOUT", "SMTP_ALLOW_INSECURE_AUTH",
            "MAIL_FROM", "MAIL_FROM_NAME", "MAIL_DOMAIN",
        )}
        config.SMTP_USER, config.SMTP_PASSWORD = "bot@jobmatch.app", "hunter2"
        config.SMTP_TIMEOUT = 15
        config.SMTP_ALLOW_INSECURE_AUTH = False
        config.MAIL_FROM, config.MAIL_FROM_NAME = "bot@jobmatch.app", "JobMatch"
        config.MAIL_DOMAIN = ""

    def tearDown(self):
        for key, value in self._config.items():
            setattr(config, key, value)

    def headers(self, data):
        """The header block of a received message, as a dict."""
        text = data.decode("utf-8", "replace").split("\r\n\r\n", 1)[0]
        unfolded = text.replace("\r\n ", " ").replace("\r\n\t", " ")
        return dict(
            (line.split(":", 1)[0], line.split(":", 1)[1].strip())
            for line in unfolded.splitlines() if ":" in line
        )


# ── The conversation ─────────────────────────────────────────

class TransportTests(SocketTestCase):
    def test_starttls_delivers_the_message_over_an_encrypted_socket(self):
        sink = self.start(starttls=True)
        mail.send("her@example.com", "3 new job matches (top 92%)", self.MESSAGE,
                  html="<p>3 new matches</p>")

        got = sink.last
        self.assertEqual(got.rcpt_to, ["<her@example.com>"])
        self.assertTrue(got.auth_encrypted, "credentials crossed in the clear")
        self.assertTrue(got.data_encrypted, "the message crossed in the clear")
        self.assertEqual(got.auth, ("bot@jobmatch.app", "hunter2"))
        self.assertIn(b"Subject: 3 new job matches (top 92%)", got.data)

    def test_implicit_tls_delivers_the_message_with_no_starttls_at_all(self):
        """Port 465: the socket is encrypted before a byte of SMTP is spoken."""
        sink = self.start(implicit_tls=True, starttls=False)
        mail.send("her@example.com", "Subject", self.MESSAGE)

        got = sink.last
        self.assertTrue(got.data_encrypted)
        self.assertTrue(got.auth_encrypted)
        self.assertIn(b"Subject: Subject", got.data)

    def test_an_untrusted_certificate_stops_the_send(self):
        """Verification is on — and this is the test that proves it can fail."""
        sink = self.start(starttls=True, trust=False)
        with self.assertRaises(ssl.SSLCertVerificationError):
            mail.send("her@example.com", "Subject", self.MESSAGE)
        self.assertEqual(sink.last.data, b"")

    def test_credentials_are_never_handed_to_an_unencrypted_socket(self):
        """The measured defect: both TLS switches off sent the password in clear."""
        sink = self.start(implicit_tls=False, starttls=False)
        with self.assertRaises(RuntimeError) as caught:
            mail.send("her@example.com", "Subject", self.MESSAGE)
        self.assertIn("unencrypted", str(caught.exception))
        self.assertIsNone(sink.last.auth)
        self.assertEqual(sink.last.data, b"")

    def test_a_local_relay_can_ask_for_plaintext_auth_by_name(self):
        sink = self.start(implicit_tls=False, starttls=False)
        config.SMTP_ALLOW_INSECURE_AUTH = True
        mail.send("her@example.com", "Subject", self.MESSAGE)

        self.assertEqual(sink.last.auth, ("bot@jobmatch.app", "hunter2"))
        self.assertFalse(sink.last.auth_encrypted)

    def test_an_unauthenticated_relay_needs_no_tls_decision(self):
        """No SMTP_USER means no credentials, so nothing is at stake."""
        sink = self.start(implicit_tls=False, starttls=False)
        config.SMTP_USER, config.SMTP_PASSWORD = "", ""
        mail.send("her@example.com", "Subject", self.MESSAGE)
        self.assertIn(b"Subject: Subject", sink.last.data)

    def test_the_helo_name_is_the_sender_domain_not_the_container_hostname(self):
        """A container's hostname has no dot in it, and smtplib then sends
        `[172.18.0.4]` — a private address literal, in every relay's log."""
        sink = self.start()
        real = socket.getfqdn
        socket.getfqdn = lambda *a: "9f3c1d4b7a02"
        self.addCleanup(setattr, socket, "getfqdn", real)

        mail.send("her@example.com", "Subject", self.MESSAGE)
        self.assertEqual(sink.last.ehlo_name, "jobmatch.app")

    def test_mail_domain_overrides_the_sender_domain(self):
        sink = self.start()
        config.MAIL_DOMAIN = "mail.jobmatch.app"
        mail.send("her@example.com", "Subject", self.MESSAGE)

        self.assertEqual(sink.last.ehlo_name, "mail.jobmatch.app")
        self.assertIn("@mail.jobmatch.app>", self.headers(sink.last.data)["Message-ID"])


# ── What a relay actually receives ───────────────────────────

class DeliverabilityTests(SocketTestCase):
    def test_the_envelope_sender_is_the_address_in_the_From_header(self):
        """SPF authenticates the envelope; DMARC then asks whether it aligns
        with From:. Two different addresses is a pass that fails anyway."""
        sink = self.start()
        mail.send("her@example.com", "Subject", self.MESSAGE)

        self.assertEqual(sink.last.mail_from.split(" ")[0], "<bot@jobmatch.app>")
        self.assertEqual(self.headers(sink.last.data)["From"], "JobMatch <bot@jobmatch.app>")

    def test_every_message_carries_a_date_and_a_message_id(self):
        """Neither EmailMessage nor smtplib writes one, and for Phase 8's whole
        life this app wrote neither: `Date` is mandatory in RFC 5322 and a
        missing `Message-ID` is on Gmail's list of what a bulk sender must not do."""
        sink = self.start()
        mail.send("her@example.com", "Subject", self.MESSAGE)

        headers = self.headers(sink.last.data)
        self.assertRegex(headers["Date"], r"^\w{3}, \d{2} \w{3} \d{4} [\d:]{8} (GMT|[+-]\d{4})$")
        self.assertRegex(headers["Message-ID"], r"^<[^@<>]+@jobmatch\.app>$")

    def test_two_messages_do_not_share_a_message_id(self):
        sink = self.start()
        mail.send("her@example.com", "Subject", self.MESSAGE)
        mail.send("him@example.com", "Subject", self.MESSAGE)

        first, second = (self.headers(got.data)["Message-ID"] for got in sink.deliveries)
        self.assertNotEqual(first, second)

    def test_the_digest_says_it_is_a_robot(self):
        """RFC 3834. An out-of-office reply to a digest helps nobody."""
        sink = self.start()
        mail.send("her@example.com", "Subject", self.MESSAGE)
        self.assertEqual(self.headers(sink.last.data)["Auto-Submitted"], "auto-generated")

    def test_not_one_byte_on_the_wire_is_eight_bit(self):
        """The measured defect: the parts were `Content-Transfer-Encoding: 8bit`
        and the envelope never said `BODY=8BITMIME`, because smtplib only adds
        that for a non-ASCII *address*. A relay without the extension is
        entitled to strip the high bit off every Slovak title in the mail."""
        sink = self.start()
        mail.send("her@example.com", "Subject", self.MESSAGE,
                  html="<p>Senior vývojár — Košice</p>")

        got = sink.last
        self.assertEqual([byte for byte in got.data if byte > 127], [])
        got.data.decode("ascii")            # the assertion above, said twice
        self.assertNotIn("8bit", self.headers(got.data).get("Content-Transfer-Encoding", ""))

    def test_the_accented_text_survives_the_encoding(self):
        """7-bit on the wire is worth nothing if it does not decode back."""
        sink = self.start()
        mail.send("her@example.com", "Subject", self.MESSAGE,
                  html="<p>Senior vývojár — Košice</p>")

        received = email.message_from_bytes(sink.last.data, policy=email.policy.default)
        plain = received.get_body(("plain",)).get_content()
        html = received.get_body(("html",)).get_content()
        self.assertIn("Senior Python vývojár", plain)
        self.assertIn("Košice · plný úväzok", plain)
        self.assertIn("vývojár — Košice", html)

    def test_the_plain_part_still_leads_the_alternative(self):
        """Asked of the received bytes, not of the object: clients render the
        last part they understand, so text has to be first."""
        sink = self.start()
        mail.send("her@example.com", "Subject", self.MESSAGE, html="<p>rich</p>")

        body = sink.last.data.decode("ascii")
        self.assertLess(body.index("text/plain"), body.index("text/html"))

    def test_a_header_cannot_be_injected_through_the_recipient(self):
        """The address comes from the users table, and a header is one line."""
        for address in ("her@example.com\nBcc: attacker@evil.test",
                        "her@example.com\r\nSubject: hijacked"):
            with self.assertRaises(ValueError):
                mail.build(address, "Subject", "plain")


# ── The digest, over a real socket ───────────────────────────

class DigestOverSocketTests(DigestTestCase, SocketTestCase):
    """`send_due` end to end: the message that leaves is the one a relay gets."""

    def setUp(self):
        DigestTestCase.setUp(self)
        SocketTestCase.setUp(self)
        mail.send = self._send          # the real transport, not the recorder

    def tearDown(self):
        SocketTestCase.tearDown(self)
        DigestTestCase.tearDown(self)

    def test_a_real_digest_reaches_the_relay_intact(self):
        """A Slovak title, the two bodies, the unsubscribe header and the stamp
        — all of it through a socket rather than through the recorder."""
        sink = self.start()
        self.add_job("Senior Python vývojár", company="Košice s.r.o.")
        user_id = self.user_with_matches(count=3)
        sent = digest.send_due(self.conn)

        self.assertEqual(len(sent), 1)
        self.assertEqual(sink.last.rcpt_to, ["<her@example.com>"])
        headers = self.headers(sink.last.data)
        self.assertIn("new job match", headers["Subject"])
        self.assertEqual(headers["To"], "her@example.com")
        self.assertEqual(headers["List-Unsubscribe"], f"<{BASE_URL}/settings>")
        self.assertIn("Date", headers)
        self.assertEqual([byte for byte in sink.last.data if byte > 127], [])

        received = email.message_from_bytes(sink.last.data, policy=email.policy.default)
        plain = received.get_body(("plain",)).get_content()
        self.assertIn("Senior Python vývojár", plain)
        self.assertIn("http://x/Senior Python vývojár", plain)
        self.assertEqual(self.digested(user_id), 4)

    def test_a_relay_that_refuses_the_message_leaves_the_jobs_for_tomorrow(self):
        """The 550 has to reach `send_for_user` as an exception, or the jobs are
        marked as sent and nobody ever hears about them."""
        self.start(refuse_data=True)
        user_id = self.user_with_matches(count=3)
        sent = digest.send_due(self.conn)

        self.assertEqual(sent, [])
        self.assertEqual(self.digested(user_id), 0)
        # The run is stamped anyway: a dead relay costs one cycle, not a retry
        # on every poll.
        self.assertIsNotNone(db.get_setting(self.conn, user_id, digest.RUN_KEY))
