# Task: Windows Native Install — Part B: Bundling and Packaging

## Problem Statement

With essentia.pyd built for Windows (Part A), this plan assembles all runtime components
into a self-contained Windows installer. The installer must require no external databases,
no Docker, no opened network ports, and no user-visible configuration. ArangoDB runs as a
bundled child process communicating over a Windows named pipe. Python runs from an
embeddable zip. GPU ML tagging works if the user has an NVIDIA GPU with a recent driver;
otherwise inference falls back silently to CPU.

**Prerequisite:** TASK-windows-native-A-essentia-build.md

## Phases

### Phase 1: Runtime Assembly

- [ ] Download the ArangoDB Windows binary package (zip, not installer) and stage the minimum required files (arangod.exe, arangosh.exe, etc.) into build_resources/win-runtime/arangodb/
- [ ] Download Python 3.12 Windows embeddable zip and stage into build_resources/win-runtime/python/
- [ ] Install nomarr Python dependencies into the embeddable Python layout using pip with --target, excluding essentia (provided separately)
- [ ] Copy essentia.pyd and all DLLs from win-runtime/ (from Part A) into the embeddable Python site-packages
- [ ] Copy Vite-built frontend from nomarr/public_html/ into the runtime layout (already built; no extra step needed)

### Phase 2: ArangoDB Named Pipe Integration

- [ ] Create build_resources/config/arangodb-windows.conf configuring --server.endpoint windows://\\\\.\\pipe\\nomarr-arango, --database.directory to a user-local data path, and authentication disabled for the named pipe endpoint
- [ ] Add a Windows named pipe connection string option to nomarr/services/config_service.py (e.g. NOMARR_DB_ENDPOINT env var defaulting to the pipe URI on Windows)
- [ ] Implement arangod.exe lifecycle management in a new nomarr/helpers/arango_process.py: start on app startup, healthcheck loop, graceful shutdown on exit
- [ ] Update nomarr/app.py startup sequence to invoke arango_process.start() before the first DB connection attempt when running in bundled mode
- [ ] Verify python-arango connects successfully over the named pipe endpoint in a local integration test

### Phase 3: Launcher and Installer

- [ ] Create build_resources/scripts/nomarr-launcher.ps1 that sets PYTHONPATH to the embedded layout, starts uvicorn on 127.0.0.1 only, and opens the browser to <http://127.0.0.1:8356>
- [ ] Compile a small nomarr-launcher.exe wrapper (e.g. with PyInstaller --onefile or a Go stub) so users double-click an exe rather than a ps1
- [ ] Write an NSIS or WiX installer definition in build_resources/installer/ that bundles win-runtime/, arangodb/, embedded Python, and the launcher exe
- [ ] Add a GitHub Actions workflow .github/workflows/build-windows-installer.yml that builds the installer on push to feat/windows-native-install and on tagged releases, uploading the .exe as a release artifact
- [ ] Smoke-test the installer on a clean GitHub Actions Windows runner: install, launch, verify /info endpoint responds, verify ArangoDB named pipe connection, verify ML tagging completes on a fixture file

## Completion Criteria

- A single .exe installer produces a working nomarr installation with no external dependencies
- ArangoDB communicates exclusively over the named pipe — no TCP port opened
- nomarr binds to 127.0.0.1 only — no network interface exposure
- ML tagging works end-to-end on a machine with an NVIDIA GPU and recent driver
- CPU-only machines complete tagging without error (slower but functional)
- GitHub Actions produces the installer artifact automatically on release tags

## References

- Part A: TASK-windows-native-A-essentia-build.md
- ArangoDB Windows binary downloads: <https://www.arangodb.com/download-major/>
- Python embeddable zip: <https://www.python.org/downloads/windows/>
- python-arango named pipe endpoint: ArangoClient(hosts='http+unix://...')
- NSIS installer: <https://nsis.sourceforge.io/>
