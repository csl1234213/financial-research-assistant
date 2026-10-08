"""Bounded task-level stage driver; durable ledger, not queue delivery, is truth.

Queue adapters must retain/requeue retry_pending and lease_busy deliveries.
This driver never starts another stage while a live lease belongs to a worker.
"""

from core.ingestion_contracts import STAGES


class IngestionTaskRunner:
    def __init__(self, executor, *, ready_promotion=None, clock=None):
        self.executor = executor
        self.ledger = executor.ledger
        self.ready_promotion = ready_promotion
        self.clock = clock or getattr(executor, "clock", None)
        if ready_promotion is not None and not callable(self.clock):
            raise ValueError("READY_PROMOTION_CLOCK_REQUIRED")

    def _state(self, task_id, tenant_id, user_id):
        state = self.ledger.status(task_id, tenant_id, user_id)
        if (self.ready_promotion is not None and state["status"] not in {"ready", "failed", "quarantined"}
                and len(state["completed_stages"]) == len(STAGES)):
            self.ready_promotion.promote(task_id, tenant_id=tenant_id, user_id=user_id, now=self.clock())
            state = self.ledger.status(task_id, tenant_id, user_id)
        return state

    def run(self, task_id, *, tenant_id, user_id):
        # Authorization also applies to replayed queue deliveries. Never infer
        # scope from client metadata or reuse another user's source resolver.
        for _ in range(len(STAGES)):
            state = self._state(task_id, tenant_id, user_id)
            if state["status"] in {"ready", "failed", "quarantined"}:
                return state["status"]
            result = self.executor.run_one(task_id)
            if result in {"not_claimed", "lease_lost", "failed"}:
                state = self._state(task_id, tenant_id, user_id)
                if state["status"] in {"ready", "failed", "quarantined"}:
                    return state["status"]
                return "retry_pending" if state["status"] == "pending" else "lease_busy"
            if result == "quarantined":
                return "quarantined"
            if result != "completed":
                raise ValueError("UNKNOWN_STAGE_RESULT")
        state = self._state(task_id, tenant_id, user_id)
        return state["status"] if state["status"] in {"ready", "failed", "quarantined"} else "retry_pending"
