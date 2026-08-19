"""Typed failures for the Phase 6 identity boundary."""


class IdentityError(Exception):
    """Base identity-domain error."""


class OwnerBootstrapError(IdentityError):
    """The single-owner bootstrap invariant was not satisfied."""


class EnrollmentRejectedError(IdentityError):
    """An enrollment code is invalid, expired, consumed, or otherwise unusable."""


class AuthenticationError(IdentityError):
    """A reusable device credential failed generic authentication."""


class ScopeDeniedError(IdentityError):
    """An authenticated device lacks a required transport scope."""


class CapabilityEscalationError(IdentityError):
    """A heartbeat attempted to report a non-approved capability."""


class DeviceNotFoundError(IdentityError):
    """A local administrative command named no known device."""
