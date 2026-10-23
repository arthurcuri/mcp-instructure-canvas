"""Translate owner replies without weakening the provider's approval boundary."""

import unicodedata

from jsonschema import exceptions, validators


def confirmation(text: str) -> bool | None:
    value = "".join(
        char
        for char in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(char)
    )
    value = " ".join(value.strip(" \t\r\n.!?").split())
    if value in {"sim", "s", "yes", "y", "ok", "autorizo", "eu autorizo", "permito", "yes i allow"}:
        return True
    if value in {"nao", "n", "no", "nego", "nao autorizo", "negar"}:
        return False
    return None


def valid_form(schema: dict, content: object) -> bool:
    if not isinstance(schema, dict):
        return False
    # MCP forms are inline. Never retrieve a schema reference over the network.
    pending = [schema]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if {"$ref", "$dynamicRef", "$recursiveRef"}.intersection(value):
                return False
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    try:
        validator = validators.validator_for(schema)
        validator.check_schema(schema)
        return isinstance(content, dict) and validator(schema).is_valid(content)
    except (exceptions.SchemaError, TypeError, ValueError):
        return False


def is_confirmation(params: dict) -> bool:
    """Only a form with no fields and a valid empty result is a yes/no prompt."""
    schema = params.get("requestedSchema")
    return (
        params.get("mode") == "form"
        and isinstance(schema, dict)
        and schema.get("type") == "object"
        and schema.get("properties") == {}
        and valid_form(schema, {})
    )
