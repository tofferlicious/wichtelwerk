# Wichtelwerk

<p align="center">
  <img src="static/images/gift-still-life.svg" width="240" alt="Wichtelwerk gift illustration in evergreen, cream and terracotta">
</p>

A small, self-hosted Secret Santa application with a German-language interface. Organize private gift exchanges, collect wishlists and reveal each person's recipient only in their own account. Built with Flask, SQLite and plain JavaScript; no frontend build step, analytics, external fonts or image services.

## Screenshots

Real application screens, captured locally with **synthetic demo data**. No production accounts, wishlists or assignments are shown.

### Welcome

![Wichtelwerk desktop welcome page with the gift illustration](docs/screenshots/home-desktop.png)

### Your rounds

![Organizer dashboard showing two synthetic gift exchanges](docs/screenshots/dashboard.png)

### Your recipient and wishlist

![Participant view showing a synthetic recipient and wishlist](docs/screenshots/recipient.png)

<details>
<summary>Mobile view</summary>

<img src="docs/screenshots/mobile.png" width="320" alt="Mobile participant view with synthetic wishlist and recipient details">

</details>

Regenerate these screenshots using the development dependencies:

```sh
.venv/bin/python scripts/capture_screenshots.py
```

The script starts a disposable local instance, exercises the actual invitation and draw APIs, and uses memory-only email. It never connects to a production instance. Set `CHROME_PATH` if you want to use an existing Chromium installation.

## Features

- Passwordless sign-in using single-use email links.
- Email invitations and optional shared invitation links.
- Accept/decline responses, wishlists and optional postal addresses.
- Directional exclusions and a feasibility check before the final draw.
- Private recipient views: organizers do not receive an assignment list.
- Queued draw notifications with retries and visible delivery-submission status.
- Annual round copies without copying wishes, addresses or participation responses.
- Configurable retention, account deletion and round deletion.
- Creator allowlist by default; optional public creation for authenticated users.
- Responsive interface with locally served SVG artwork.

## Install

Requires Python 3.11+ and a Unix-like server. Real sign-in/invitation email currently requires a working `/usr/sbin/sendmail` interface; direct SMTP configuration is not implemented.

```sh
git clone https://github.com/tofferlicious/wichtelwerk.git
cd wichtelwerk
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Configure the process environment, using your own hostname, sender and verified login email:

```sh
export DATABASE="$PWD/instance/wichtelwerk.db"
export BASE_URL="https://wichtelwerk.example.com"
export MAIL_MODE="sendmail"
export MAIL_FROM="wichtelwerk@example.com"
export PUBLIC_EVENT_CREATION="false"
export EVENT_CREATOR_EMAILS="admin@example.com"

.venv/bin/gunicorn --bind 127.0.0.1:8765 --workers 2 'wichtelwerk:create_app()'
```

Place an HTTPS reverse proxy in front of Gunicorn. Cookies are secure by default; use HTTPS for real sign-in. Set `BASE_URL` to the exact public origin without a path. Uberspace requires binding to `0.0.0.0:8765` rather than loopback and registering the dedicated domain backend.

The database schema initializes automatically. Keep the database and backups outside publicly served paths. `.env.example` documents the variables but **is not automatically loaded**; export them or set them in your process manager. Keep the same database, URL and mail settings for maintenance workers. Restart the web application after configuration changes.

## Who can create rounds?

| Variable | Default | Meaning |
| --- | --- | --- |
| `PUBLIC_EVENT_CREATION` | `false` | If explicitly enabled, all authenticated users may create rounds. |
| `EVENT_CREATOR_EMAILS` | empty | Comma-separated allowlist of login email addresses permitted to create and copy rounds. |

With the defaults, nobody can create rounds. There is no automatic first-user administrator. Allowlist matching is exact after trimming/lowercasing; no wildcard or implicit email aliases are supported. The switch accepts `true/false`, `1/0`, `yes/no` or `on/off`; invalid values abort startup.

The backend enforces this policy for both creation and copying; hiding controls is not the security boundary. Ordinary users can still sign in, accept invitations, join an enabled invitation link and edit their own wishes. Existing ownership remains intact, but a former creator without current permission cannot copy a round. Enabling public creation does not grant access to other users' rounds. The allowlist is not a global administration role.

## Maintenance

Schedule these commands with your process manager or cron, using the same exported environment as the web application:

```sh
# Run approximately once per minute to submit queued draw notifications.
.venv/bin/flask --app 'wichtelwerk:create_app()' send-draw-mail

# Run daily to remove expired rounds, links, sessions and rate-limit entries.
.venv/bin/flask --app 'wichtelwerk:create_app()' cleanup
```

Run `/healthz` for a basic application/database health check. Back up SQLite consistently, including its WAL state; copying only a live `.db` file is not a backup strategy. Preserve production data on upgrades and never replace it with a development database.

## Tests

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
.venv/bin/python verify_lifecycle.py
```

If Chromium is already installed, set `CHROME_PATH=/path/to/chrome` instead of downloading another copy. Tests use temporary SQLite databases and memory-only mail, exercising creator permissions, anonymous denial, invitations, wishlists, draw privacy, notification queues and desktop/mobile controls.

An optional **read-only** deployment check is skipped unless you explicitly set `WICHTEL_TEST_URL=https://your-host.example`. It checks the public landing page and login form; it does not send email. The test suite does not prove inbox delivery.

## Security and limitations

- Assignment privacy is server-side access control, **not end-to-end encryption**. The server operator can access the database. Small groups or strong exclusions can make assignments logically inferable.
- Draws are final. The matching algorithm randomizes valid assignments but does not sample them uniformly. Previous-year assignments are not reused as exclusion constraints.
- Mail status means submitted to the mail service, not delivered or read. The notification worker uses at-least-once delivery; a crash around submission can produce duplicates.
- Retention months are approximated as 31 days. Accounts persist until explicitly deleted; expired rounds are removed by the cleanup command.
- Basic protections include CSRF checks, single-use login tokens, secure cookies, access checks, rate limits and a restrictive content security policy. This project has automated tests, not an independent comprehensive security audit.
- Before offering a public instance, supply your own legally appropriate operator/contact information and privacy notice; the built-in page describes technical behavior only.

This repository contains application code, synthetic tests and generic configuration examples—no production accounts, rounds, mail outboxes or credentials.

## License

[MIT](LICENSE). The included SVG illustrations are part of the project and use the same license.
