"""Bounded single-process worker: persisted queue, no DB transaction during AI."""

import asyncio
import logging

from app.diagnostics import log_internal_error
from app.evaluation.budget import evaluation_scope
from app.services import evaluations

logger = logging.getLogger("cqa.worker")


class EvaluationWorker:
    def __init__(self, factory, pipeline, concurrency=2):
        self.factory, self.pipeline, self.concurrency = factory, pipeline, concurrency
        self.tasks = []

    async def start(self):
        with self.factory.begin() as db:
            count = evaluations.recover(db)
        if count:
            logger.warning("event=evaluation_recovered error=INTERRUPTED records=%d", count)
        self.tasks = [asyncio.create_task(self.run()) for _ in range(self.concurrency)]
        logger.info("event=evaluation_worker_started concurrency=%d", self.concurrency)

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []
        logger.info("event=evaluation_worker_stopped")

    def _fail(self, id_, code, message, provenance=None):
        try:
            with self.factory.begin() as db:
                evaluations.fail(db, id_, code, message, provenance)
        except Exception as exc:
            log_internal_error("EVALUATION_SAVE_FAILED", exc)
            logger.error("event=evaluation_failure_save_failed error=EVALUATION_SAVE_FAILED")
            return
        logger.error("event=evaluation_failed status=failed error=%s", code)

    async def run(self):
        from app.evaluation.errors import EvaluationError

        while True:
            id_ = None
            provenance = None
            try:
                with self.factory.begin() as db:
                    claimed = evaluations.claim(db)
                if claimed is None:
                    await asyncio.sleep(0.2)
                    continue
                id_, transcript, checklist = claimed
                logger.info("event=evaluation_started status=running")
                # The snapshot transaction has committed and its Session is closed.
                with evaluation_scope(id_):
                    result = await self.pipeline.evaluate(
                        transcript=transcript, checklist=checklist
                    )
                provenance = result.provenance
                with self.factory.begin() as db:
                    evaluations.complete(db, id_, result)
                logger.info("event=evaluation_completed status=completed")
            except asyncio.CancelledError as exc:
                if id_ is not None:
                    self._fail(
                        id_,
                        "INTERRUPTED",
                        "Оценка прервана. Создайте новый запуск.",
                        getattr(exc, "provenance", None) or provenance,
                    )
                raise
            except EvaluationError as exc:
                if id_ is not None:
                    self._fail(id_, exc.code, exc.safe_message, exc.provenance)
            except Exception as exc:
                log_internal_error("EVALUATION_INTERNAL_ERROR", exc)
                if id_ is not None:
                    self._fail(
                        id_,
                        "EVALUATION_INTERNAL_ERROR",
                        "Не удалось выполнить AI-оценку",
                        provenance,
                    )
                else:
                    logger.error("event=evaluation_claim_failed error=EVALUATION_INTERNAL_ERROR")
                    await asyncio.sleep(1)


async def start_evaluation_worker(app):
    from app.evaluation.pipeline import EvaluationPipeline
    from app.services.budget import SqlBudgetGuard

    # One engine/account covers every future SDK attempt, independently of batches.
    engine = app.state.session_factory.kw["bind"]
    guard = SqlBudgetGuard(engine, app.state.settings)
    guard.initialize()
    app.state.budget_guard = guard

    pipeline = getattr(app.state, "evaluation_pipeline", None)
    app.state.evaluation_pipeline_injected = pipeline is not None
    if pipeline is None:
        pipeline = EvaluationPipeline(app.state.settings, budget_guard=guard)
    app.state.evaluation_pipeline = pipeline
    worker = EvaluationWorker(
        app.state.session_factory, pipeline, app.state.settings.evaluation_concurrency
    )
    app.state.evaluation_worker = worker
    await worker.start()


async def stop_evaluation_worker(app):
    worker = getattr(app.state, "evaluation_worker", None)
    if worker is not None:
        await worker.stop()
        app.state.evaluation_worker = None
    pipeline = getattr(app.state, "evaluation_pipeline", None)
    if pipeline is not None and not getattr(app.state, "evaluation_pipeline_injected", False):
        close = getattr(pipeline, "aclose", None)
        if close is not None:
            await close()
        app.state.evaluation_pipeline = None
