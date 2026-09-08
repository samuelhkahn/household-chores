# Household Chores: Initial Django Backlog

**Implementation status (2026-09-08):** Items 1–9 are implemented in the
release candidate and covered by the CI suite. The Docker image and deployment
runbook are ready; provisioning the live demonstration environment remains an
owner-operated step because it requires a hosting account and secrets.

This backlog breaks the product plan into a small, dependency-ordered set of deliverable tasks. Each task should include migrations, tests, and documentation where applicable.

## 1. Bootstrap the Django project

**Priority:** P0
**Depends on:** Nothing

- Install Django and create the project and first application.
- Register the application in `INSTALLED_APPS` in the project `settings.py` file.
- Add environment-based configuration, PostgreSQL support, and local console email.
- Add Docker, Docker Compose, formatting, linting, tests, and migration checks in CI.
- Add health and readiness endpoints.

**Done when:** The application starts locally through Docker, connects to PostgreSQL, and passes the initial CI checks.

## 2. Implement users, households, and authorization

**Priority:** P0
**Depends on:** 1

- Create the custom email-based user model before the first migration.
- Model households, adult memberships, organizer roles, and managed child profiles.
- Allow organizers to invite adults with expiring, single-use tokens.
- Enforce exactly one household per adult and household-level access on every operation.

**Done when:** An organizer can create a household, invite an adult, and add a child; permission tests prove outsiders cannot read or change household data.

## 3. Build recurring chore management

**Priority:** P0
**Depends on:** 2

- Model daily and weekly recurring chores, effort, due day, eligibility, and active state.
- Add server-rendered create and edit workflows using Django forms and HTMX where useful.
- Preserve the current week's schedule when a chore changes; apply changes to the next assignment run.
- Put validation and business rules in service modules.

**Done when:** Authorized members can manage valid recurring chores, and edits do not alter existing occurrences or assignments.

## 4. Generate occurrences and record completion

**Priority:** P0
**Depends on:** 3

- Generate and store a separate occurrence for every scheduled chore instance.
- Keep incomplete past-due occurrences open and mark them overdue without blocking new ones.
- Let adults complete their own occurrences with an optional note.
- Let organizers record completion for child assignments.

**Done when:** Daily and weekly occurrences are generated idempotently, status transitions are correct, and completion permissions are covered by tests.

## 5. Implement capacity-weighted assignment

**Priority:** P0
**Depends on:** 4

- Store each member's low, medium, or high capacity for the coming week.
- Calculate weighted targets and a documented, bounded prior-week compensation.
- Assign occurrences while enforcing active-member and child-eligibility rules.
- Distribute daily occurrences individually and use deterministic tie-breaking.
- Preserve existing assignments and organizer overrides.

**Done when:** Tests demonstrate valid, deterministic assignments, bounded compensation, eligibility enforcement, and explainable target-versus-assigned totals.

## 6. Add scheduling and email delivery

**Priority:** P1
**Depends on:** 5

- Add a persistent scheduler and background worker for Sunday allocation in each household's timezone.
- Send assignment emails after allocation and one reminder on each occurrence's due day.
- Deliver adult notices directly and child notices to every organizer.
- Make jobs and sends retry-safe and idempotent; store delivery attempts and failures.
- Configure SendGrid from environment variables and use a fake backend in tests.

**Done when:** Automated tests prove that scheduled jobs create assignments and send each required message exactly once to the correct recipients.

## 7. Build reassignment and override workflows

**Priority:** P1
**Depends on:** 5

- Let adults request reassignment of their own occurrences.
- Let organizers reject requests or approve them by selecting an eligible replacement.
- Let organizers override an assignment directly.
- Record previous and new assignees, actor, time, and optional reason without rerunning allocation.

**Done when:** Requests, decisions, and overrides respect roles, affect fairness reporting, and leave a complete audit trail.

## 8. Deliver the responsive dashboard

**Priority:** P1
**Depends on:** 5, 7

- Show the signed-in member's current-week chores and the household schedule.
- Show pending, completed, and overdue states plus target and assigned minutes per member.
- Expose only current- and previous-week history in the interface.
- Add role-appropriate completion, reassignment, and override actions.
- Cover mobile layout, keyboard access, and empty, loading, and error states.

**Done when:** The primary workflows work on mobile and desktop and pass accessibility and end-to-end smoke checks.

## 9. Harden and deploy the first release

**Priority:** P1
**Depends on:** 1–8

- Review CSRF, cookies, HTTPS, allowed hosts, authorization, validation, and database constraints.
- Add structured logging, error-reporting hooks, migration and rollback instructions, and backup expectations.
- Complete unit, integration, permission, scheduler, email, and end-to-end test coverage.
- Document Docker-based operation and deploy a demonstration environment that may sleep when idle.

**Done when:** Every acceptance criterion in `plan.md` is covered by an automated test or documented deployment verification, and the demo can be built and run from the documented commands.
