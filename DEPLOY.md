<!-- How JobMatch is deployed. The plan is in ROADMAP.md; this is the runbook. -->

# DEPLOY.md — JobMatch on a VPS

Four containers behind Caddy on one small box:

```
        :443
          │
     ┌────▼────┐      ┌──────────┐
     │  caddy  ├─────►│   web    │  gunicorn, 2 workers, never scrapes
     └─────────┘      └────┬─────┘
                           │
     ┌─────────┐      ┌────▼─────┐
     │ worker  ├─────►│    db    │  Postgres 16
     └─────────┘      └──────────┘
      the only scraper. exactly one.
```

**Why a VPS and not a PaaS.** The image carries Chromium (~1 GB) and a scan runs
for minutes with deliberate 5–16 s politeness delays between requests — an
always-on box fits that far better than scale-to-zero. Postgres is a container
instead of a managed-database bill, an EU datacenter keeps user CVs in the EU
and sits close to the Slovak boards, and owning the box is the more honest CV
line. The cost is that patching, backups and the firewall are yours. Fly.io +
Fly Postgres is the drop-in alternative: same `Dockerfile`, only this file
changes.

**One worker, always.** The crawl is shared by every user by design (see
`ROADMAP.md`), and the politeness delays only mean anything if a single process
is doing the scraping. Never `docker compose up --scale worker=2`. `web` can be
scaled freely — as of Phase 4 scan state lives in the `scans` row, so any web
process can answer a status poll.

---

## 1. Provision the box

A Hetzner CX22 (2 vCPU / 4 GB, ~€4/mo) in an EU datacenter is the sizing this
was built for: the Playwright image and one Chromium fit, with room for
Postgres.

```bash
# As root on a fresh Ubuntu 24.04:
adduser deploy && usermod -aG sudo deploy
rsync --archive ~/.ssh /home/deploy/ && chown -R deploy:deploy /home/deploy/.ssh

# SSH keys only.
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/'               /etc/ssh/sshd_config
systemctl restart ssh

ufw default deny incoming && ufw default allow outgoing
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp
ufw --force enable

apt update && apt install -y unattended-upgrades fail2ban
dpkg-reconfigure -plow unattended-upgrades

# Docker, from Docker's own repository (Ubuntu's is older).
curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy
```

Point the domain's `A` (and `AAAA`) record at the box **before** the first
`docker compose up`: Caddy asks Let's Encrypt for a certificate on startup, and
a failed challenge is rate-limited.

> Docker publishes ports by writing iptables rules that bypass ufw. It does not
> bite here because only `caddy` publishes anything and those ports are open
> anyway — but do not add a `ports:` mapping to `db` and assume ufw hides it.

## 2. Configure

```bash
sudo mkdir -p /opt/jobmatch && sudo chown deploy:deploy /opt/jobmatch
git clone https://github.com/<you>/jobmatch.git /opt/jobmatch
cd /opt/jobmatch
cp .env.example .env
```

Fill in `.env` — every other value has a working default:

| Variable | |
|---|---|
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"`. Changing it logs everybody out. |
| `POSTGRES_PASSWORD` | Any long random string. `DATABASE_URL` is built from it. |
| `DOMAIN`, `ACME_EMAIL` | For Caddy's certificate. |
| `HOST` | `0.0.0.0` — gunicorn binds with `--bind`, but startup checks read this. |
| `JOBMATCH_DEBUG` | `false`. Startup refuses debug on a non-loopback bind. |
| `ALLOW_SIGNUP` | `false` closes the door without a code change. |
| `TRUSTED_PROXY_HOPS` | `1` for the Caddy in front. Too high lets a caller forge their own IP past the rate limits. |
| `DEMO_MODE` | `true` puts the seeded demo account on the landing page. `DEMO_EMAIL` / `DEMO_PASSWORD` are published on that page, so change them from the repo's defaults. |
| `SENTRY_DSN` | Optional. Unset = no error reporting; the app boots either way. |
| `SMTP_HOST`, `MAIL_FROM` | Optional, and both are needed for either to count. Unset = the instance sends no digests; see §7. |
| `PUBLIC_BASE_URL` | `https://$DOMAIN`. Only the emails need it — the worker has no request to build a link from, and without it a digest links to the job board rather than to your app. |

`LOG_FORMAT=json` and `JOBMATCH_COMPONENT` are set per container in
`docker-compose.yml`, not in `.env` — `web` and `worker` share one log stream
and each line says which of them wrote it.

## 3. Start it

```bash
docker compose up -d --build --wait
docker compose logs -f web worker
```

The first build pulls the ~1 GB Playwright base; later ones reuse it and take
seconds. `--wait` returns only once `db` is healthy and the app containers are
up.

Then create the first account, which is the instance's admin — and therefore
the account whose search settings drive the shared crawl:

```bash
docker compose exec web python3 -m jobmatch.setpassword
```

Verify:

```bash
curl -sI https://$DOMAIN/login | head -1     # 200, with a valid certificate
docker compose exec web python3 -c "from jobmatch import db; c=db.get_conn(); print(c.dialect, c.scalar('SELECT COUNT(*) FROM jobs'))"
```

## 4. Migrating existing data

A fresh Postgres deployment needs nothing: `create_all` writes the current
schema and `jobmatch.backfill` is SQLite-only by design (it rewrites tables in
place, which is what a live SQLite file needs and a new database never does).

To carry a local SQLite database over, run `python3 -m jobmatch.backfill`
against it **first**, so it is on the current schema, then move the rows with
your tool of choice (`pgloader` handles this shape without help). The timestamp
columns are `TEXT` in both backends and hold the same `YYYY-MM-DD HH:MM:SS`
naive-UTC strings, so they copy across as they are — that is the whole reason
the Postgres defaults are `to_char(now() AT TIME ZONE 'utc', …)` rather than a
real `timestamp`.

## 5. Backups

`deploy/backup.sh` dumps Postgres and tars the CVs (which live in a volume, not
in the database), verifies both archives, copies them off the box and prunes
local copies older than `KEEP_DAYS`.

```bash
sudo crontab -e
# 17 3 * * *  REMOTE_TARGET=u1234@u1234.your-storagebox.de:jobmatch/ \
#             /opt/jobmatch/deploy/backup.sh >> /var/log/jobmatch-backup.log 2>&1
```

**Then restore one.** A backup that has never been restored is not a backup:

```bash
deploy/restore-check.sh /var/backups/jobmatch/jobmatch-<stamp>.sql.gz
```

It restores into a scratch database inside the same container, diffs the row
counts and the `sum(match_score)` against live, drops the scratch database, and
exits non-zero on any mismatch. Nothing it does touches the live database.

## 6. Deploys

`.github/workflows/deploy.yml` runs after CI goes green on `main`: it SSHes in,
checks out that exact commit, rebuilds and restarts with `--wait`, and then
fetches `https://$DOMAIN/login`. A container that does not come up healthy fails
the workflow instead of quietly serving a 502.

Repository secrets it needs:

| Secret | |
|---|---|
| `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PATH` | The box, the `deploy` user, `/opt/jobmatch`. |
| `DEPLOY_SSH_KEY` | A deploy-only private key; put the public half in `~deploy/.ssh/authorized_keys`. |
| `DEPLOY_HOST_KEY` | `ssh-keyscan -t ed25519 <host>` — pinned, not trust-on-first-use. |
| `DEPLOY_DOMAIN` | For the smoke test. |

Manual deploy, same thing by hand:

```bash
cd /opt/jobmatch && git pull && docker compose up -d --build --wait
```

## 7. Email digests (optional)

The worker mails each user the new matches their scan turned up, at most one
message every `DIGEST_INTERVAL_HOURS`. It is off until the instance has both an
`SMTP_HOST` and a `MAIL_FROM`; unset, the worker skips the pass entirely and
Settings tells the user their instance cannot send mail. Nothing else changes,
and mail is never a startup dependency — a relay that is refusing connections
costs a digest, not the scanner.

Use a transactional relay (Postmark, Resend, SES, Fastmail — anything with
SMTP). **Do not send from the box itself**: a fresh VPS IP has no reputation,
no SPF/DKIM and no PTR record, and the mail goes to spam or nowhere.

```bash
# in .env
SMTP_HOST=smtp.example-relay.com
SMTP_PORT=587                      # 465 if the relay wants implicit TLS
SMTP_USER=...
SMTP_PASSWORD=...
MAIL_FROM=jobmatch@yourdomain.tld  # must be an address the relay lets you send as
PUBLIC_BASE_URL=https://jobmatch.yourdomain.tld
```

Port 587 is plaintext until STARTTLS upgrades it; 465 is encrypted before the
first byte of SMTP. `SMTP_SSL` and `SMTP_STARTTLS` each default off the port, so
the usual pair needs neither — setting them the wrong way round is the reason a
relay hangs up on you. Add SPF and DKIM records for `MAIL_FROM`'s domain at the
relay's instructions, or every message is spam by default.

Then check it without sending anything, and send one on purpose:

```bash
docker compose exec worker python3 -m jobmatch.digest --status
docker compose exec worker python3 -m jobmatch.digest --dry-run --user you@example.com --force
docker compose exec worker python3 -m jobmatch.digest --user you@example.com --force
```

`--force` ignores both the schedule and the user's own Notifications setting,
which is what makes it a test rather than a wait. It still marks what it sends,
so those jobs will not turn up in the next digest.

## Operating notes

```bash
docker compose logs -f worker              # what the scan is doing
docker compose exec db psql -U jobmatch    # a shell on the database
docker compose exec web python3 -m jobmatch.setpassword   # add/reset an account
docker compose exec web python3 -m jobmatch.demo --status  # when the demo last reset
docker compose exec worker python3 -m jobmatch.digest --status  # who is due an email
curl -s https://$DOMAIN/healthz                            # what an uptime monitor sees
docker compose restart worker              # safe: an interrupted scan is
                                           # reconciled from its heartbeat
```

- **A scan looks stuck.** It probably isn't — Profesia and Kariéra sleep 5–16 s
  between page requests on purpose. `SELECT status, phase, heartbeat_at FROM
  scans ORDER BY id DESC LIMIT 1;` is the truth. A row whose heartbeat has
  stopped for `SCAN_STALE_SECONDS` is failed by the worker on its next pass.
- **Chromium dies mid-crawl.** Almost always shared memory; `shm_size: 512mb` on
  the worker is why. Check `docker compose logs worker` for a tab crash.
- **Certificate trouble.** `docker compose logs caddy`. The usual cause is DNS
  not yet pointing at the box.
- **Point an uptime monitor at `/healthz`.** It is public, it queries the
  database, and it answers 503 when that query fails — which is the failure a
  check against `/login` would miss, because the web container is perfectly
  happy to serve a page while Postgres is gone. `web`'s own container
  healthcheck uses the same endpoint. The body carries `release`, so you can
  see which commit is actually serving.
- **Reading the logs.** Both containers emit one JSON object per line, tagged
  with `component`. `docker compose logs --no-log-prefix | jq 'select(.level ==
  "ERROR")'` is the whole tooling. A request-scoped line also carries `method`,
  `path` and `user_id` — never an email address.
- **The demo drifted or is empty.** `docker compose exec worker python3 -m
  jobmatch.demo` re-seeds it immediately; the worker does it on its own every
  `DEMO_RESET_HOURS`. The account keeps its id and password, so anybody
  currently reading it is not signed out.
- **Nobody is getting a digest.** `python3 -m jobmatch.digest --status` answers
  the whole question in one screen: whether the instance can send mail at all,
  and per account whether they left it on, when theirs last ran, and how many
  matches are waiting. A user with 0 waiting is not a bug — an empty digest is
  deliberately never sent. A failed send is an `ERROR` line in the worker's log
  and leaves the jobs unmarked, so they arrive in the next one.
- **Emergency stop on the digests.** `DIGEST_INTERVAL_HOURS=0` stops the worker
  scheduling any, while leaving `python3 -m jobmatch.digest --force` working
  from the shell. Clearing `SMTP_HOST` turns the feature off outright.
- **Emergency stop on the scrapers.** `SCAN_ENABLED=false` in `.env` and
  `docker compose up -d worker web` — the schedule stops and `POST
  /api/scan/start` answers 503. No code change, no image rebuild.
