# ASR-004: Application must start from a compose file with minimal environmental configuration

**Status:** Active  
**Date:** 2026-04-08  
**Quality Attribute:** Deployability  
**Priority:** High  
**Source:** User requirement — April 2026  

## Stimulus

A new user deploys the application for the first time with no prior configuration

## Response Measure

A new deployment reaches a working state by supplying only a compose file with the database and application images, plus minimal environment variables (credentials/paths that cannot have defaults). No additional services or manual initialization steps are required.

## Background

The target user is a self-hoster, not an ops team. Complex configuration requirements create support burden and reduce adoption. The application must apply sensible defaults and require minimal operator input to reach a working state.
