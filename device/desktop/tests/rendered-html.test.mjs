import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const developmentPreviewMeta =
  /<meta(?=[^>]*\bname=["']codex-preview["'])(?=[^>]*\bcontent=["']development["'])[^>]*>/i;

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the interactive competition workspace", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.doesNotMatch(html, developmentPreviewMeta);
  assert.match(html, /You Just Lead/i);
  assert.match(html, /COMPETITION TRAINING AGENT/);
  assert.match(html, /创建你的竞赛项目/);
  assert.match(html, /创建项目并提交规则/);
});

test("ships the complete competition workflow surface with a social preview", async () => {
  const [css, page, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /RULES INTAKE/);
  assert.match(page, /RESEARCH RADAR/);
  assert.match(page, /MATERIAL ANALYSIS/);
  assert.match(page, /TRAINING FOUNDATION/);
  assert.match(page, /TRAINING DEPLOYMENT/);
  assert.match(page, /确认训练位置/);
  assert.match(page, /PROJECT MAP/);
  assert.match(page, /项目脉络/);
  assert.match(page, /stageResult/);
  assert.match(page, /前端交互预览/);
  assert.doesNotMatch(page, /SkeletonPreview|codex-preview/);
  assert.match(css, /--amber/);
  assert.match(css, /graph-flow/);
  assert.match(css, /project-flow/);
  assert.match(css, /@media/);
  assert.match(layout, /Competition Training Agent/);
  assert.match(layout, /og-workspace\.png/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await access(new URL("../public/og-workspace.png", import.meta.url));
});
