import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

const site = (process.env.SITE_URL || "https://recompetes.com").replace(/\/$/, "");

function basePath() {
  const raw = (process.env.BASE_PATH ?? "/").trim();
  if (!raw || raw === "/") return "/";
  const withSlash = raw.startsWith("/") ? raw : `/${raw}`;
  return withSlash.replace(/\/$/, "");
}

export default defineConfig({
  site,
  base: basePath(),
  trailingSlash: "always",
  output: "static",
  build: { format: "directory" },
  integrations: [
    sitemap({
      filter: (page) => !page.includes("/404"),
    }),
  ],
  server: { host: "127.0.0.1", port: 4817 },
});
