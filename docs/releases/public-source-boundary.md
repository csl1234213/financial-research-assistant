# Public-source boundary

This repository is exported from the clean, validated ce0b9c6 application tree without its .git directory or commit history. The original repository remains unchanged.

Publication-only security changes remove a retired signing-key literal from source and tests. Its SHA256 remains a rejection predicate, preserving production validation semantics. A fresh synthetic test checks the hash rejection branch and case normalization; it does not reproduce the retired value.

Two API-shaped security fixtures remain. Both were independently checked against the original reachable history and their complete test contexts: one tests isolated in-memory settings confidentiality/user scoping, the other pure Fernet key rotation. Exact Gitleaks fingerprints are the only exceptions; no directory, rule or entropy exception is used.

Private production overlays and env files are not included. Deployment evidence is summarized without user identities, container identifiers, private paths, database data or backup manifests. Public SEC sample reports and synthetic test fixtures are distinct from production uploads.

Production JWT rotation was not performed by public publication. The current production key was independently verified different from the retired historical default. This repository does not claim to remove already-published history from the original repository.
