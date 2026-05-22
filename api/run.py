from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=int(os.getenv("API_PORT", "8000")),
        reload=os.getenv("APP_ENV", "development") == "development",
    )


if __name__ == "__main__":
    main()
