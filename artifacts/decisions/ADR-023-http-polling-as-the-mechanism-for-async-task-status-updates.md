# ADR-023: HTTP polling as the mechanism for async Task status updates

**Status:** Accepted  
**Date:** 2026-04-09  
**Tags:** frontend, async, tasks, api  

## Context

ASR-003 requires that progress is surfaced for non-instant operations. The frontend needs a mechanism to learn when a backend Task has progressed or completed. Three approaches were considered: WebSockets (bidirectional, low latency, but requires persistent connection management and infrastructure support), Server-Sent Events (simpler than WebSockets but still requires persistent server-side streaming), and polling (client-initiated periodic GET requests — stateless, works transparently through proxies and load balancers, no server infrastructure changes). Nomarr's Task operations are coarse-grained and do not require sub-second update latency.

## Decision

The frontend uses HTTP polling to obtain status updates for async Task operations. Components send periodic GET requests to a task status endpoint and update UI state (progress bar, completion, failure) based on the response. WebSockets and SSE are not used for this purpose.

## Consequences

Polling introduces a latency floor equal to the poll interval; the interval must balance responsiveness against server load. Each component that displays Task progress is responsible for starting and stopping its own poll loop. Polling must stop on task completion, failure, or component unmount to prevent resource leaks. If sub-second update latency becomes a requirement in future, this ADR should be superseded by one adopting SSE or WebSockets.

## References

ASR-003
