# ASR-005: Spawned processes must be recoverable without corrupting application state

**Status:** Active  
**Date:** 2026-04-08  
**Quality Attribute:** Availability  
**Priority:** Critical  
**Source:** User requirement — April 2026  

## Stimulus

A spawned process terminates unexpectedly or is killed

## Response Measure

The application detects the termination (expected or unexpected), transitions affected work to a recoverable state, and resumes or retries without leaving corrupted application state.

## Background

The application spawns worker processes for scanning, ML tagging, and other long-running tasks. These processes can terminate unexpectedly (OOM, signal, exception). The application—not the process itself—is responsible for detecting termination and initiating recovery. A crashed worker must not leave tasks stuck in an in-progress state or leave partial writes in the database.
