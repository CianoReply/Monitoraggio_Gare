"""Funzioni di supporto ai test che leggono `docs/API_CONTRACT.yaml`."""

from typing import Any

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def resolve(spec: dict, node: Any) -> Any:
    """Risolve ricorsivamente i $ref locali (il contratto non ha riferimenti circolari)."""
    if isinstance(node, dict):
        if "$ref" in node:
            target: Any = spec
            for part in node["$ref"].removeprefix("#/").split("/"):
                target = target[part]
            return resolve(spec, target)
        return {key: resolve(spec, value) for key, value in node.items()}
    if isinstance(node, list):
        return [resolve(spec, value) for value in node]
    return node
