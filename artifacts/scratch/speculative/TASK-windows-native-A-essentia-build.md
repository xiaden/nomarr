# Task: Windows Native Install — Part A: Essentia Windows Build

## Problem Statement

Nomarr currently runs only in Docker due to essentia-tensorflow having no Windows binaries.
The goal is to build a Windows-native essentia Python extension (.pyd) linked against the
TF 2.10.0 GPU C API (the last Windows GPU release Google published) so that full ML tagging
works on Windows without Docker. This plan covers only the C++ build and verification;
bundling and packaging are in Part B.

Key constraints:

- Build must target exactly the 25 algorithms nomarr uses (slim build via --include-algos)
- TF C API must be 2.10.0 GPU Windows (libtensorflow.dll + cuDNN 8 DLLs) — GPU path only
- Python target: CPython 3.12 Windows x64
- Build environment: GitHub Actions Windows runner (MSVC or MinGW-w64)

## Phases

### Phase 1: Branch and Build Environment

- [ ] Create branch feat/windows-native-install from main
- [ ] Research whether upstream essentia wscript supports MSVC or requires MinGW-w64 on Windows, document findings in build_resources/essentia/windows-build-notes.md
- [ ] Download TF 2.10.0 GPU Windows C API zip from <https://storage.googleapis.com/tensorflow/libtensorflow/libtensorflow-gpu-windows-x86_64-2.10.0.zip> and inspect headers and .lib structure
- [ ] Download cuDNN 8.x Windows inference DLLs (cudnn64_8.dll, cudnn_ops_infer64_8.dll, cudnn_cnn_infer64_8.dll, cudnn_adv_infer64_8.dll) and confirm NVIDIA redistribution terms
- [ ] Document exact TF 2.10 / cuDNN 8 / CUDA 11 version triplet required in build_resources/win-runtime/VERSION.txt

### Phase 2: Third-Party Static Dependencies

- [ ] Audit which system libraries the slim 25-algorithm essentia build requires (fftw3, libsamplerate, libtag, libchromaprint, libyaml, libavcodec/avformat/avutil/swresample) and confirm Windows static build availability
- [ ] Add a build_resources/scripts/build_win32_3rdparty.sh cross-compile script (adapting upstream packaging/build_3rdparty_static_win32.sh) scoped to only the libs the slim build needs
- [ ] Verify FFmpeg Windows static libs cover the AudioLoader/MonoLoader codec chain nomarr uses
- [ ] Stage all compiled .a/.lib static deps into build_resources/win-static-deps/

### Phase 3: Essentia Waf Build for Windows

- [ ] Add waf configure invocation for Windows in build_resources/scripts/build_essentia_windows.sh with --with-python, --with-tensorflow, --include-algos matching the 25-algo list in dockerfile.base, and paths pointing to TF 2.10 headers and win-static-deps
- [ ] Resolve any wscript MSVC/MinGW flag issues surfaced during configure (reference upstream packaging/win32/ for known workarounds)
- [ ] Run waf build and produce essentia Python extension as essentia.pyd
- [ ] Stage essentia.pyd + all required runtime DLLs (libtensorflow.dll, cuDNN 8 DLLs) into build_resources/win-runtime/

### Phase 4: Verification

- [ ] Write tests/test_essentia_windows.py that imports essentia, instantiates MonoLoader and TensorflowPredict2D, and runs inference on a fixture audio file
- [ ] Run the test on a Windows GitHub Actions runner with the staged win-runtime artifacts and confirm pass
- [ ] Verify no symbol resolution errors for the full TF C API symbol set used in tensorflowpredict.cpp (TF_NewSession, TF_SessionRun, TF_LoadSessionFromSavedModel, etc.)
- [ ] Confirm essentia.__version__ matches the nomarr branch version

## Completion Criteria

- essentia.pyd loads in CPython 3.12 on Windows x64 without import errors
- TensorflowPredict2D runs inference against a real MTG model file on Windows
- All verification tests pass on a clean GitHub Actions Windows runner
- win-runtime/ directory contains a complete, documented set of redistributable DLLs

## References

- Part B: TASK-windows-native-B-packaging.md
- TF 2.10 GPU Windows C API: <https://storage.googleapis.com/tensorflow/libtensorflow/libtensorflow-gpu-windows-x86_64-2.10.0.zip>
- Upstream static win32 build scripts: build_resources/essentia/packaging/win32_3rdparty/
- Slim build algo list: dockerfile.base ARG ESSENTIA_ALGOS
