import { useEffect } from "react";

export function usePageTitle(title) {
  useEffect(() => {
    const previous = document.title;
    document.title = title ? `${title} — Fin·QA v2` : "Fin·QA v2";
    return () => {
      document.title = previous;
    };
  }, [title]);
}
