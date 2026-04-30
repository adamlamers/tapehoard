#!/usr/bin/env python3
"""Dump the FastAPI OpenAPI schema to a JSON file without starting the server."""

import json
import sys
from pathlib import Path

from app.main import app

# Add the backend directory to the path so we can import app.main
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))


def main():
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    schema = app.openapi()
    output_path.write_text(json.dumps(schema, indent=2))
    print(f"OpenAPI schema written to {output_path}")


if __name__ == "__main__":
    main()
