# Operations and deployment

## Production configuration

Use PostgreSQL and set `DJANGO_DEBUG=false`, a random `DJANGO_SECRET_KEY` of at
least 50 characters, exact `DJANGO_ALLOWED_HOSTS`, and HTTPS origins in
`DJANGO_CSRF_TRUSTED_ORIGINS`. Enable secure cookies and SSL redirect. After the
HTTPS configuration is verified, set `DJANGO_SECURE_HSTS_SECONDS=31536000`.

For SendGrid, use Django's SMTP backend and set `SENDGRID_API_KEY`,
`DEFAULT_FROM_EMAIL`, `EMAIL_HOST=smtp.sendgrid.net`, `EMAIL_PORT=587`,
`EMAIL_HOST_USER=apikey`, and `EMAIL_USE_TLS=true`. Automated tests use Django's
in-memory backend and local development defaults to console delivery.

Run the web and worker processes from the same image:

```console
gunicorn config.wsgi:application --bind 0.0.0.0:8000
python manage.py run_scheduler
```

The worker can be restarted safely. Jobs and email deliveries have unique
idempotency keys, attempt counts, timestamps, and retained failure messages.
Application output uses one-line structured JSON logs, which a host can route to
its error reporting or log alerting service.

## Release and rollback

Before a release, back up PostgreSQL and record the current image tag. Then run:

```console
python manage.py migrate --plan
python manage.py migrate
python manage.py check --deploy
```

For rollback, stop the worker, restore the previous image, and migrate the app to
the migration recorded for that release, for example:

```console
python manage.py migrate chores 0001
```

Only reverse a migration after checking its reversibility and taking a fresh
backup. If a release writes data in a shape the prior code cannot read, restore
the pre-release database backup instead of relying on a schema-only rollback.

## Backups

Use a managed PostgreSQL plan with automated daily backups and point-in-time
recovery for production. Retain at least seven daily backups, encrypt them, and
test a restore quarterly in an isolated database. A sleeping demonstration
environment may use a lower-cost database, but it should still be treated as
disposable and contain no sensitive household data.

## Demonstration deployment checklist

1. Create a PostgreSQL database, a web service, and a continuously running
   worker service from the Docker image.
2. Add the production environment variables described above.
3. Run migrations as the release command.
4. Verify `/health/` and `/ready/`, create a test household, and run
   `python manage.py run_scheduler --once`.
5. Confirm one assignment email and one due-day reminder, then retry the worker
   pass and confirm no duplicate delivery.
6. Verify database backups and exercise a restore before inviting real users.

The web service may sleep when idle. The worker must either remain active or be
invoked at least once per minute by the hosting platform. Provisioning a live
environment is intentionally separate from the repository because it requires
the owner's hosting account, domain choice, and secrets.
