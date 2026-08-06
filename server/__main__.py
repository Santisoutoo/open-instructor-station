"""Console entry point: ``instructor-station``."""

from __future__ import annotations

import logging

import uvicorn

from server.deps import get_settings

__all__ = ["main"]


def main() -> None:
    """Run the instructor station server with the configured settings."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    logging.getLogger(__name__).info(
        "Starting Open Instructor Station on %s:%s with the %r adapter",
        settings.host,
        settings.port,
        settings.adapter,
    )
    uvicorn.run(
        "server.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
