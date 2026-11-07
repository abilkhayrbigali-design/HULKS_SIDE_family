import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def make_engine(url: str):
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite:") else {},
    )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_settings(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def session_factory(engine):
    factory = sessionmaker(engine, expire_on_commit=False)

    @event.listens_for(factory, "after_commit")
    def log_saved_operations(session):
        summary = session.info.pop("cqa_import_summary", None)
        if summary is not None:
            logging.getLogger("cqa.import").info(
                "event=dataset_import_completed status=completed "
                "records=%d created=%d new_versions=%d unchanged=%d",
                summary["received"],
                summary["created"],
                summary["new_versions"],
                summary["unchanged"],
            )
        count = session.info.pop("cqa_checklist_versions", 0)
        if count:
            logging.getLogger("cqa.checklists").info(
                "event=checklist_version_saved records=%d", count
            )
        for key, event_name in (
            ("cqa_evaluation_queued", "evaluation_queued"),
            ("cqa_appeal_created", "appeal_created"),
            ("cqa_appeal_decided", "appeal_decision_saved"),
        ):
            count = session.info.pop(key, 0)
            if count:
                logging.getLogger("cqa.evaluation").info("event=%s records=%d", event_name, count)

    @event.listens_for(factory, "after_rollback")
    def discard_saved_operations(session):
        session.info.pop("cqa_import_summary", None)
        session.info.pop("cqa_checklist_versions", None)
        for key in ("cqa_evaluation_queued", "cqa_appeal_created", "cqa_appeal_decided"):
            session.info.pop(key, None)

    return factory
