// TEST-ONLY: compile the real app with esbuild, swapping native modules for the browser stand-ins.
// node tools/webtest/build.mjs <outdir>
import { mkdirSync, writeFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";

const { build } = await import(process.env.ESBUILD_PATH || "esbuild");
const here = path.dirname(fileURLToPath(import.meta.url));
const out = process.argv[2] || path.join(here, "out");
mkdirSync(out, { recursive: true });
const other = path.join(here, "other-shims.js");
await build({
  entryPoints: [path.join(here, "harness.js")], bundle: true, outfile: path.join(out, "bundle.js"), format: "iife", jsx: "automatic",
  loader: { ".js": "jsx" }, nodePaths: [process.env.NODE_MODULES || "/opt/npm-tools/node_modules"],
  alias: { "react-native": path.join(here, "rn-shim.js"), "expo-secure-store": other, "expo-status-bar": other, "react-native-safe-area-context": other,
    "@expo/vector-icons": other, "expo-haptics": other },
  define: { "process.env.NODE_ENV": '"development"' }, logLevel: "warning",
});
writeFileSync(path.join(out, "index.html"), `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{margin:0;height:100%}#root{height:100%;display:flex;flex-direction:column}*{box-sizing:border-box}</style></head>
<body><div id="root"></div><script src="bundle.js"></script></body></html>`);
console.log("built", out);
