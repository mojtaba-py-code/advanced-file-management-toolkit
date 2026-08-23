"""Custom exception hierarchy for the Advanced File Management Toolkit.

A single, well-defined hierarchy makes it possible to catch toolkit-specific
failures without accidentally swallowing unrelated errors.
"""

from __future__ import annotations


class ToolkitError(Exception):
    """Base class for every error raised by the toolkit."""


class SecurityError(ToolkitError):
    """Raised when an operation would violate a security guarantee.

    Examples: path traversal outside an allowed root, attempting to operate
    on a symlink when symlinks are disallowed, or writing over a protected
    system path.
    """


class PathValidationError(SecurityError):
    """Raised when a user-supplied path fails validation."""


class ConfirmationDeclined(ToolkitError):
    """Raised when the user declines a destructive operation."""


class ConfigError(ToolkitError):
    """Raised when configuration cannot be loaded or is invalid."""


class OperationError(ToolkitError):
    """Raised when a filesystem operation fails in a recoverable way."""


class IntegrityError(ToolkitError):
    """Raised when a checksum/integrity verification fails."""
