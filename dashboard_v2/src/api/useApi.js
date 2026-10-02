import { useEffect, useState } from "react";

export function useApi(fetcher, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // fetcher receives the AbortSignal so slow calls (e.g. LLM-backed research) can opt in
    // to being cancelled when deps change or the component unmounts.
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null); // else the previous request's result keeps rendering under the new deps

    fetcher(controller.signal)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading };
}
