const pages = new Set(["etfs", "strategies", "data"]);

export function workspaceUrl(page: string) {
  const current = new URLSearchParams(location.search);
  const query = new URLSearchParams({ page });
  for (const key of ["code", "object", "start", "end", "scope", "search"]) {
    const value = current.get(key);
    if (value) query.set(key, value);
  }
  return `?${query}`;
}

export function safeReturnUrl(value: string | null) {
  if (!value || !/^\/?\?/.test(value)) return null;
  const url = new URL(value, location.origin);
  return url.origin === location.origin && url.pathname === "/" && pages.has(url.searchParams.get("page") ?? "")
    ? url.search : null;
}

export function dataManagementUrl(manage: string, task?: string, code?: string) {
  const current = new URLSearchParams(location.search);
  current.delete("return_to");
  if (!current.has("page")) current.set("page", "etfs");
  const query = new URLSearchParams({ page: "data", manage, return_to: `?${current}` });
  const instrument = code || current.get("code");
  if (instrument) query.set("code", instrument);
  if (task) query.set("task", task);
  return `?${query}`;
}
