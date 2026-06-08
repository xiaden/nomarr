import type { Plugin } from "@opencode-ai/plugin"
import fs from "fs"
import path from "path"

interface InstructionRule {
  pattern: string
  content: string
}

export const ApplyToPlugin: Plugin = async ({ directory }) => {
  console.log("[ApplyToPlugin] Loading plugin from directory:", directory)
  const injectedPatterns = new Set<string>()
  const rules: InstructionRule[] = []

  // Load rules from .github/instructions/*.instructions.md
  const instructionsDir = path.join(directory, ".github", "instructions")
  console.log("[ApplyToPlugin] Instructions directory:", instructionsDir)
  console.log("[ApplyToPlugin] Directory exists:", fs.existsSync(instructionsDir))
  if (fs.existsSync(instructionsDir)) {
    const files = fs.readdirSync(instructionsDir).filter(f => f.endsWith(".instructions.md"))
    for (const file of files) {
      const content = fs.readFileSync(path.join(instructionsDir, file), "utf-8")
      const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/)
      if (frontmatterMatch) {
        const frontmatter = frontmatterMatch[1]
        const applyToMatch = frontmatter.match(/applyTo:\s*(.+)/)
        if (applyToMatch) {
          const pattern = applyToMatch[1].trim()
          const body = content.slice(frontmatterMatch[0].length).trim()
          rules.push({ pattern, content: body })
        }
      }
    }
  }
  console.log("[ApplyToPlugin] Loaded", rules.length, "rules")

  function matchesPattern(filePath: string, pattern: string): boolean {
    // Convert absolute path to relative path from project root
    let relativePath = filePath
    if (path.isAbsolute(filePath)) {
      relativePath = path.relative(directory, filePath)
    }
    
    // Convert glob pattern to regex
    const regexPattern = pattern
      .replace(/[.+^${}()|[\]\\]/g, "\\$&") // Escape special regex chars except * and ?
      .replace(/\*\*/g, "{{GLOBSTAR}}")
      .replace(/\*/g, "[^/]*")
      .replace(/\?/g, "[^/]")
      .replace(/{{GLOBSTAR}}/g, ".*")
    const regex = new RegExp(`^${regexPattern}$`)
    return regex.test(relativePath)
  }

  function getMatchingRules(filePath: string): InstructionRule[] {
    return rules.filter(rule => matchesPattern(filePath, rule.pattern))
  }

  function formatInstructions(rules: InstructionRule[]): string {
    const content = rules.map(r => `# Layer Instructions (${r.pattern})\n\n${r.content}`).join("\n\n---\n\n")
    const banner = `## ⚠️ AUTO-INJECTED LAYER INSTRUCTIONS\n\nThese instructions were automatically appended by the apply-to plugin and are **not** part of the tool's return value. They describe rules and conventions for working in this layer. Review them carefully before proceeding.\n\n---`
    return `<|injected-rules|>\n${banner}\n\n${content}\n<|/injected-rules|>`
  }

  function checkAndInject(filePath: string | undefined): string | null {
    if (!filePath) return null

    const matchingRules = getMatchingRules(filePath)
    const uninjectRules = matchingRules.filter(r => !injectedPatterns.has(r.pattern))

    if (uninjectRules.length > 0) {
      uninjectRules.forEach(r => injectedPatterns.add(r.pattern))
      return formatInstructions(uninjectRules)
    }

    return null
  }

  /** Strip all text between (and including) startMarker..endMarker from input. */
  function stripBetween(input: string, startMarker: string, endMarker: string): string {
    let result = input
    let startIdx = result.indexOf(startMarker)
    while (startIdx !== -1) {
      const endIdx = result.indexOf(endMarker, startIdx)
      if (endIdx !== -1) {
        result = result.slice(0, startIdx) + result.slice(endIdx + endMarker.length)
      } else {
        result = result.slice(0, startIdx)
      }
      startIdx = result.indexOf(startMarker)
    }
    return result
  }

  return {
    "tool.execute.after": async (input, output) => {
      const toolName = input.tool

      // Args live on input.args in after (read-only snapshot).
      // output.args is the before-modification target and may not exist here.
      const toolArgs = (input as Record<string, unknown>).args as Record<string, unknown> | undefined

      let filePath: string | undefined

      if (toolName === "read") {
        filePath = toolArgs?.filePath as string | undefined
      } else if (["edit", "write"].includes(toolName)) {
        filePath = toolArgs?.filePath as string | undefined
      } else if (toolName === "apply_patch") {
        const patchText = toolArgs?.patchText as string | undefined
        if (patchText) {
          const pathMatches = patchText.match(/\*\*\* (?:Add|Update|Move to|Delete File): (.+)/g)
          if (pathMatches && pathMatches.length > 0) {
            filePath = pathMatches[0].replace(/\*\*\* (?:Add|Update|Move to|Delete File): /, "")
          }
        }
      } else {
        return // not a tool that touches files
      }

      const instructions = checkAndInject(filePath)
      if (instructions) {
        output.output = (output.output || "") + "\n\n---\n\n" + instructions
      }
    },

    "session.compacted": async () => {
      injectedPatterns.clear()
    },

    "experimental.session.compacting": async (input, output) => {
      if (!Array.isArray(output.context)) return

      const START = "<|injected-rules|>"
      const END = "<|/injected-rules|>"

      // Programmatically strip injected-rules blocks from context entries.
      // This is more reliable than asking the summarizer to do it — an
      // experimental event that may not fire in all environments would
      // leave injected content to survive compaction, causing duplication
      // when session.compacted clears injectedPatterns and triggers
      // re-injection on the next tool call.
      output.context = output.context.map((entry: unknown) => {
        const raw = typeof entry === "string" ? entry
          : entry && typeof (entry as Record<string, unknown>).content === "string"
            ? (entry as Record<string, unknown>).content as string
            : null
        if (raw === null) return entry
        if (!raw.includes(START)) return entry

        const stripped = stripBetween(raw, START, END)
        return typeof entry === "string" ? stripped
          : { ...(entry as Record<string, unknown>), content: stripped }
      })
    },
  }
}
