# Household Chores

A responsive Django web application that helps couples and families distribute recurring household chores fairly and remember when they are due.

The application will assign daily and weekly chores according to each member's estimated workload and weekly capacity, send assignment and due-day emails, and provide a compact view of chores and fairness across the household.

## Status

Release-candidate implementation. All nine backlog areas are implemented and
covered by the automated suite. A live demonstration deployment still requires
choosing a host and supplying that host's credentials. See the
[product plan](_docs/plan.md), [backlog](_docs/backlog.md), and
[operations guide](_docs/operations.md).

## Intended stack

- Django with server-rendered templates and HTMX
- PostgreSQL
- SendGrid email delivery
- A production-safe background job scheduler
- Docker-based deployment

## Local development

Prerequisites: Python 3.12 or later, [uv](https://docs.astral.sh/uv/), and
Docker with Compose.

Install the development environment and run the checks:

```console
uv sync
uv run python manage.py migrate
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python manage.py makemigrations --check --dry-run
```

The test command includes branch coverage for application code and enforces a
minimum total coverage of 90%.

Run Django locally with SQLite and console email:

```console
uv run python manage.py runserver
```

Run the application with PostgreSQL:

```console
docker compose up -d db
docker compose run --rm web python manage.py migrate
docker compose up --build
```

The liveness and database-readiness endpoints are available at `/health/` and
`/ready/`. Copy `.env.example` to `.env` when running outside Compose and adjust
the values for the environment. Create an initial organizer account with
`uv run python manage.py createsuperuser`, sign in through `/accounts/login/`,
and create its household from the home page.

The Compose stack includes a persistent scheduler/worker. To run a single
scheduler pass locally, or use the lower-level maintenance commands:

```console
uv run python manage.py run_scheduler --once
uv run python manage.py generate_occurrences HOUSEHOLD_ID 2026-09-07
uv run python manage.py mark_overdue --as-of 2026-09-08
```

The scheduler stores idempotent allocation, reminder, and overdue jobs in the
database. It allocates at 18:00 on Sunday and sends due-day reminders after the
household's configured local reminder time.

## Fair allocation

Low, medium, and high capacity have weights 1, 2, and 3. The allocator carries
forward 50% of the prior week's target-minus-assigned gap, capped at 25% of the
new base target. It then deterministically minimizes total absolute deviation,
while respecting child eligibility and preserving existing assignments and
organizer overrides.
