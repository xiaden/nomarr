#!/usr/bin/env python3
"""Patch msd-musicnn-1.onnx: replace conv2d_3 Conv with MatMul decomposition.

The Conv node (kernel [51,1,64,1], asymmetric time padding pre=31/post=32)
triggers HEURISTIC_QUERY_FAILED from cuDNN Frontend on SM750 (Turing) hardware.
The Frontend has no valid engine configs for this low-channel asymmetric geometry.

The replacement uses only standard GEMM ops (MatMul + helpers): all computation
routes through cuBLAS, bypassing cuDNN entirely. The transformation is
mathematically equivalent; numerical verification asserts max_abs_diff < 1e-3.

The substitution:
    Conv([N,1,187,96], W[51,1,64,1], pads=[31,0,32,0])
    →
    Pad([N,1,187,96], [0,0,31,0,0,0,32,0])               → [N,1,250,96]
    Reshape(→ [N,250,96])                                  drop channel dim
    Gather(axis=1, indices[187*64])                        → [N,11968,96]
    Reshape(→ [N,187,64,96])                               window view
    Transpose(perm=[0,3,1,2])                              → [N,96,187,64]
    MatMul(W_mat[64,51])                                   → [N,96,187,51]
    Transpose(perm=[0,3,2,1])                              → [N,51,187,96]
    Add(bias[1,51,1,1])                                    broadcast bias

Usage:
    python patch_musicnn_conv.py <src.onnx> <dst.onnx>
"""

from __future__ import annotations

import os
import sys

import numpy as np
import onnx
from onnx import helper, numpy_helper

# ---------------------------------------------------------------------------
# Constants describing the target conv geometry
# ---------------------------------------------------------------------------
_TARGET_W_SHAPE = [51, 1, 64, 1]
_N_OUT_TIME = 187
_KERNEL_SIZE = 64
_MEL_BINS = 96


def _find_conv_node(
    graph: onnx.GraphProto,
) -> tuple[onnx.NodeProto, dict[str, onnx.TensorProto]] | tuple[None, None]:
    """Return the Conv node whose weight matches _TARGET_W_SHAPE, plus the init map."""
    init_map = {init.name: init for init in graph.initializer}
    for node in graph.node:
        if node.op_type != "Conv":
            continue
        if len(node.input) < 2:
            continue
        w_name = node.input[1]
        if w_name not in init_map:
            continue
        w = numpy_helper.to_array(init_map[w_name])
        if list(w.shape) == _TARGET_W_SHAPE:
            return node, init_map
    return None, None


def _get_conv_time_pads(conv_node: onnx.NodeProto) -> tuple[int, int]:
    """Return (pad_time_begin, pad_time_end) from Conv pads attribute."""
    # Conv pads for 2D spatial: [h_begin, w_begin, h_end, w_end]
    for attr in conv_node.attribute:
        if attr.name == "pads":
            return int(attr.ints[0]), int(attr.ints[2])
    return 0, 0


def patch_model(src_path: str, dst_path: str) -> None:
    """Load the ONNX model at src_path, apply the Conv→MatMul patch, save to dst_path."""
    model = onnx.load(src_path)
    graph = model.graph

    # -----------------------------------------------------------------------
    # Find the target Conv node
    # -----------------------------------------------------------------------
    conv_node, init_map = _find_conv_node(graph)
    if conv_node is None:
        print(f"[patch] Conv node with weight {_TARGET_W_SHAPE} not found — nothing to do")
        return

    assert init_map is not None  # init_map is None iff conv_node is None

    print(f"[patch] Found Conv node: {conv_node.name!r}")

    time_pad_begin, time_pad_end = _get_conv_time_pads(conv_node)
    padded_time = _N_OUT_TIME + time_pad_begin + time_pad_end
    print(f"[patch] Time padding: begin={time_pad_begin}, end={time_pad_end} → padded={padded_time}")

    x_name = conv_node.input[0]  # [N, 1, 187, 96]
    w_name = conv_node.input[1]
    b_name = conv_node.input[2] if len(conv_node.input) > 2 and conv_node.input[2] else None
    out_name = conv_node.output[0]  # [N, 51, 187, 96]

    # -----------------------------------------------------------------------
    # Derive new weight matrix and Gather indices
    # -----------------------------------------------------------------------
    w_orig = numpy_helper.to_array(init_map[w_name])  # [51, 1, 64, 1]
    w_mat = w_orig.squeeze().T.astype(np.float32)  # [64, 51]

    # Sliding-window indices: for each output time t gather frames t..t+63
    indices = np.array(
        [t + k for t in range(_N_OUT_TIME) for k in range(_KERNEL_SIZE)],
        dtype=np.int64,
    )  # shape [11968]

    # -----------------------------------------------------------------------
    # Build new node names (use a safe prefix)
    # -----------------------------------------------------------------------
    pfx = (conv_node.name or "conv2d_3").replace("/", "_") + "_mm"

    # Intermediate tensor names
    pad_out = f"{pfx}_pad"
    reshape0_out = f"{pfx}_r0"
    gather_out = f"{pfx}_gather"
    reshape1_out = f"{pfx}_r1"
    tp1_out = f"{pfx}_tp1"
    mm_out = f"{pfx}_mm"

    # -----------------------------------------------------------------------
    # New initializers
    # -----------------------------------------------------------------------
    # Pad uses pads as tensor input (ONNX opset 11+)
    pads_val = np.array([0, 0, time_pad_begin, 0, 0, 0, time_pad_end, 0], dtype=np.int64)
    pads_init = numpy_helper.from_array(pads_val, name=f"{pfx}_pads_const")

    # Reshape [N,1,padded_time,96] → [N,padded_time,96]; 0 means "copy input dim"
    shape0_val = np.array([0, padded_time, _MEL_BINS], dtype=np.int64)
    shape0_init = numpy_helper.from_array(shape0_val, name=f"{pfx}_shape0")

    # Gather index tensor
    idx_init = numpy_helper.from_array(indices, name=f"{pfx}_idx")

    # Reshape [N,11968,96] → [N,187,64,96]
    # shape: 187 windows x 64 kernel frames x 96 mel bins
    shape1_val = np.array([0, _N_OUT_TIME, _KERNEL_SIZE, _MEL_BINS], dtype=np.int64)
    shape1_init = numpy_helper.from_array(shape1_val, name=f"{pfx}_shape1")

    # Weight matrix [64, 51]
    w_mat_init = numpy_helper.from_array(w_mat, name=f"{pfx}_W")

    new_inits = [pads_init, shape0_init, idx_init, shape1_init, w_mat_init]

    # -----------------------------------------------------------------------
    # New nodes
    # -----------------------------------------------------------------------
    pad_node = helper.make_node(
        "Pad",
        inputs=[x_name, f"{pfx}_pads_const"],
        outputs=[pad_out],
        name=f"{pfx}_pad_node",
    )

    reshape0_node = helper.make_node(
        "Reshape",
        inputs=[pad_out, f"{pfx}_shape0"],
        outputs=[reshape0_out],
        name=f"{pfx}_reshape0",
    )

    gather_node = helper.make_node(
        "Gather",
        inputs=[reshape0_out, f"{pfx}_idx"],
        outputs=[gather_out],
        name=f"{pfx}_gather_node",
        axis=1,
    )

    reshape1_node = helper.make_node(
        "Reshape",
        inputs=[gather_out, f"{pfx}_shape1"],
        outputs=[reshape1_out],
        name=f"{pfx}_reshape1",
    )

    # [N,187,64,96] → [N,96,187,64]
    tp1_node = helper.make_node(
        "Transpose",
        inputs=[reshape1_out],
        outputs=[tp1_out],
        name=f"{pfx}_tp1",
        perm=[0, 3, 1, 2],
    )

    # [N,96,187,64] @ [64,51] → [N,96,187,51]
    mm_node = helper.make_node(
        "MatMul",
        inputs=[tp1_out, f"{pfx}_W"],
        outputs=[mm_out],
        name=f"{pfx}_matmul",
    )

    new_nodes = [pad_node, reshape0_node, gather_node, reshape1_node, tp1_node, mm_node]

    if b_name:
        # Bias: [51] → reshape to [1,51,1,1] for broadcasting after final Transpose
        b_orig = numpy_helper.to_array(init_map[b_name])
        b_rs = b_orig.reshape(1, 1, 1, 51).astype(np.float32)  # [1,1,1,51] for pre-transpose
        bias_init = numpy_helper.from_array(b_rs, name=f"{pfx}_B")
        new_inits.append(bias_init)

        # Add bias before transpose: [N,96,187,51] + [1,1,1,51] → [N,96,187,51]
        add_out = f"{pfx}_add"
        add_node = helper.make_node(
            "Add",
            inputs=[mm_out, f"{pfx}_B"],
            outputs=[add_out],
            name=f"{pfx}_add_node",
        )
        new_nodes.append(add_node)
        tp2_input = add_out
    else:
        tp2_input = mm_out

    # [N,96,187,51] → [N,51,187,96]
    tp2_node = helper.make_node(
        "Transpose",
        inputs=[tp2_input],
        outputs=[out_name],
        name=f"{pfx}_tp2",
        perm=[0, 3, 2, 1],
    )
    new_nodes.append(tp2_node)

    # -----------------------------------------------------------------------
    # Splice into graph
    # -----------------------------------------------------------------------
    conv_idx = list(graph.node).index(conv_node)
    del graph.node[conv_idx]
    for i, node in enumerate(new_nodes):
        graph.node.insert(conv_idx + i, node)

    for init in new_inits:
        graph.initializer.append(init)

    # Remove old Conv weight/bias initializers (no longer referenced)
    stale = {w_name}
    if b_name and b_name in {init.name for init in graph.initializer}:
        stale.add(b_name)
    for i in range(len(graph.initializer) - 1, -1, -1):
        if graph.initializer[i].name in stale:
            del graph.initializer[i]

    # -----------------------------------------------------------------------
    # Validate and save
    # -----------------------------------------------------------------------
    model = onnx.shape_inference.infer_shapes(model)
    onnx.checker.check_model(model)

    os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
    onnx.save(model, dst_path)
    print(f"[patch] Saved patched model → {dst_path}")


def verify_numerical(src_path: str, dst_path: str) -> None:
    """Run both models on random input; assert outputs are numerically equivalent."""
    try:
        import onnxruntime as ort
    except ImportError:
        print("[verify] onnxruntime not available — skipping numerical check")
        return

    print("[verify] Loading sessions…")
    sess_orig = ort.InferenceSession(src_path, providers=["CPUExecutionProvider"])
    sess_patch = ort.InferenceSession(dst_path, providers=["CPUExecutionProvider"])

    input_meta = sess_orig.get_inputs()[0]
    input_name = input_meta.name
    # Replace symbolic dims with concrete values (batch=2)
    shape = [2 if (isinstance(d, str) or d is None or d == 0) else d for d in input_meta.shape]
    print(f"[verify] Input: name={input_name!r}, shape={shape}")

    rng = np.random.default_rng(42)
    x = rng.standard_normal(shape).astype(np.float32)

    orig_outs = sess_orig.run(None, {input_name: x})
    patch_outs = sess_patch.run(None, {input_name: x})

    all_pass = True
    for i, (o, p) in enumerate(zip(orig_outs, patch_outs, strict=False)):
        out_name = sess_orig.get_outputs()[i].name
        max_diff = float(np.max(np.abs(o - p)))
        status = "OK" if max_diff < 1e-3 else "FAIL"
        print(f"  [{status}] output[{i}] {out_name!r}: shape={o.shape}, max_abs_diff={max_diff:.3e}")
        if max_diff >= 1e-3:
            all_pass = False

    if all_pass:
        print("[verify] Numerical verification PASSED ✓")
    else:
        print("[verify] Numerical verification FAILED ✗")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <src.onnx> <dst.onnx>")
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    patch_model(src, dst)
    verify_numerical(src, dst)
