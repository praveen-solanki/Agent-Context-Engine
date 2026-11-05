"""Reuse existing providers, retries and meters, with a shared request ceiling."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from agent_context.benchmarks.models import Experiment, Measurement, Usage
from agent_context.benchmarks.storage import fingerprint
from agent_context.evaluation import MeteredTransport, reported_tokens
from context_graph.config import Settings
from context_graph.providers.chat_backend import ChatLLMProvider, EmbeddingProviderImpl


class RequestLimitExceeded(RuntimeError):
    """Stop before a provider request; never retry a depleted experiment budget."""


class RequestBudget:
    def __init__(self, maximum: int) -> None:
        self.maximum, self.used = maximum, 0

    def take(self) -> None:
        if self.used >= self.maximum:
            raise RequestLimitExceeded("experiment provider-request ceiling reached")
        self.used += 1


class LimitedTransport(MeteredTransport):
    def __init__(self, settings: Settings, budget: RequestBudget) -> None:
        super().__init__(settings)
        self.budget = budget

    async def _post_once(
        self, path: str, payload: dict[str, Any], label: str
    ) -> dict[str, Any]:
        self.budget.take()
        return await super()._post_once(path, payload, label)


class MeteredEmbedding(EmbeddingProviderImpl):
    def __init__(
        self, settings: Settings, budget: RequestBudget, *, query: bool
    ) -> None:
        super().__init__(
            embedding=settings.embedding, retry=settings.retry, for_query=query
        )
        self.budget = budget
        self.attempts = self.failed = self.tokens = self.unreported = 0

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.budget.take()
        self.attempts += 1
        try:
            response = await super()._post(payload)
        except Exception:
            self.failed += 1
            raise
        usage = response.get("usage") or {}
        tokens = reported_tokens(usage, "prompt_tokens")
        if tokens is None:
            tokens = reported_tokens(usage, "total_tokens")
        if tokens is None:
            self.unreported += 1
        else:
            self.tokens += int(tokens)
        return response


class Providers:
    def __init__(self, settings: Settings, experiment: Experiment) -> None:
        self.experiment = experiment
        self.context_tokens = settings.llm.context_limit_tokens
        self.embedding_batch_size = settings.embedding.batch_size
        self.prompt_safety_tokens = settings.llm.safety_margin_tokens
        self.configuration: dict[str, Any] = {
            "chat": {
                "base_url_sha256": fingerprint(settings.chat.base_url),
                "temperature": settings.llm.temperature,
                "structured_output": settings.chat.structured_output.value,
                "token_parameter": settings.chat.token_parameter,
                "repair_attempts": settings.chat.repair_attempts,
            },
            "embedding": {
                "base_url_sha256": fingerprint(settings.embedding.base_url),
                "backend": settings.embedding.backend.value,
                "batch_size": settings.embedding.batch_size,
            },
            "pipeline": {
                key: getattr(settings, key).model_dump(mode="json")
                for key in (
                    "llm",
                    "segmentation",
                    "gate",
                    "resolution",
                    "promotion",
                    "batching",
                    "maintenance",
                    "retry",
                )
            },
        }
        self.configuration["pipeline"]["llm"]["unresolved_reference_values"] = sorted(
            settings.llm.unresolved_reference_values
        )
        self.budget = RequestBudget(experiment.max_provider_requests)
        self.transports: dict[str, LimitedTransport] = {}
        self.llms: dict[str, ChatLLMProvider] = {}
        for role, model in (
            ("answer", experiment.answer_model),
            ("ingestion", experiment.ingestion_model),
            ("judge", experiment.judge_model),
        ):
            resolved = settings.model_copy(
                update={
                    "chat": settings.chat.model_copy(
                        update={"chat_model": model or settings.chat.chat_model}
                    )
                }
            )
            transport = LimitedTransport(resolved, self.budget)
            self.transports[role] = transport
            self.llms[role] = ChatLLMProvider(
                backend=resolved.chat, llm=resolved.llm, transport=transport
            )
        self.passages = MeteredEmbedding(settings, self.budget, query=False)
        self.queries = MeteredEmbedding(settings, self.budget, query=True)

    def snapshot(self) -> dict[str, Usage]:
        values = {
            role: Usage(
                model=self.llms[role].model,
                attempts=meter.attempts,
                failed_attempts=meter.failed_attempts,
                prompt_tokens=meter.prompt_tokens,
                completion_tokens=meter.completion_tokens,
                unreported=meter.missing_usage_responses,
            )
            for role, meter in self.transports.items()
        }
        for role, embedding in (
            ("passage_embedding", self.passages),
            ("query_embedding", self.queries),
        ):
            values[role] = Usage(
                model=embedding.model,
                attempts=embedding.attempts,
                failed_attempts=embedding.failed,
                prompt_tokens=embedding.tokens,
                unreported=embedding.unreported,
            )
        return values

    def measure(self, before: dict[str, Usage], started: float) -> Measurement:
        delta: dict[str, Usage] = {}
        cost: float | None = 0.0
        for role, after in self.snapshot().items():
            values = {
                key: getattr(after, key) - getattr(before[role], key)
                for key in Usage.model_fields
                if key != "model"
            }
            usage = Usage(model=after.model, **values)
            delta[role] = usage
            if usage.attempts:
                pricing = self.experiment.prices.get(usage.model)
                if pricing is None or usage.unreported or usage.failed_attempts:
                    cost = None
                elif cost is not None:
                    cost += (
                        usage.prompt_tokens * pricing.input_per_million_usd
                        + usage.completion_tokens * pricing.output_per_million_usd
                    ) / 1000000
        return Measurement(
            seconds=perf_counter() - started, usage=delta, known_cost_usd=cost
        )

    async def close(self) -> None:
        for transport in self.transports.values():
            await transport.aclose()
        await self.passages.aclose()
        await self.queries.aclose()
