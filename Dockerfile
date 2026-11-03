# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.4 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY retrieval_tester ./retrieval_tester
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    uv sync --frozen --no-dev --no-editable --system-certs
ENV PATH="/app/.venv/bin:$PATH" CG_LOG_FILE=/tmp/ace/context_graph.log
USER 1000:1000
EXPOSE 8000
CMD ["agent-context-api"]
