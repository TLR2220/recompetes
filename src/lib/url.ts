export function href(path = ""): string {
  const base = import.meta.env.BASE_URL || "/";
  if (!path || path === "/") return base;
  return base + path.replace(/^\//, "");
}

export function absolute(path = ""): string {
  const site = import.meta.env.SITE || "https://recompetes.com";
  return new URL(href(path), site.endsWith("/") ? site : `${site}/`).href;
}
