import { useEffect, useState } from "react";
import { api } from "./api";

export function useApiResource<T>(path: string | null) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ path: string | null; data?: T; loading: boolean; error: string }>({ path, loading: !!path, error: "" });
  useEffect(() => {
    const controller = new AbortController();
    if (!path) { setState({ path, loading: false, error: "" }); return; }
    setState((old) => ({ path, data: old.path === path ? old.data : undefined, loading: true, error: "" }));
    api<T>(path, "GET", undefined, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setState({ path, data, loading: false, error: "" }); })
      .catch((error: Error) => { if (!controller.signal.aborted) setState((old) => ({ ...old, path, loading: false, error: error.message })); });
    return () => controller.abort();
  }, [path, revision]);
  const current = state.path === path ? state : { loading: !!path, error: "", data: undefined };
  return { ...current, retry: () => setRevision((value) => value + 1) };
}
