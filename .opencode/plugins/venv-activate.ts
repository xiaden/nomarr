import type { Plugin } from "@opencode-ai/plugin"
import path from "path"

export const VenvActivatePlugin: Plugin = async ({ directory }) => {
  const venvDir = path.join(directory, ".venv")
  const activateScript = path.join(venvDir, "bin", "activate")

  return {
    "tool.execute.before": async (_input, output) => {
      // Auto-activate venv before every bash command
      if (_input.tool !== "bash") return

      const command = output.args?.command
      if (typeof command !== "string" || command.trim() === "") return
      if (command.includes(activateScript)) return

      output.args.command = `. ${activateScript} && ${command}`
    },
  }
}
