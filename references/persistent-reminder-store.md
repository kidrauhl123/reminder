# Persistent reminder store notes

Session learning: when the user asks for reminder durability beyond cron's jobs.json, keep skill files immutable and put mutable state in the active Hermes profile data directory.

## Storage location

- Default profile path: `~/.hermes/data/reminders/reminders.sqlite`.
- Profile/test-safe implementation should derive the path from Hermes home / cron store context, not hardcode `/root/.hermes`.
- The skill directory is package/documentation territory only (`SKILL.md`, `references/`, `templates/`, `scripts/`), not runtime data.

## Schema shape

Minimum useful tables:

- `schema_meta(key, value, updated_at)` — schema version.
- `reminders` — one row per reminder-shaped cron job. Important columns: `id`, `cron_job_id`, `title`, `details`, `status`, `remind_at`, `due_at`, `repeat_rule`, `platform`, `chat_id`, `thread_id`, `user_id`, `source_message`, timestamps.
- `reminder_events` — append-only lifecycle history: `created`, `updated`, `paused`, `resumed`, `fired`, `failed`, `completed`, `cancelled`, `snoozed`.

## Integration pattern

- Treat `cron` as the scheduler and SQLite as reminder state/history.
- Only mirror cron jobs that intentionally load the reminder skill (`skills=["reminder"]` or legacy `skill="reminder"`), so unrelated automations do not pollute the reminder DB.
- On `cronjob(action="create")`, upsert a `reminders` row and append `created`.
- On `pause`/`resume`, sync status to `paused`/`active` and append events.
- On `remove`, keep history: mark `cancelled` and append `cancelled`; do not delete the row.
- On `mark_job_run`, append `fired`/`failed`; for terminal successful one-shot reminders, mark `done` and append `completed`.
- Hooks should be best-effort and non-fatal: reminder DB failure must not break cron scheduling/delivery.

## Verification

A focused test should cover:

1. Creating `skills=["reminder"]` cron writes the DB row under the active profile/test home.
2. `pause`/`resume`/successful one-shot run updates status and history.
3. `remove` leaves a cancelled historical row.

Focused command used successfully:

```bash
python -m pytest tests/tools/test_cronjob_tools.py tests/tools/test_reminder_persistence.py -q -o 'addopts='
```

Operational pitfall: if changes are made from inside the messaging gateway process, `hermes gateway restart` is blocked to avoid restart loops. Restart from an external shell for the running gateway to load new code.
