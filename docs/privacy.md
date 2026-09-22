# Privacy

Apogee stores a record of what someone reads on the web. That is sensitive by nature, so privacy is
a design constraint from the first table.

> **Status.** The browser extension and its local privacy filtering are **future work** and are not
> implemented. This document states the principles the project commits to and how the Day 1 database
> and API were shaped so those controls are easy to add. It does not describe features that exist.

## Principles

Apogee should:

1. **Never require browser cookies.**
2. **Never collect passwords.**
3. **Never collect authentication tokens.**
4. **Never collect form input.**
5. **Exclude sensitive domains before data leaves the browser.** Filtering happens in the
   extension, prior to upload; the server should never receive what it must not keep.
6. **Not capture Incognito/private browsing by default.**
7. **Let the user define their own exclusions** (domains, patterns), in addition to sensible defaults
   for categories such as banking and health.
8. **Support deletion of stored user data**, from a single page up to everything.
9. **Minimise what is collected**: only what retrieval needs.

## How the Day 1 design supports this

- **Minimal schema.** `browsing_events` holds a URL, title, domain, timestamps, and an optional
  session identifier. There is no column for cookies, credentials, tokens, form values, headers, or
  arbitrary browser state, so there is nowhere to put them by accident.
- **Cascading deletion.** Every table is owned by a user with `ON DELETE CASCADE`:
  - deleting a user removes all their devices, pages and events;
  - deleting a device removes the events it captured;
  - deleting a page removes the events that reference it.
  Any future table (embeddings, sessions, …) must follow the same rule, so data derived from a page
  cannot outlive it. The database enforces this, so it does not depend on application code.
- **Ownership is enforced, not assumed.** Composite foreign keys stop an event from referencing
  another user's device or page.
- **Hard deletes.** Privacy deletion removes rows rather than flagging them, so nothing is retained
  "soft-deleted".
- **No secrets in code or config files in git.** Credentials come from environment variables;
  `.env` is git-ignored.
- **The health endpoint exposes no user data** and hides connection details in error responses.

## Server-side validation (Day 2)

`POST /api/v1/capture` adds a first server-side layer. It is **defence in depth only**: the browser
extension (future) must filter *before upload*, so the server never receives what it must not keep.

- **Only known fields are accepted.** Any other key (cookies, passwords, tokens, form values, browser
  storage, page text, ...) is rejected with `422`, not ignored. The request has no field in which
  such data could be stored.
- **Only `http`/`https` URLs** are accepted; `javascript:`, `data:`, `file:`, `chrome:` and the rest
  are rejected.
- **URLs with embedded credentials** (`https://user:pass@host/`) are rejected.
- **Fragments and known tracking parameters are removed** before anything is stored, and **the raw
  URL is never persisted**: events and pages hold only the normalised URL. (Fragments can carry
  tokens, e.g. OAuth implicit-flow responses.)
- **Timestamps** must carry a timezone and be plausible (not before 2000, not in the future), and
  titles are length-limited and free of NUL characters.
- **Error responses never echo the request.** Validation errors report where and why, not the
  submitted values; server errors are generic.
- **Logging.** The service logs identifiers and counts only, never URLs or titles. The database
  engine hides bound parameters, so URLs and titles do not appear in SQLAlchemy exception text or
  logs. Server-side tracebacks for unexpected errors still include exception messages.

## Known gaps and risks (to be addressed by future work)

- **URLs can still contain secrets.** The server drops fragments, embedded credentials and known
  *tracking* parameters, but it cannot know which arbitrary query parameters are sensitive: a
  magic-login link (`?token=...`) or a session id in a path or query is stored as sent. The
  extension's privacy filter must drop or strip such URLs *before upload*.
- **Partial deletion leaves orphans.** Deleting events by time range or domain does not by itself
  delete a `pages` row that no longer has any events (and would keep its title and extracted text).
  A deletion service will need to remove such pages.
- **Backups and logs.** Database backups, write-ahead logs and any application logs may retain
  deleted data for their retention period; a deletion policy must cover them.
- **No authentication yet.** `POST /api/v1/capture` trusts the `user_id` and `device_id` it is
  given, so anyone who can reach the port can write events for any user. Until authentication
  exists, run the backend only on a trusted machine and network. The development compose file
  binds ports to `127.0.0.1` for that reason.
- **Transport and storage encryption** are not addressed at this stage.
