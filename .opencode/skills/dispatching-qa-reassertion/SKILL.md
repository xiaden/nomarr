---
name: dispatching-qa-reassertion
description: Template for reasserting QA review requirements when Exec-Manager reports DONE without QA results.
---

# Dispatching QA Reassertion

Use this skill when Exec-Manager reports `status: DONE` without including QA-Reviewer results.

## When to Use

- When Exec-Manager reports DONE but the report is missing `qaReview` section
- When Exec-Manager reports DONE but `testAnalyzerReport` or `docsAnalyzerReport` is missing
- When Exec-Manager attempts to skip QA review

## Reassertion Template

```
QA review is mandatory. Re-run with QA-Reviewer before reporting DONE.

Your report MUST include:
- QA-Reviewer verdict and all checks (lint, layers, contracts, quality, completeness)
- QA-TestAnalyzer status and report
- QA-DocsAnalyzer status and report
```

## Required Checks

Exec-Manager's report must include ALL of these before accepting DONE:

- [ ] `checks.lint: PASS`
- [ ] `checks.layerCompliance: PASS`
- [ ] `checks.contracts: PASS`
- [ ] `checks.codeQuality: PASS`
- [ ] `checks.completeness: PASS`
- [ ] `checks.testCoverage: PASS` — confirms QA-TestAnalyzer ran
- [ ] `checks.documentation: PASS` — confirms QA-DocsAnalyzer ran
- [ ] `testAnalyzerReport` present in output
- [ ] `docsAnalyzerReport` present in output

## After Reassertion

If ANY check is missing (not failed — **missing**), the review is incomplete. Re-dispatch Exec-Manager with the reassertion message.

Exec-Manager must then spawn QA-Reviewer and wait for a complete review before reporting DONE again.
