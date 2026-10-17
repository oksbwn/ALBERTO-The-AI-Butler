"""Auth Providers: fetch/extract/inject credentials for downstream tool calls."""

from alberto.auth_providers.resolver import AuthResolver, ResolvedAuth

__all__ = ["AuthResolver", "ResolvedAuth"]
