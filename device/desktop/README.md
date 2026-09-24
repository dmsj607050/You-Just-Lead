# You Just Lead · Competition Intelligence

一个面向机器学习竞赛研发流程的证据驱动型工作台。它将实验指标、决策记录、研究证据与后续行动整合为一个清晰的企业级界面。

## 仓库归属

本目录是 **You Just Lead 客户端仓库** `YouJustLead-Harmony` 的一部分（与 `entry/` 下的鸿蒙端应用同仓）。
它承担的是 Windows 桌面端：Tauri 外壳 + 本地 Competition Agent 后端 sidecar。

原先这个工作台托管在第三方平台（ChatGPT Sites / Cloudflare Workers）上，**该托管方式已废弃**，
仓库不再依赖它。本文档下面「工作区身份」「Optional Dispatch-Owned ChatGPT Sign-In」两节记录的是
那段托管方式的原始说明，属于历史遗留，桌面端与本地开发都不需要它们。

打包（Windows 安装包）：

```powershell
npm run desktop:package
```

脚本位于 `tools/`，会去后端仓库（默认同级目录 `..\..\You Just Lead\competition-agent`，
可用 `-BackendRoot` 参数或环境变量 `YJL_BACKEND_ROOT` 覆盖）构建 `competition-agent-api.exe`
sidecar，再走 Tauri release 与 NSIS。

## Prerequisites

- Node.js `>=22.13.0`

## 本地启动

```bash
npm install
npm run dev
npm run build
```

若要显示本机 Competition Agent 的真实工作区数据，先在项目根目录运行
`conda run -n AIC python main.py serve --port 8765`，然后复制 `.env.example`
为 `.env.local` 再启动前端。API 不可达时，界面会保持可用并明确标记为演示数据模式。

生产构建使用 Vinext / Cloudflare Workers 运行时，不依赖 `wrangler.jsonc`。

## 项目结构

- `app/`：仪表盘页面、元数据与全局视觉系统
- `public/og.png`：用于社交预览的品牌视觉
- `tests/`：服务端渲染与关键界面内容检查
- `.openai/hosting.json`：私密站点发布配置

## 工作区身份（可选）

OpenAI workspace sites can read the current user's email from
`oai-authenticated-user-email`.

SIWC-authenticated workspace sites may also receive
`oai-authenticated-user-full-name` when the user's SIWC profile has a non-empty
`name` claim. The full-name value is percent-encoded UTF-8 and is accompanied by
`oai-authenticated-user-full-name-encoding: percent-encoded-utf-8`.

Treat the full name as optional and fall back to email when it is absent:

```tsx
import { headers } from "next/headers";

export default async function Home() {
  const requestHeaders = await headers();
  const email = requestHeaders.get("oai-authenticated-user-email");
  const encodedFullName = requestHeaders.get("oai-authenticated-user-full-name");
  const fullName =
    encodedFullName &&
    requestHeaders.get("oai-authenticated-user-full-name-encoding") ===
      "percent-encoded-utf-8"
      ? decodeURIComponent(encodedFullName)
      : null;

  const displayName = fullName ?? email;
  // ...
}
```

## Optional Dispatch-Owned ChatGPT Sign-In

Import the ready-to-use helpers from `app/chatgpt-auth.ts` when the site needs
optional or required ChatGPT sign-in:

- Use `getChatGPTUser()` for optional signed-in UI.
- Use `requireChatGPTUser(returnTo)` for server-rendered pages that should send
  anonymous visitors through Sign in with ChatGPT.
- Use `chatGPTSignInPath(returnTo)` and `chatGPTSignOutPath(returnTo)` for
  browser links or actions.
- Pass a same-origin relative `returnTo` path for the destination after sign-in
  or sign-out. The helper validates and safely encodes it.
- Mark protected pages with `export const dynamic = "force-dynamic"` because
  they depend on per-request identity headers.

Dispatch owns `/signin-with-chatgpt`, `/signout-with-chatgpt`, `/callback`, the
OAuth cookies, and identity header injection. Do not implement app routes for
those reserved paths. Routes that do not import and call the helper remain
anonymous-compatible.

SIWC establishes identity only; it does not prove workspace membership. Use the
Sites hosting platform's access policy controls for workspace-wide restrictions,
or enforce explicit server-side membership or allowlist checks.

Use SIWC for account pages, user-specific dashboards, saved records, and write
actions tied to the current ChatGPT user. Leave public content anonymous.

## Useful Commands

- `npm run dev`: start local development
- `npm run build`: verify the vinext build output
- `npm test`: build the starter and verify its rendered loading skeleton
- `npm run db:generate`: generate Drizzle migrations after schema changes

## Learn More

- [vinext Documentation](https://github.com/cloudflare/vinext)
- [Drizzle D1 Guide](https://orm.drizzle.team/docs/get-started/d1-new)
