"""Local FastAPI server: static frontend, status/config API, WebSocket stream."""

from .app import create_app

__all__ = ["create_app"]
