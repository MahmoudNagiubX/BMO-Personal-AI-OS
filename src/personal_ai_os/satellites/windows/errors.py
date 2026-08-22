"""Sanitized Windows satellite transport errors."""


class SatelliteError(RuntimeError):
    def __init__(self, code: str, *, uncertain: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain


class SatelliteOfflineError(SatelliteError):
    pass


class SatelliteProtocolError(SatelliteError):
    pass


class DuplicateSatelliteSessionError(SatelliteError):
    pass


__all__ = [
    "DuplicateSatelliteSessionError",
    "SatelliteError",
    "SatelliteOfflineError",
    "SatelliteProtocolError",
]
