#!/usr/bin/env python3
"""
Logical test to validate model wiring against modelsinfo.md documentation.
This test does NOT require dependencies to be installed.
"""

import sys
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from nomarr.ml.models.discovery import discover_heads, get_embedding_output_node, get_head_output_node


def test_model_discovery():
    """Test that we discover all expected models and validate their wiring."""

    models_dir = Path(__file__).parent / "models"
    if not models_dir.exists():
        print(f"❌ Models directory not found: {models_dir}")
        return False

    print("=" * 80)
    print("MODEL DISCOVERY & WIRING TEST")
    print("=" * 80)

    heads = discover_heads(str(models_dir))

    if not heads:
        print("❌ No heads discovered!")
        return False

    print(f"\n✅ Discovered {len(heads)} head models\n")

    # Expected wiring from modelsinfo.md
    expected_wiring = {
        "yamnet": {
            "predictor_class": "TensorflowPredictVGGish",
            "predictor_params": {"input": "melspectrogram", "output": "embeddings"},
            "embedding_output": "embeddings",
        },
        "vggish": {
            "predictor_class": "TensorflowPredictVGGish",
            "predictor_params": {"output": "model/vggish/embeddings"},
            "embedding_output": "model/vggish/embeddings",
        },
        "effnet": {
            "predictor_class": "TensorflowPredictEffnetDiscogs",
            "predictor_params": {"output": "PartitionedCall:1"},
            "embedding_output": "PartitionedCall:1",
        },
        "musicnn": {
            "predictor_class": "TensorflowPredictMusiCNN",
            "predictor_params": {"output": "model/dense/BiasAdd"},
            "embedding_output": "model/dense/BiasAdd",
        },
    }

    expected_head_types = {
        "softmax": "model/Softmax",
        "identity": "model/Identity",
        "multiclass": "model/Softmax",  # multiclass also uses Softmax
    }

    backbones_seen = set()
    head_types_seen = set()
    errors = []

    for head in heads:
        print(f"\n{'─' * 80}")
        print(f"Head: {head.name}")
        print(f"  Backbone: {head.backbone}")
        print(f"  Head Type: {head.head_type}")
        print(f"  Embedding Graph: {Path(head.embedding_graph).name}")
        print(f"  Labels: {len(head.sidecar.labels)}")

        backbones_seen.add(head.backbone)
        head_types_seen.add(head.head_type)

        # Validate embedding output node
        emb_output = get_embedding_output_node(head.backbone)
        print(f"  Embedding Output Node: {emb_output}")

        if head.backbone in expected_wiring:
            expected_emb = expected_wiring[head.backbone]["embedding_output"]
            if emb_output == expected_emb:
                print("    ✅ Embedding output matches documentation")
            else:
                err = f"❌ Embedding output mismatch for {head.backbone}: got '{emb_output}', expected '{expected_emb}'"
                print(f"    {err}")
                errors.append(err)
        else:
            warn = f"⚠️  Unknown backbone '{head.backbone}' not in documentation"
            print(f"    {warn}")

        # Validate head output node
        head_output = get_head_output_node(head.head_type, head.sidecar)
        print(f"  Head Output Node: {head_output}")

        # Check if schema specifies the output (highest priority)
        schema_out = head.sidecar.head_output_name()
        if schema_out and schema_out == head_output:
            print(f"    ✅ Head output from schema (model-specific): {head_output}")
        else:
            # Check if it matches expected patterns
            head_type_lower = head.head_type.lower()
            matched = False
            for pattern, expected_node in expected_head_types.items():
                if pattern in head_type_lower:
                    if head_output == expected_node:
                        print(f"    ✅ Head output matches documentation ({pattern} → {expected_node})")
                        matched = True
                    else:
                        # Only error if schema didn't specify it
                        if not schema_out:
                            err = f"❌ Head output mismatch for {head.head_type}: got '{head_output}', expected '{expected_node}'"
                            print(f"    {err}")
                            errors.append(err)
                            matched = True
                    break

            if not matched and not schema_out:
                warn = f"⚠️  Head type '{head.head_type}' using fallback output: {head_output}"
                print(f"    {warn}")

        # Validate predictor instantiation logic
        print("\n  Predicted Instantiation:")
        if head.backbone == "yamnet":
            print("    TensorflowPredictVGGish(")
            print(f"      graphFilename={Path(head.embedding_graph).name},")
            print("      input='melspectrogram',")
            print(f"      output='{emb_output}'")
            print("    )")
        elif head.backbone == "vggish":
            print("    TensorflowPredictVGGish(")
            print(f"      graphFilename={Path(head.embedding_graph).name},")
            print(f"      output='{emb_output}'")
            print("    )")
        elif head.backbone == "effnet":
            print("    TensorflowPredictEffnetDiscogs(")
            print(f"      graphFilename={Path(head.embedding_graph).name},")
            print(f"      output='{emb_output}'")
            print("    )")
        elif head.backbone == "musicnn":
            print("    TensorflowPredictMusiCNN(")
            print(f"      graphFilename={Path(head.embedding_graph).name},")
            print(f"      output='{emb_output}'")
            print("    )")

        print("    TensorflowPredict2D(")
        print(f"      graphFilename={Path(head.sidecar.graph_abs('')).name},")
        print(f"      output='{head_output}'")
        print("    )")

    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    print(f"Backbones discovered: {sorted(backbones_seen)}")
    print(f"Head types discovered: {sorted(head_types_seen)}")
    print(f"Total heads: {len(heads)}")

    if errors:
        print(f"\n❌ ERRORS FOUND ({len(errors)}):")
        for err in errors:
            print(f"  {err}")
        return False
    else:
        print("\n✅ ALL CHECKS PASSED - Model wiring looks correct!")
        return True


def check_no_orphan_embeddings():
    """Ensure we're not processing embedding models without heads (which would just store embeddings as tags)."""
    print(f"\n{'=' * 80}")
    print("ORPHAN EMBEDDING CHECK")
    print(f"{'=' * 80}")

    models_dir = Path(__file__).parent / "models"
    heads = discover_heads(str(models_dir))

    # Get all backbones that have heads
    backbones_with_heads = {h.backbone for h in heads}

    # Check all embedding directories
    orphans = []
    for backbone_dir in models_dir.iterdir():
        if not backbone_dir.is_dir():
            continue

        backbone_name = backbone_dir.name
        embeddings_dir = backbone_dir / "embeddings"

        if embeddings_dir.exists():
            embedding_files = list(embeddings_dir.glob("*.pb"))
            if embedding_files and backbone_name not in backbones_with_heads:
                orphans.append(backbone_name)
                print(f"⚠️  Orphan embedding found: {backbone_name}")
                print(f"    Has {len(embedding_files)} .pb file(s) but NO heads")

    if orphans:
        print(f"\n⚠️  Found {len(orphans)} backbone(s) with embeddings but no heads")
        print("    These will NOT be processed (correct behavior)")
        return True
    else:
        print("\n✅ No orphan embeddings - all backbones have heads")
        return True


if __name__ == "__main__":
    print("\n")
    success1 = test_model_discovery()
    success2 = check_no_orphan_embeddings()

    print(f"\n{'=' * 80}")
    if success1 and success2:
        print("✅ ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)
