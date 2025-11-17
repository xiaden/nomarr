import js from "@eslint/js";
import importPlugin from "eslint-plugin-import";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  // Ignore build output
  globalIgnores(["dist"]),

  {
    files: ["**/*.{ts,tsx}"],

    // Only flat-config-safe base configs
    extends: [js.configs.recommended, ...tseslint.configs.recommended],

    languageOptions: {
      ecmaVersion: 2020,
      sourceType: "module",
      globals: globals.browser,
    },

    // Register plugins explicitly for flat config
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
      import: importPlugin,
    },

    settings: {
      "import/resolver": {
        typescript: {
          alwaysTryTypes: true,
          project: "./tsconfig.json",
        },
        node: true,
      },
      react: {
        version: "detect",
      },
    },

    rules: {
      // -------------------------
      // TypeScript hygiene
      // -------------------------
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "warn",

      // -------------------------
      // React hooks rules (what reactHooks.configs.recommended would give you)
      // -------------------------
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",

      // -------------------------
      // React Refresh integration
      // -------------------------
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],

      // -------------------------
      // Import hygiene + ordering
      // -------------------------
      "import/order": [
        "warn",
        {
          "newlines-between": "always",
          alphabetize: { order: "asc", caseInsensitive: true },
          groups: [
            "builtin",
            "external",
            "internal",
            "parent",
            "sibling",
            "index",
          ],
        },
      ],
      "import/no-cycle": "warn",

      // -------------------------
      // ARCHITECTURE RULES
      // -------------------------

      // 1) No raw fetch outside shared/api.ts
      "no-restricted-globals": [
        "error",
        {
          name: "fetch",
          message: "Use shared/api.ts instead of calling fetch() directly.",
        },
      ],

      // 2) shared/ must not import from features/
      "import/no-restricted-paths": [
        "error",
        {
          zones: [
            {
              target: "./src/shared",
              from: "./src/features",
              message: "shared/ must not import from features/.",
            },
          ],
        },
      ],
    },
  },

  // Allow fetch in shared/api.ts specifically
  {
    files: ["src/shared/api.ts"],
    rules: {
      "no-restricted-globals": "off",
    },
  },
]);
