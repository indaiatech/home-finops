# Security Policy

## Local-First & Zero-Secret Posture

FinOps handles sensitive personal financial information. The repository enforces strict separation between open-source code and private data:

- **Secrets:** Pluggy `clientId`/`clientSecret`, PostgreSQL passwords, and the Hermes `FINOPS_MCP_TOKEN` must only live in `.env` (gitignored) or an external secret manager.
- **Personal Data & IaC Configs:** Personal YAML configs (`local/*.yaml`), bank exports (`*.csv`, `*.ofx`), and database dumps (`backups/`, `*.sql`, `*.dump`) are explicitly excluded in `.gitignore`.
- **Network Binding:** Local services in `docker-compose.yml` bind to `127.0.0.1` by default so PostgreSQL and the MCP server are not accidentally exposed on a LAN or public interface.
- **Audited Agent Access:** The `finops-mcp` server authenticates requests with a Bearer token and records every write action performed by Hermes in an immutable `audit_log` table.

## Reporting a Vulnerability

If you discover a security vulnerability in FinOps:

1. **Do not** open a public GitHub issue with exploit details.
2. Report it privately using GitHub Security Advisories (or contact the repository maintainers directly).
3. Include steps to reproduce, affected components, and any suggested mitigation.

We aim to acknowledge security reports within 72 hours and release a fix as promptly as possible.
