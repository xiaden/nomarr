---
name: Bug Report
about: Report a bug or unexpected behavior
title: '[BUG] '
labels: bug
assignees: ''
---

## Bug Description

A clear and concise description of what the bug is.

## Steps to Reproduce

1. Go to '...'
2. Click on '...'
3. Run command '...'
4. See error

## Expected Behavior

What you expected to happen.

## Actual Behavior

What actually happened.

## Environment

**Nomarr Version:**
- Check `docker compose logs nomarr | grep version` or `config/nomarr.yaml`
- Commit hash: (if building from source)

**System:**
- OS: [e.g. Ubuntu 22.04, Windows 11, macOS 14]
- Docker version: [e.g. 24.0.7]
- Docker Compose version: [e.g. 2.23.0]
- GPU: [e.g. NVIDIA RTX 3090, none]
- CUDA version: [e.g. 12.3, N/A]

**Configuration:**
- Music library location: [e.g. local disk, NFS mount, SMB share]
- Watch mode: [e.g. event, poll, disabled]
- Any custom environment variables:

```yaml
# Paste relevant sections from docker-compose.yml or .env
```

## Logs

<details>
<summary>Nomarr container logs</summary>

```
# Paste output of: docker compose logs nomarr --tail=100
```

</details>

<details>
<summary>ArangoDB logs (if database-related)</summary>

```
# Paste output of: docker compose logs arangodb --tail=50
```

</details>

<details>
<summary>Browser console (if web UI issue)</summary>

```
# Press F12 in browser, go to Console tab, paste errors
```

</details>

## Additional Context

Add any other context about the problem here (screenshots, related issues, etc.)

## Workaround

If you found a temporary workaround, describe it here.