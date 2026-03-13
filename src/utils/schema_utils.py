from typing import Any, Dict, List, Optional

try:
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover
    jsonschema = None


class SchemaError(ValueError):
    pass


class ValidationError(ValueError):
    pass


def _is_type(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    return True


def check_json_schema(schema: Dict[str, Any]) -> None:
    if not isinstance(schema, dict):
        raise SchemaError("schema must be an object")
    if jsonschema is not None:
        jsonschema.Draft202012Validator.check_schema(schema)
        return
    if "type" in schema and schema["type"] not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
        raise SchemaError(f"unsupported schema type: {schema['type']}")
    props = schema.get("properties")
    if props is not None and not isinstance(props, dict):
        raise SchemaError("properties must be an object")
    if isinstance(props, dict):
        for child in props.values():
            if isinstance(child, dict):
                check_json_schema(child)
    items = schema.get("items")
    if items is not None and isinstance(items, dict):
        check_json_schema(items)


def _validate_recursive(instance: Any, schema: Dict[str, Any], path: str = "$") -> None:
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _is_type(instance, expected_type):
        raise ValidationError(f"{path} expected {expected_type}")

    if "enum" in schema and instance not in schema.get("enum", []):
        raise ValidationError(f"{path} must be one of {schema.get('enum')}")

    if expected_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", True)
        if not isinstance(instance, dict):
            raise ValidationError(f"{path} expected object")
        for req in required:
            if req not in instance:
                raise ValidationError(f"{path}.{req} is required")
        for key, value in instance.items():
            if key in properties and isinstance(properties[key], dict):
                _validate_recursive(value, properties[key], f"{path}.{key}")
            elif additional is False:
                raise ValidationError(f"{path}.{key} is not allowed")
    elif expected_type == "array":
        items = schema.get("items")
        if not isinstance(instance, list):
            raise ValidationError(f"{path} expected array")
        if isinstance(items, dict):
            for idx, value in enumerate(instance):
                _validate_recursive(value, items, f"{path}[{idx}]")


def validate_json_instance(instance: Any, schema: Dict[str, Any]) -> None:
    check_json_schema(schema)
    if jsonschema is not None:
        jsonschema.validate(instance=instance, schema=schema)
        return
    _validate_recursive(instance, schema, "$")

