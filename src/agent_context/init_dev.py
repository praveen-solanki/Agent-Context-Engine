"""Create ignored local development authentication without printing secrets."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from pathlib import Path

from dotenv import set_key

from agent_context.contracts import Permission, Principal


def initialize(*, tenant_id: str, user_id: str) -> Path:
    path = Path(".env")
    user = Principal(
        tenant_id=tenant_id,
        user_id=user_id,
        actor_id=user_id,
        actor_kind="user",
        projects=frozenset({"research-project"}),
        permissions=frozenset(
            {Permission.VIEW, Permission.ASSERT, Permission.CORRECT, Permission.DELETE}
        ),
    )
    host = Principal(
        tenant_id=tenant_id,
        user_id=user_id,
        actor_id="research-agent",
        actor_kind="agent",
        projects=frozenset({"research-project"}),
        permissions=frozenset({Permission.VIEW, Permission.ASSERT}),
    )
    template = Path(".env.example").read_text()
    # Exclusive creation protects an existing user's configuration and values.
    with path.open("x") as output:
        path.chmod(0o600)
        output.write(template)
    bindings = {}
    for principal, variable in (
        (user, "ACE_DEMO_USER_TOKEN"),
        (host, "ACE_DEMO_AGENT_TOKEN"),
    ):
        token = secrets.token_urlsafe(36)
        set_key(path, variable, token)
        bindings[hashlib.sha256(token.encode()).hexdigest()] = principal.model_dump(
            mode="json"
        )
    for key, value in {
        "ACE_TENANT_ID": tenant_id,
        "ACE_USER_ID": user_id,
        "ACE_AUTH_BINDINGS": json.dumps(bindings, separators=(",", ":")),
    }.items():
        set_key(path, key, value)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="local-tenant")
    parser.add_argument("--user", default="local-user")
    args = parser.parse_args()
    path = initialize(tenant_id=args.tenant, user_id=args.user)
    print(
        f"Created {path} with private local user/host credentials. Configure the model credential securely before starting the worker."
    )
