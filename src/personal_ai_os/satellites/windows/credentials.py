"""Windows current-user credential storage for the Phase 9 satellite."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any, Protocol

CREDENTIAL_TARGET = "BMO.PersonalAIOS.WindowsSatellite.v1"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class CredentialStore(Protocol):
    def read(self) -> str | None: ...

    def write(self, credential: str) -> None: ...

    def delete(self) -> None: ...


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _last_error() -> int:
    getter = getattr(ctypes, "get_last_error", None)
    return int(getter()) if getter is not None else 0


def _advapi32() -> Any:
    if os.name != "nt":
        raise OSError("Windows Credential Manager is available only on Windows")
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise OSError("Windows Credential Manager loader is unavailable")
    library = loader("Advapi32.dll", use_last_error=True)
    library.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    library.CredWriteW.restype = wintypes.BOOL
    library.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
    ]
    library.CredReadW.restype = wintypes.BOOL
    library.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    library.CredDeleteW.restype = wintypes.BOOL
    library.CredFree.argtypes = [ctypes.c_void_p]
    library.CredFree.restype = None
    return library


class WindowsCredentialStore:
    """Store one opaque bearer credential under the current Windows user."""

    def read(self) -> str | None:
        library = _advapi32()
        pointer = ctypes.POINTER(_CREDENTIALW)()
        if not library.CredReadW(
            CREDENTIAL_TARGET,
            _CRED_TYPE_GENERIC,
            0,
            ctypes.byref(pointer),
        ):
            if _last_error() == _ERROR_NOT_FOUND:
                return None
            raise OSError("Windows credential read failed")
        try:
            credential = pointer.contents
            blob = ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            return blob.decode("utf-16-le")
        finally:
            library.CredFree(pointer)

    def write(self, credential: str) -> None:
        if not credential or len(credential) > 128 or "\x00" in credential:
            raise ValueError("device credential is invalid")
        library = _advapi32()
        encoded = bytearray(credential.encode("utf-16-le"))
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer(encoded)
        value = _CREDENTIALW()
        value.Type = _CRED_TYPE_GENERIC
        value.TargetName = CREDENTIAL_TARGET
        value.CredentialBlobSize = len(encoded)
        value.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        value.Persist = _CRED_PERSIST_LOCAL_MACHINE
        value.UserName = "BMO Windows Satellite"
        try:
            if not library.CredWriteW(ctypes.byref(value), 0):
                raise OSError("Windows credential write failed")
        finally:
            for index in range(len(encoded)):
                encoded[index] = 0

    def delete(self) -> None:
        library = _advapi32()
        if (
            not library.CredDeleteW(CREDENTIAL_TARGET, _CRED_TYPE_GENERIC, 0)
            and _last_error() != _ERROR_NOT_FOUND
        ):
            raise OSError("Windows credential delete failed")


class MemoryCredentialStore:
    """Synthetic test store; production construction never selects it."""

    def __init__(self, credential: str | None = None) -> None:
        self.credential = credential

    def read(self) -> str | None:
        return self.credential

    def write(self, credential: str) -> None:
        self.credential = credential

    def delete(self) -> None:
        self.credential = None


__all__ = [
    "CREDENTIAL_TARGET",
    "CredentialStore",
    "MemoryCredentialStore",
    "WindowsCredentialStore",
]
