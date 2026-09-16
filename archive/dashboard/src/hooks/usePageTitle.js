import { useEffect } from "react";

export function usePageTitle(title) {
  useEffect(() => {
    const previous = document.title;
    document.title = title ? `${title} | Fin_QA` : "Fin_QA Dashboard";
    return () => {
      document.title = previous;
    };
  }, [title]);
}