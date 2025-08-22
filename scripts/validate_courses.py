#!/usr/bin/env python3
import json
import sys
from jsonschema import Draft202012Validator


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: validate_courses.py <schema.json> <data.json>")
        return 2

    schema_path, data_path = sys.argv[1], sys.argv[2]
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(data[0] if isinstance(data, list) and data else data))
    if errors:
        for err in errors:
            print(f"error: {err.message} at {list(err.path)}")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())


