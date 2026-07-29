import tailwind from "bun-plugin-tailwind";
import { rm } from "node:fs/promises";
import path from "node:path";

// unset, bun leaves the raw process.env reference in the bundle and the browser
// throws "process is not defined". fail here rather than shipping that.
if (!process.env.BUN_PUBLIC_API_URL) {
  throw new Error(
    "BUN_PUBLIC_API_URL is not set. copy .env.example to .env and fill it in.",
  );
}

const outdir = path.join(process.cwd(), "dist");
await rm(outdir, { recursive: true, force: true });

const entrypoints = [...new Bun.Glob("src/**/*.html").scanSync()];

const result = await Bun.build({
  entrypoints,
  outdir,
  plugins: [tailwind],
  minify: true,
  target: "browser",
  sourcemap: "linked",
  // must match bunfig.toml's [serve.static] env, without this the dev server
  // inlines BUN_PUBLIC_* but production builds silently ship undefined
  env: "BUN_PUBLIC_*",
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
});

for (const output of result.outputs) {
  console.log(` ${path.relative(process.cwd(), output.path)}  ${(output.size / 1024).toFixed(1)} KB`);
}
