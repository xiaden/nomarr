# Goal
perform code maintenance passes over the backend services, moving to have a better composition, DRY patterns, typing closer to the examples in V2, and clear, Meaningful logging/error tracing @nomarr/components/  . Additionally, remove all AI generated slop introduced in backend code files.

This includes:

- Extra comments that a human wouldn't add or is inconsistent with the rest of the file
- Extra defensive checks or try/catch blocks that are abnormal for that area of the codebase (especially if called by trusted / validated codepaths)
- Casts to any to get around type issues
- Any other style that is inconsistent with the file

# Budget
max_rounds: 10
