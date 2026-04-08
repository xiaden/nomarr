# ASR-003: All UI elements must remain responsive with progress indication for non-instant operations

**Status:** Active  
**Date:** 2026-04-08  
**Quality Attribute:** Usability  
**Priority:** High  
**Source:** User requirement — April 2026  

## Stimulus

A user triggers any action or navigates to any view in the application

## Response Measure

All UI elements remain interactive. Any action that cannot complete near-instantly displays a progress indication for its duration.

## Background

Long-running operations (library scans, ML tagging, calibration) are common. The UI must never feel frozen. For operations that cannot complete near-instantly, the interface must communicate that work is in progress.
