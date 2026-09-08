# Household Chores: Product and Implementation Plan

## 1. Objective

Build a production-ready, responsive Django web application for couples and families. The product should distribute recurring chores in proportion to household members' weekly capacity, remind them by email, and make the result understandable and adjustable.

The codebase must be portable through Docker. The initial demonstration deployment may use a free-tier host that sleeps when inactive; continuous availability is not required for that environment.

## 2. Users and permissions

### Adult member

- Signs in with an email address and password.
- Belongs to exactly one household.
- Creates recurring chores.
- Sets their own weekly capacity to low, medium, or high.
- Views household assignments and fairness totals.
- Completes their own chores with an optional short note.
- Requests reassignment of their chores.

### Organizer

- Has all adult-member capabilities.
- Invites adult members by email.
- Creates and manages child profiles.
- Configures household settings and reminder time.
- Selects a replacement member when approving a reassignment.
- Overrides assignments directly; every override is recorded.

A household may have multiple organizers.

### Child profile

- Has no login or email address.
- Is managed by an organizer, who records completion on the child's behalf.
- May receive only chores explicitly marked as child-eligible.
- Has assignment and due-day reminders delivered to all household organizers.

## 3. Chores and occurrences

The first release supports recurring chores only.

Each chore has:

- Name and optional description
- Estimated effort in minutes
- Daily or weekly recurrence
- Due day, with no due time
- Child-eligible or adult-only classification
- Active/inactive state

Every scheduled occurrence is stored separately. An incomplete occurrence becomes overdue and remains open until completed. Future occurrences continue to be created even when an earlier one is overdue.

Chores added or edited during a week keep the current week's schedule unchanged. Their changes apply to the next assignment run.

## 4. Weekly capacity and fair assignment

Members select a capacity for the coming week:

| Capacity | Workload share |
| --- | ---: |
| Low | 1 |
| Medium | 2 |
| High | 3 |

The assignment service runs every Sunday evening in the household's timezone.

For total estimated minutes `T` and total active-member weight `W`, member `i` has an initial target of:

`target_i = T * weight_i / W`

The service then adjusts targets to compensate for the difference between each member's target and assigned minutes in the previous week. Compensation must be bounded so that one unusual week cannot distort assignments indefinitely. The exact bound will be documented alongside the algorithm and covered by tests.

The allocator should minimize each member's absolute deviation from their adjusted target while respecting these rules:

- Only active household members may receive chores.
- Adult-only chores cannot be assigned to children.
- Each occurrence has exactly one assignee.
- Individual occurrences of daily chores are distributed separately.
- Existing assignments and organizer overrides are never silently rewritten.
- Deterministic tie-breaking makes identical inputs produce identical results.

The dashboard displays assigned minutes and the capacity-weighted target for every member so the allocation is explainable.

## 5. Assignment lifecycle

1. Members and organizers maintain recurring chores and next week's capacity.
2. On Sunday evening, the system creates the next week's occurrences and assigns them.
3. Each affected adult receives an assignment email. Organizers receive the relevant child-assignment emails.
4. On an occurrence's due day, the system sends one reminder at the household-configured time.
5. A member or organizer marks the occurrence done and may add a short completion note.
6. An unfinished occurrence is marked overdue after its due day; no additional overdue email is required.

## 6. Reassignment and overrides

- An adult can submit a reassignment request for one of their occurrences.
- An organizer approves or rejects the request.
- On approval, the organizer explicitly selects the replacement member.
- Organizers may also override an assignment without a request.
- Reassignments and overrides record the previous assignee, new assignee, acting organizer, timestamp, and optional reason.
- Changes affect fairness reporting but do not trigger a full weekly reallocation.

## 7. Dashboard and history

The responsive dashboard provides a compact overview containing:

- The signed-in member's current-week chores
- The whole household's weekly schedule
- Assigned minutes and capacity-weighted targets by member
- Clear pending, completed, and overdue states
- Reassignment actions appropriate to the user's role

The interface exposes the current and previous week only. Older operational records may remain in the database for integrity and auditing but are not part of the first-release user interface.

## 8. Email behavior

- Use SendGrid in deployed environments.
- Send assignment emails after the Sunday allocation completes.
- Send due-day emails once, at a household-wide configurable time.
- Send adult reminders directly to the assignee.
- Send reminders for child assignments to all organizers.
- Make email tasks idempotent so retries do not produce duplicates.
- Store delivery attempts and failure status for operational diagnosis.
- Use Django's console backend locally and a fake backend in automated tests.

## 9. Technical architecture

- Django application with server-rendered templates and HTMX interactions
- PostgreSQL as the production database
- Custom email-based user model created before the first migration
- Django forms and services for validation and business logic
- Background workers and a persistent scheduler for weekly allocation and due-day email tasks
- SendGrid configured through environment variables
- Docker image plus a local Docker Compose setup
- Static assets served using a production-appropriate strategy
- No public JSON or REST API in the first release

Business rules should live in testable service modules rather than views, templates, signals, or scheduled-task definitions.

## 10. Production-readiness baseline

- Secure password storage using Django defaults
- Expiring, single-use invitation tokens
- CSRF protection, secure cookies, HTTPS-aware settings, and strict host configuration
- Household-level authorization checks on every read and write
- Server-side input validation and safe file-free completion notes
- Database constraints for important invariants
- Structured logging and error reporting hooks
- Health and readiness endpoints
- Idempotent scheduled jobs and retry-safe email delivery
- Database migration and rollback procedures
- Automated backup expectations documented for paid production hosting
- Responsive and keyboard-accessible primary workflows
- Unit, integration, permission, and end-to-end smoke tests
- Continuous integration for formatting, linting, tests, and migration checks

The free demonstration host may sleep and may not provide a production uptime guarantee. Production-ready describes the application and deployment artifacts, not the service level of the free host.

## 11. Explicitly out of scope

- One-time chores
- Membership in multiple households
- Social sign-in or passwordless authentication
- Native mobile applications
- Public API
- Chat, comments, and household announcements
- Points, rewards, streaks, or gamification
- Photo or file proof
- User-configurable reminder schedules
- Repeated overdue email reminders
- Automatic reassignment without organizer approval
- More than two weeks of history in the user interface

## 12. Delivery milestones

1. **Foundation:** Django project, custom user model, PostgreSQL, Docker, CI, and environment configuration.
2. **Households:** roles, invitations, adult membership, child profiles, and authorization boundaries.
3. **Chores:** recurring definitions, effective-next-week edits, occurrence generation, and completion.
4. **Fair assignment:** capacity targets, prior-week compensation, eligibility rules, deterministic allocation, and explanation totals.
5. **Operations:** scheduled assignment, SendGrid delivery, due-day reminders, idempotency, and delivery records.
6. **Adjustments:** reassignment requests, organizer decisions, direct overrides, and audit records.
7. **Experience:** responsive dashboard, current/previous week views, accessibility, and empty/error/loading states.
8. **Hardening:** security review, full test suite, observability, deployment documentation, and free-tier demo deployment.

## 13. Acceptance criteria

The first release is complete when:

- An organizer can create a household and invite an adult by email.
- An organizer can create a managed child profile.
- Members can create daily and weekly recurring chores with estimated minutes and eligibility.
- Sunday allocation produces valid, deterministic, capacity-weighted assignments and accounts for the previous week.
- Daily chore occurrences can be distributed among different members.
- Users can see their chores, the household schedule, and fairness totals on mobile and desktop.
- Assignment and due-day emails are sent exactly once to the correct recipients.
- Adults and organizers can complete eligible occurrences with an optional note.
- Missed occurrences become overdue without blocking later occurrences.
- Reassignment requests and organizer overrides work and are auditable.
- Household data cannot be accessed or modified by users outside that household.
- Automated tests cover the allocator, scheduling, permissions, invitations, reminders, completion, and reassignment workflows.
- The project can be built and run from documented Docker commands and deployed to a sleeping free-tier demonstration environment.
