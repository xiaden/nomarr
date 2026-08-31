import type { Plugin } from "@opencode-ai/plugin"
import path from "path"

export const VenvActivatePlugin: Plugin = async ({ directory }) => {
  const venvDir = path.join(directory, ".venv")
  const venvBin = path.join(venvDir, "bin")
  const venvPython = path.join(venvBin, "python")

  // Keep setup/recreation commands usable before the venv exists. Once it is
  // present, shell.env makes it the default for all OpenCode shell sessions.

  return {
    // shell.env applies to AI commands and commands entered in OpenCode's
    // integrated terminal. Prefer the workspace venv when it exists, but do
    // not block shell access when an agent needs to create or repair it.
    "shell.env": async (_input, output) => {
      if (!(await Bun.file(venvPython).exists())) return

      const currentPath = output.env.PATH ?? process.env.PATH ?? ""
      const pathEntries = currentPath.split(path.delimiter).filter(Boolean)
      output.env.PATH = [venvBin, ...pathEntries.filter((entry) => entry !== venvBin)].join(
        path.delimiter,
      )
      output.env.VIRTUAL_ENV = venvDir
      output.env.PYTHONNOUSERSITE = "1"
      output.env.PIP_REQUIRE_VIRTUALENV = "1"
    },
  }
}
