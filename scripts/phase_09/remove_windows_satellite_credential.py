"""Remove only the product-owned current-user satellite credential."""

from personal_ai_os.satellites.windows.credentials import WindowsCredentialStore


def main() -> None:
    WindowsCredentialStore().delete()
    print("PHASE_09_BMO_CREDENTIAL_REMOVED")


if __name__ == "__main__":
    main()
