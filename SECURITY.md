# Security Policy

## Project Status

⚠️ **Nomarr is alpha software** under active development. Security features are still being implemented and hardened. **Do not use Nomarr in production environments or expose it directly to the internet.**

## Supported Versions

Currently, only the latest commit on the `main` branch is supported. Version numbers are provisional during alpha.

| Version | Supported          |
| ------- | ------------------ |
| latest (main) | :white_check_mark: |
| < 0.1.x | :x:                |

## Security Considerations

### Current Security Features

- **API Key Authentication** - Bearer token auth for API endpoints
- **Session-based Auth** - Web UI uses secure session cookies
- **Docker Isolation** - Runs in containerized environment
- **Database Authentication** - ArangoDB requires credentials
- **No External Network Access** - ML models run locally, no telemetry

### Known Limitations (Alpha)

- **No HTTPS by default** - Run behind a reverse proxy (nginx, Traefik) for TLS
- **No rate limiting** - Can be abused if exposed to untrusted networks
- **No user management** - Single admin account only
- **Limited input validation** - File path validation is basic
- **No audit logging** - Security events are not tracked
- **Auto-generated credentials** - First-run passwords are logged to stdout

### Recommended Deployment

**For self-hosted use:**

1. **Do not expose to internet** - Run on LAN/VPN only
2. **Use a reverse proxy** - nginx or Traefik with TLS termination
3. **Bind to localhost** - Use `127.0.0.1:8356` and proxy from reverse proxy
4. **Strong passwords** - Change auto-generated admin password immediately
5. **Regular updates** - Pull latest images frequently during alpha
6. **Filesystem permissions** - Music library should be read-only for Nomarr
7. **Backup database** - ArangoDB data in `config/db` should be backed up

**Docker security:**

```yaml
# Example docker-compose.yml security hardening
services:
  nomarr:
    read_only: true  # Filesystem read-only
    tmpfs:
      - /tmp
      - /run
    cap_drop:
      - ALL
    cap_add:
      - CHOWN  # Only if needed for file operations
    security_opt:
      - no-new-privileges:true
```

## Reporting a Vulnerability

**Do not open public issues for security vulnerabilities.**

### How to Report

1. **GitHub Security Advisories** (preferred):
   - Go to https://github.com/xiaden/nomarr/security/advisories
   - Click "Report a vulnerability"
   - Fill in the details

2. **Via GitHub Discussions** (for lower-severity issues):
   - Open a private discussion with the maintainer
   - Tag as "security"

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Affected versions/commits
- Potential impact
- Suggested fix (if known)

### What to Expect

- **Initial response:** Within 48-72 hours
- **Status update:** Within 7 days
- **Fix timeline:** Depends on severity
  - Critical: Hotfix within days
  - High: Patch within 2 weeks
  - Medium/Low: Included in next release

**Note:** As an alpha project with a single maintainer, response times may vary. Critical vulnerabilities will be prioritized.

## Security Best Practices for Users

### Environment Variables

- **Never commit `.env` files** to version control
- **Use strong passwords** for `NOMARR_ARANGO_ROOT_PASSWORD`
- **Rotate API keys** if compromised

### File System Access

- **Mount music libraries read-only** when possible:
  ```yaml
  volumes:
    - /path/to/music:/music:ro
  ```
- **Limit Nomarr's write access** to only necessary directories
- **Use separate Docker volumes** for config and database

### Network Security

- **Run on trusted networks only** (LAN/VPN)
- **Use firewall rules** to restrict access
- **Enable HTTPS** via reverse proxy for remote access
- **Consider authentication proxy** (Authelia, oauth2-proxy) for additional security

### Updates

```bash
# Pull latest images regularly
docker compose pull
docker compose up -d

# Check for breaking changes in commit messages
git log --oneline
```

## Disclosure Policy

Once a vulnerability is fixed:

1. **Fix is merged** to main branch
2. **Security advisory is published** (GitHub Security Advisories)
3. **Release notes include** CVE/vulnerability details
4. **Users are notified** via GitHub Discussions

We follow **coordinated disclosure** - vulnerabilities are not made public until a fix is available.

## Out of Scope

- Issues requiring physical access to the host machine
- Social engineering attacks
- Vulnerabilities in third-party dependencies (report to upstream projects)
- Issues that require user to run untrusted code
- DoS attacks (alpha has no DoS protection)

## Dependencies

Nomarr relies on:

- **Python 3.12+** - Security updates via official Python channels
- **FastAPI** - Web framework security
- **ArangoDB** - Database security
- **Essentia** - ML model security
- **TensorFlow** - ML inference security

**Dependency updates:** Automated via Dependabot (once configured). Security advisories for dependencies are monitored.

## Future Security Roadmap

- [ ] HTTPS support with Let's Encrypt
- [ ] User management and RBAC
- [ ] Rate limiting and request throttling
- [ ] Audit logging
- [ ] CSP headers for web UI
- [ ] Input sanitization hardening
- [ ] Secrets management (HashiCorp Vault, etc.)
- [ ] Security scanning in CI/CD
- [ ] Penetration testing

---

**Last Updated:** February 4, 2026
