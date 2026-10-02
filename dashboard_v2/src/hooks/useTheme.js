import { useLayoutEffect, useState } from "react";

const STORAGE_KEY = "finqa-theme";

// localStorage throws (SecurityError) when site data is blocked -- the theme just won't persist.
function savedTheme() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function initialTheme() {
  if (typeof window === "undefined") return "light";
  const saved = savedTheme();
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// No stored preference -> the toggle only reflects/overrides the system theme, it
// doesn't fix one in, so `system` (no localStorage write) always wins on reload
// until the user explicitly picks a side.
export function useTheme() {
  const [theme, setTheme] = useState(initialTheme);

  // Layout effect, not useEffect: data-theme must be set before first paint, otherwise a
  // saved "light" on a dark-OS machine flashes dark (the CSS prefers-color-scheme fallback).
  useLayoutEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // storage blocked -- the choice applies for this session only
    }
    setTheme(next);
  }

  return { theme, toggleTheme };
}
