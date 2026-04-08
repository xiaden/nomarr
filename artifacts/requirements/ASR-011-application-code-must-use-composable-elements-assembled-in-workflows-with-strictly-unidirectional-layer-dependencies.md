# ASR-011: Application code must use composable elements assembled in workflows with strictly unidirectional layer dependencies

**Status:** Active  
**Date:** 2026-04-09  
**Quality Attribute:** Maintainability  
**Priority:** Critical  
**Source:** User requirement — April 2026  

## Stimulus

A developer adds code that either skips a layer or imports from a higher layer

## Response Measure

Any upward import is caught by import-linter. No layer contains logic belonging to a higher layer. Composable elements (components, workflows) are assembled by services, not duplicated across layers.

## Background

The Nomarr codebase is structured in named layers: interfaces → services → workflows → components → persistence/helpers. Each layer has a defined role. Business logic lives in components and workflows. Services wire things together. Interfaces route requests. Upward imports from lower layers into higher layers are forbidden and enforced by import-linter.

## Constraints

Imports must only flow downward. Same-layer lateral imports are permitted. Upward imports are forbidden. Import-linter enforces this at CI time.
