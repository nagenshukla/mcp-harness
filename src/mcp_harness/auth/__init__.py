"""Authentication backends: resolve transport credentials into a :class:`Principal`."""

from .anonymous import AnonymousAuth
from .api_key import APIKeyAuth
from .azure_ad import AzureADAuth
from .base import AuthMiddleware, BaseAuth
from .chained import ChainedAuth

__all__ = [
    "BaseAuth",
    "AuthMiddleware",
    "AnonymousAuth",
    "APIKeyAuth",
    "ChainedAuth",
    "AzureADAuth",
]
