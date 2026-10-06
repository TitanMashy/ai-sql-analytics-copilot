"""Retention job: delete expired conversations and old audit records.

    python -m app.jobs.purge

Run it on a schedule (cron, a Kubernetes CronJob, a scheduled CI job); see docs/operations.md. It is
idempotent and safe to run concurrently with the application. With the in-process conversation
store there is nothing durable to purge and the conversation step reports 0.
"""

from __future__ import annotations

import json
import logging

from app.conversation.service import get_conversation_memory
from app.core.audit import purge_audit_records
from app.core.config import get_settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def run_purge() -> dict[str, int]:
    settings = get_settings()
    conversations = get_conversation_memory().purge_expired()
    audit_rows = 0
    if settings.audit_sink in {"database", "both"}:
        audit_rows = purge_audit_records(SessionLocal, settings.audit_retention_days)
    return {"conversations_purged": conversations, "audit_records_purged": audit_rows}


def main() -> None:
    print(json.dumps(run_purge()))


if __name__ == "__main__":
    main()
