import js from "@eslint/js";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";
import globals from "globals";

export default [
  js.configs.recommended,
  react.configs.flat.recommended,
  jsxA11y.flatConfigs.recommended,
  {
    plugins: { "react-hooks": reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
  {
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser, ...globals.es2022 },
    },
    settings: { react: { version: "18.3" } },
    rules: {
      "react/react-in-jsx-scope": "off", // Vite's JSX runtime doesn't need React in scope
      "react/prop-types": "off", // no prop-types in this codebase
    },
  },
  { ignores: ["dist/**", "node_modules/**"] },
];
