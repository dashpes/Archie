"""Notification transports. Email over SMTP is the only channel."""

from .email import EmailChannel

__all__ = ["EmailChannel"]
