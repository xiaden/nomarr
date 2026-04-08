# ASR-012: The interface layer must contain no business logic and must only interact with the service layer

**Status:** Active  
**Date:** 2026-04-09  
**Quality Attribute:** Maintainability  
**Priority:** Critical  
**Source:** User requirement — April 2026  

## Stimulus

A developer adds logic to an interface layer handler that makes a domain decision or calls a component/workflow directly

## Response Measure

Interface layer code calls service methods only. No domain logic, validation rules, or data transformation beyond request/response shaping appear in interface layer files.

## Background

The interface layer (FastAPI routes and handlers) is responsible for request parsing, response formatting, and routing only. Business logic in this layer is untestable without an HTTP stack and cannot be reused. All domain decisions must flow through the service layer so they can be exercised independently of the transport protocol.
