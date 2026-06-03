#!/usr/bin/env node

import { createWriteStream, mkdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

const [manifestPath, outputDir = ".demo-cache"] = process.argv.slice(2);

if (!manifestPath) {
  console.error("Usage: node scripts/download-hltv-demos.mjs <manifest.json> [output-dir]");
  process.exit(1);
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const demos = Array.isArray(manifest) ? manifest : manifest.demos;

if (!Array.isArray(demos) || demos.length === 0) {
  console.error("Manifest must be an array or an object with a non-empty demos array.");
  process.exit(1);
}

mkdirSync(outputDir, { recursive: true });

for (const demo of demos) {
  const demoUrl = resolveDemoUrl(demo);
  const id = demo.id ?? demo.demoId ?? basename(new URL(demoUrl).pathname);
  const response = await fetch(demoUrl, {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    },
  });

  if (!response.ok || !response.body) {
    throw new Error(`Failed to download ${demoUrl}: ${response.status} ${response.statusText}`);
  }

  const filename = safeFilename(demo.archiveName ?? contentDispositionFilename(response) ?? `hltv-demo-${id}.rar`);
  const outputPath = join(outputDir, filename);
  await pipeline(Readable.fromWeb(response.body), createWriteStream(outputPath));
  console.log(`${demoUrl} -> ${outputPath}`);
}

function resolveDemoUrl(demo) {
  if (typeof demo === "string") return demo;
  if (demo.demoUrl) return demo.demoUrl;
  if (demo.demoId) return `https://www.hltv.org/download/demo/${demo.demoId}`;
  throw new Error("Each demo entry needs demoUrl or demoId.");
}

function contentDispositionFilename(response) {
  const header = response.headers.get("content-disposition");
  if (!header) return undefined;
  const match = /filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i.exec(header);
  return match ? decodeURIComponent(match[1]) : undefined;
}

function safeFilename(filename) {
  return filename.replace(/[^\w.\-()[\] ]+/g, "_");
}
