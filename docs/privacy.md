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

## Known gaps and risks (to be addressed by future work)

- **URLs can contain secrets** (magic-login links, OAuth codes, session ids in query strings). The
  schema stores the URL as given, so the extension's privacy filter must strip or drop such URLs
  *before upload*, and the server's URL normalisation should act as a second line of defence.
- **Partial deletion leaves orphans.** Deleting events by time range or domain does not by itself
  delete a `pages` row that no longer has any events (and would keep its title and extracted text).
  A deletion service will need to remove such pages.
- **Backups and logs.** Database backups, write-ahead logs and any application logs may retain
  deleted data for their retention period; a deletion policy must cover them.
- **No authentication yet.** Until authentication exists, the backend must only be run on a trusted
  machine and network. The development compose file binds ports to `127.0.0.1` for that reason.
- **Transport and storage encryption** are not addressed at this stage.
