# ADR-001: Use ONNX Runtime for ML Inference

**Status:** Accepted  
**Date:** 2026-04-02  
**Tags:** ml, performance  
**Source Log:** rnd-ddauthor#L5  

## Context

We need a fast ML inference backend that works cross-platform

## Decision

Use ONNX Runtime as the primary inference engine

## Consequences

Must convert all models to ONNX format before deployment

## References

- [ONNX Runtime docs](https://onnxruntime.ai)
