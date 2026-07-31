# Data Classification

| Class | Examples | Default handling |
|---|---|---|
| Public | Open-source code, public docs | May be committed |
| Internal | Architecture notes without secrets | Repository access only |
| Personal | Tasks, routines, conversations, project history | Encrypted storage; never in Git |
| Sensitive personal | Location, health, nutrition, contacts, screenshots | Explicit opt-in, minimum retention, encrypted |
| Secret | Tokens, private keys, passwords, cookies | Secret store only; never logged or committed |
| Critical control | Device signing keys, unlock/control credentials | Isolated storage, rotation, strongest approval |

## Rules

- Tests use synthetic data.
- Logs contain identifiers only when needed and must support redaction.
- Raw audio, screenshots, and camera data are not retained by default.
- Memory must be inspectable, correctable, and deletable.
- Every new data domain must define source, purpose, retention, deletion, backup, and access scope.
