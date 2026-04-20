# Pipeline Automation

Nomarr can automate the path from a fresh library scan to calibrated tags and optional file writeback. This page explains what the pipeline does, what the **auto-write** setting controls, and how to interpret the pipeline states shown in the UI.

## What pipeline automation does

After you add or rescan a library, Nomarr can move through these stages automatically:

1. Discover files during scanning
2. Run ML tagging on files that still need tags
3. Wait for or generate calibration data when the library has enough processed files
4. Apply the calibration to the library's tagged files
5. Optionally write the curated tags into the audio files themselves

The first four stages work on Nomarr's database state. The last stage writes tags back into the music files on disk.

## Auto-write setting

`library_auto_write` is the per-library setting that decides what happens **after calibration apply finishes**.

- **Enabled:** when the library reaches `write_ready`, Nomarr starts file writeback automatically
- **Disabled:** Nomarr stops at `write_ready` and waits for you to start file writeback manually

This setting lets you choose between a fully automatic flow and a review-first flow.

### When to enable it

Enable auto-write when:

- You trust the current calibration and tagging behavior for that library
- You want newly processed files written automatically without another click
- You prefer a hands-off workflow after the initial setup

Leave it disabled when:

- You want to review database tags before they are written into files
- You are still validating how a new library behaves
- You use Nomarr mainly for curation and reporting, not immediate file writeback

### How to enable or disable it

1. Open the library in the web UI
2. Edit the library settings
3. Toggle **Auto-write** on or off
4. Save the change

If you enable auto-write while the library is already `write_ready`, Nomarr starts writing immediately.

## Pipeline states

Each library has exactly one current pipeline state.

| State | What it means |
| --- | --- |
| `idle` | The pipeline is not currently active for the library. This is the resting state before work starts or after an empty scan. |
| `scanning` | Nomarr is scanning the library for files and updates. |
| `ml_running` | Discovery workers are still processing files that need ML tags. |
| `too_small` | The library finished ML tagging, but it does not yet have enough tagged files to continue into calibration. Add more files and rescan to resume. |
| `awaiting_calibration` | All current files are tagged and the library is waiting for calibration to start. |
| `calibrating` | Nomarr is generating calibration data. |
| `applying` | Nomarr is applying the current calibration to the library's tagged files. |
| `write_ready` | Database-side processing is complete. The library is ready for file writeback, but writing has not started yet. |
| `writing` | Nomarr is writing curated tags into the music files on disk. |
| `done` | The pipeline finished all currently required stages for the library. |

## The two-phase tag model

Nomarr treats tag work as two separate phases:

### Phase 1: Database curation

Nomarr analyzes your music, stores model outputs, and curates the resulting tags inside the database. Calibration also belongs to this phase.

This phase is where Nomarr decides **what the tags should be**.

### Phase 2: File writeback

Only after database curation is complete does Nomarr write those curated tags back into your audio files.

This phase is where Nomarr decides **whether to copy the curated tags into the files on disk**.

Keeping these phases separate gives you control:

- You can inspect and work with curated tags in Nomarr before writing anything to disk
- You can disable auto-write for libraries where you want manual approval
- You can still benefit from database-side tagging even if you do not want automatic file changes

## What to expect in practice

For a typical library with auto-write disabled:

```text
idle → scanning → ml_running → awaiting_calibration → calibrating/applying → write_ready
```

For a typical library with auto-write enabled:

```text
idle → scanning → ml_running → awaiting_calibration → calibrating/applying → writing → done
```

For a small library that has not reached the calibration minimum yet:

```text
idle → scanning → ml_running → too_small
```

Once you add more music and rescan, the pipeline can continue from there.

## Related pages

- [Getting Started](getting_started.md)
- [Deployment](deployment.md)
- [Troubleshooting](troubleshooting.md)
