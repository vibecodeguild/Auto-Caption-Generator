import fs from "node:fs";
import vm from "node:vm";

const [implementationPath, fixturePath] = process.argv.slice(2);
if (!implementationPath || !fixturePath) {
  throw new Error("Usage: probe-creator-capability.mjs <implementation.mjs> <fixture.json>");
}
let source = fs.readFileSync(implementationPath, "utf8");
if (/\bimport\s*(?:\(|[{"'*])|\brequire\s*\(/.test(source)) {
  throw new Error("Capability implementations may not import ambient modules.");
}
source = source
  .replace(/\bexport\s+async\s+function\s+build\b/, "async function build")
  .replace(/\bexport\s+function\s+build\b/, "function build")
  .replace(/\bexport\s+const\s+build\b/, "const build")
  .replace(/\bexport\s+let\s+build\b/, "let build")
  .replace(/\bexport\s+var\s+build\b/, "var build");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const safeMath = {};
for (const key of Object.getOwnPropertyNames(Math)) {
  if (key !== "random") Object.defineProperty(safeMath, key, Object.getOwnPropertyDescriptor(Math, key));
}
Object.defineProperty(safeMath, "random", {
  value() { throw new Error("Math.random is unavailable."); },
  enumerable: false,
});
const context = vm.createContext(
  {
    console: Object.freeze({ log() {}, warn() {}, error() {} }),
    Math: Object.freeze(safeMath),
    Date: Object.freeze({ now() { throw new Error("Date.now is unavailable."); } }),
    JSON,
    Object,
    Array,
    Number,
    String,
    Boolean,
  },
  { codeGeneration: { strings: false, wasm: false } },
);
const script = new vm.Script(
  `"use strict";${source}\nif(typeof build!=="function")throw new Error("build(context) missing");build(${JSON.stringify(fixture)});`,
  { filename: implementationPath },
);
const result = await script.runInContext(context, { timeout: 1000 });
process.stdout.write(JSON.stringify(result));
