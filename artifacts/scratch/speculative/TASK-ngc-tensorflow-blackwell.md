# Task: NGC TensorFlow C API for Blackwell GPU Support

## Problem Statement

Nomarr's base Docker image builds essentia from source against Google's pre-compiled TF 2.18.0 GPU C API
(`libtensorflow-gpu-linux-x86_64.tar.gz`). This C API binary ships SASS kernels up to sm_89 (Ada/RTX 40)
and PTX for compute_90 (Hopper). On production servers with Blackwell GPUs (compute capability 12.0,
CUDA driver 13.0), TF falls back to JIT-compiling PTX at runtime, causing a ~30-minute stall on every
TF session creation.

TF 2.18.0 is the last pre-compiled GPU C API Google published. No newer version exists. Nightly C API
builds stopped in January 2024. Building TF from scratch requires CUDA 12.8+ and LLVM/Clang 20+ — not
feasible with current compute resources.

NVIDIA's NGC TensorFlow containers (`nvcr.io/nvidia/tensorflow`) are built by NVIDIA with native Blackwell
support (CUDA 12.8+, sm_120 kernels). The goal is to extract or derive a TF C API library from NGC that
includes Blackwell-native kernels, then rebuild essentia against it.

**Key constraint:** Essentia links against the TF **C API** (`libtensorflow.so.2` exporting `TF_NewSession`,
`TF_SessionRun`, `TF_AllocateTensor`, etc.), NOT the Python bindings. NGC containers may only ship
the Python package, not the standalone C API library. This plan must discover the actual contents
of the NGC container and determine the viable extraction path.

## Phases

### Phase 1: NGC Container Discovery

- [x] Pull the latest NGC TF container (`nvcr.io/nvidia/tensorflow:25.xx-tf2-py3`) on a machine with Docker + NVIDIA runtime
    **Notes:** Pulled `nvcr.io/nvidia/tensorflow:25.02-tf2-py3` (27.8GB, created 2025-02-20). Image available locally.
- [x] Search the NGC container filesystem for `libtensorflow.so*` and `libtensorflow_framework.so*` (check `/usr/local/lib/`, `/usr/lib/`, Python site-packages)
    **Notes:** No standalone `libtensorflow.so.2` found. Key libraries discovered:
`/usr/local/lib/python3.12/dist-packages/tensorflow/libtensorflow_cc.so.2` — exports ALL C API symbols (TF_NewSession, TF_SessionRun, TF_AllocateTensor, TF_GraphImportGraphDef, TF_SetConfig, TF_NewGraph, TF_DeleteSession).
`/usr/local/lib/python3.12/dist-packages/tensorflow/libtensorflow_framework.so.2` — framework lib.
`/usr/local/lib/tensorflow/libtensorflow_cc.so.2` — duplicate copy.
`_pywrap_tensorflow_internal.so` exists but does NOT export C API symbols.
- [x] Identify the TF version, CUDA toolkit version, and cuDNN version inside the NGC container
    **Notes:** TensorFlow 2.17.0 (NVIDIA Release 25.02-tf2, build 143088766). CUDA toolkit 12.8 (V12.8.61). cuDNN 9.7.1. Python 3.12.
- [x] Check if NGC ships pre-compiled CUDA kernels for sm_120 by examining TF's internal kernel cache or build config
    **Notes:** NGC TF build info confirms sm_120 (Blackwell) pre-compiled SASS kernels. Full CUDA compute capabilities: `['sm_100', 'sm_120', 'sm_75', 'sm_80', 'sm_86', 'compute_90']`. Also includes TensorRT support. This means zero JIT compilation on Blackwell hardware.
- [x] Document all TF-related shared libraries found, their paths, sizes, and SONAME versions
    **Notes:** Library inventory:
`libtensorflow_cc.so.2` (1.3GB) at `/usr/local/lib/python3.12/dist-packages/tensorflow/` — SONAME `libtensorflow_cc.so.2`, NEEDED: libtensorflow_framework.so.2, libnccl.so.2, standard libc/stdc++.
`libtensorflow_framework.so.2` (66MB) at same path — SONAME `libtensorflow_framework.so.2`.
`/usr/local/lib/tensorflow/libtensorflow_cc.so.2` is a symlink to the dist-packages copy.
TF C API headers exist at `/usr/local/lib/python3.12/dist-packages/tensorflow/include/tensorflow/c/c_api.h`.
No Python dependency — pure C/C++ linkage. Also needs libnccl.so.2 at runtime.
- [x] Check NGC's `nvcc --list-gpu-code` or equivalent to confirm compute capability targets
    **Notes:** NGC's nvcc (CUDA 12.8) supports sm_120 natively. Full arch list: sm_50 through sm_120. TF build info already confirmed sm_120 pre-compiled SASS in P1-S4. Phase 1 Discovery complete — all findings consistent: `libtensorflow_cc.so.2` exports C API symbols, has sm_120 kernels, no Python deps, headers available.

### Phase 2: C API Extraction Strategy

- [x] If `libtensorflow.so.2` exists in NGC, verify it exports the C API symbols essentia needs (`TF_NewSession`, `TF_SessionRun`, `TF_AllocateTensor`, `TF_GraphImportGraphDef`, `TF_SetConfig`)
    **Notes:** No standalone `libtensorflow.so.2` exists — but `libtensorflow_cc.so.2` exports ALL 27 C API symbols essentia uses (verified via nm -D): TF_NewGraph, TF_NewSession, TF_SessionRun, TF_AllocateTensor, TF_DeleteTensor, TF_GraphImportGraphDef, TF_SetConfig, TF_GraphOperationByName, TF_LoadSessionFromSavedModel, TF_CloseSession, TF_DeleteSession, etc. NGC path: `/usr/local/lib/python3.12/dist-packages/tensorflow/libtensorflow_cc.so.2`. Headers at same prefix under `include/tensorflow/c/c_api.h`. Extraction strategy: copy libtensorflow_cc.so.2 + libtensorflow_framework.so.2 + headers from NGC, create symlink libtensorflow.so.2 -> libtensorflow_cc.so.2 (or adjust pkg-config to use -ltensorflow_cc).
- [x] If standalone C API is absent, investigate essentia's `setup_from_python.sh` path that links against `_pywrap_tensorflow_internal.so` + `libtensorflow_framework.so.2` from pip TF
    **Notes:** Not needed — P2-S1 confirmed `libtensorflow_cc.so.2` exports all C API symbols. The `setup_from_python.sh` path creates symlinks + pkg-config from pip TF; we'll do the equivalent directly from NGC's `libtensorflow_cc.so.2` + `libtensorflow_framework.so.2`. The essentia waf build uses pkg-config to find `tensorflow` package — we just need a correct `tensorflow.pc` pointing to the NGC libraries.
- [x] If neither path works, determine if NGC's bazel cache or build artifacts allow building just `//tensorflow/tools/lib_package:libtensorflow` without a full TF rebuild
    **Notes:** Not needed — P2-S1 found a direct extraction path. No bazel rebuild required.
- [x] Decide on extraction strategy: direct copy, pip-install NGC TF wheel in builder stage, or hybrid
    **Notes:** Strategy: **Direct COPY --from NGC container** (multi-stage).
Add `nvcr.io/nvidia/tensorflow:25.02-tf2-py3 AS ngc-tf` as build stage.
COPY `libtensorflow_cc.so.2` + `libtensorflow_framework.so.2` + headers from NGC into essentia-builder.
Create symlink `libtensorflow.so -> libtensorflow_cc.so.2` so essentia's `-ltensorflow` pkg-config works.
Update `tensorflow.pc` to version 2.17.0 (NGC's TF version).
Update Stage 2 runtime to `nvidia/cuda:12.8.1-runtime-ubuntu24.04` to match NGC's CUDA 12.8.
Install cuDNN 9.7 (matching NGC) instead of 9.3.
Ensure `libnccl.so.2` available at runtime (NEEDED by libtensorflow_cc.so.2).
Key insight: SONAME is `libtensorflow_cc.so.2` — essentia ELF will record this as NEEDED, which is correct.

### Phase 3: Dockerfile Modification

- [x] Update `dockerfile.base` Stage 1 to source TF libraries from NGC instead of Google's tarball (exact approach depends on Phase 2 findings)
    **Notes:** Rewrote dockerfile.base: Added ngc-tf stage, COPY libs+headers from NGC, symlinks for -ltensorflow, updated pkg-config. Builder base updated to cuda:12.8.1-devel. Staging copies libtensorflow_cc*and libtensorflow_framework*.
- [x] Update the `tensorflow.pc` pkg-config file to point to the NGC-sourced libraries and headers
    **Notes:** Folded into P3-S1. The tensorflow.pc is created inline in the symlink RUN block with correct Libs (-ltensorflow) and Cflags (-I/usr/local/include/tensorflow) pointing to NGC-sourced files.
- [ ] Verify essentia `waf configure --with-tensorflow` succeeds against the new TF libraries
- [ ] Verify essentia `waf build` compiles and links successfully
- [x] Update Stage 2 runtime to copy the correct libraries (may need different cuDNN version if NGC bundles a newer one)
    **Notes:** Folded into P3-S1. Runtime uses nvidia/cuda:12.8.1-runtime-ubuntu24.04, cuDNN 9.7.1 (from local repo installer), libnccl2 package, and sanity probe checks libtensorflow_cc.so.2 via ctypes.
- [ ] Verify the sanity probe (`python3 -c "from essentia.standard import TensorflowPredict2D"`) passes

### Phase 4: Validation

- [ ] Build the complete base image locally and verify essentia imports work
- [ ] Test ML inference on a GPU (any available GPU) to confirm TF session creation succeeds without JIT warnings
- [ ] If Blackwell hardware is available, verify zero PTX JIT compilation (no "jit-compiled from PTX" warning)
- [ ] Run `lint_project_backend` to verify no Python code changes are needed
- [ ] Update `docker/compose.yaml` to remove or make optional the `tf_kernel_cache` volume (no longer needed if kernels are pre-compiled)

## Completion Criteria

- Essentia builds against NGC-sourced TF libraries with Blackwell (sm_120) pre-compiled kernels
- Base image builds successfully with `docker build -f dockerfile.base`
- ML inference runs on Blackwell GPU without PTX JIT compilation warning
- No regression on non-Blackwell GPUs (sm_89 and lower still work)

## References

- Current TF download: `dockerfile.base` line 31
- Essentia fork: `build_resources/essentia/` (branch `nomarr` on `xiaden/essentia`)
- Essentia TF C API usage: `build_resources/essentia/src/algorithms/machinelearning/tensorflowpredict.cpp`
- Alternative linking path: `build_resources/essentia/src/3rdparty/tensorflow/setup_from_python.sh`
- NGC container: `nvcr.io/nvidia/tensorflow` at <https://catalog.ngc.nvidia.com/orgs/nvidia/containers/tensorflow>
- NGC release notes: <https://docs.nvidia.com/deeplearning/frameworks/tensorflow-release-notes/>
- TF Blackwell issue: TF GitHub — no official support as of TF 2.18.0
