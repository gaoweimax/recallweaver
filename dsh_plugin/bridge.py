"""Invoke the installed RecallWeaver Python adapter for the DSH plugin."""

import json
import sys
from typing import Any

from plugins.dsh_adapter import DSHMemoryAdapter


def main() -> None:
    request: dict[str, Any] = json.load(sys.stdin)
    user_id = request.get("user_id")
    message = request.get("message")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id must be a non-empty string")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")

    prompt = DSHMemoryAdapter().on_message(user_id, message)
    sys.stdout.write(prompt)


if __name__ == "__main__":
    main()
