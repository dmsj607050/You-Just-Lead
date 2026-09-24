"use client";

import { useState } from "react";

type DeepSeekStatus = {
  configured: boolean;
  key_source: string | null;
  model: string;
  supported_models: string[];
  secure_storage_available: boolean;
};

const LOCAL_AGENT_URL = "http://127.0.0.1:8765";

async function localRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${LOCAL_AGENT_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(String(body.error ?? body.message ?? "本地 Agent 暂不可用。"));
  return body as T;
}

export function DesktopModelSettings() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<DeepSeekStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("deepseek-v4-pro");
  const [busy, setBusy] = useState<"loading" | "saving" | "testing" | null>(null);
  const [message, setMessage] = useState("");

  async function refresh() {
    setBusy("loading");
    setMessage("");
    try {
      const next = await localRequest<DeepSeekStatus>("/api/settings/deepseek");
      setStatus(next);
      setModel(next.model);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "无法连接本地 Agent。");
    } finally {
      setBusy(null);
    }
  }

  async function openSettings() {
    setOpen(true);
    await refresh();
  }

  async function save() {
    if (!apiKey.trim()) {
      setMessage("请输入 DeepSeek API Key；密钥只会发送到本机 Agent。");
      return;
    }
    setBusy("saving");
    setMessage("");
    try {
      const next = await localRequest<DeepSeekStatus>("/api/settings/deepseek", {
        method: "POST",
        body: JSON.stringify({ api_key: apiKey, model }),
      });
      setStatus(next);
      setApiKey("");
      setMessage("已保存到 Windows 凭据管理器，项目记录不会保留 API Key。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败。");
    } finally {
      setBusy(null);
    }
  }

  async function testConnection() {
    setBusy("testing");
    setMessage("");
    try {
      const result = await localRequest<{ ok: boolean; message: string; model?: string }>("/api/settings/deepseek/test", { method: "POST", body: "{}" });
      setMessage(result.model ? `${result.message} 当前模型：${result.model}` : result.message);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "连接测试失败。");
    } finally {
      setBusy(null);
    }
  }

  return <>
    <button className="model-link" onClick={openSettings} type="button"><span>◇</span><div><b>模型设置</b><small>{status?.configured ? `DeepSeek · ${status.model}` : "配置 DeepSeek 与本地 Agent"}</small></div></button>
    {open ? <div className="model-dialog-backdrop" onMouseDown={() => setOpen(false)} role="presentation"><section aria-label="DeepSeek 模型设置" aria-modal="true" className="model-dialog" onMouseDown={(event) => event.stopPropagation()} role="dialog"><div className="dialog-title"><div><span className="eyebrow">LOCAL AGENT MODEL</span><h2>接入 DeepSeek</h2><p>模型调用经由本机 Agent 发起；竞赛数据、规则文件和 API Key 不会直接提交给网页端。</p></div><button aria-label="关闭模型设置" onClick={() => setOpen(false)} type="button">×</button></div><div className="model-status"><span className={status?.configured ? "configured" : ""} />{busy === "loading" ? "正在读取本地配置…" : status?.configured ? `已配置 · ${status.key_source === "environment" ? "系统环境变量" : "Windows 凭据管理器"}` : "尚未配置"}</div><label>DeepSeek API Key<input autoComplete="off" onChange={(event) => setApiKey(event.target.value)} placeholder={status?.configured ? "如需更换密钥，请重新输入" : "sk-..."} type="password" value={apiKey} /></label><label>默认模型<select onChange={(event) => setModel(event.target.value)} value={model}>{(status?.supported_models ?? ["deepseek-v4-pro", "deepseek-v4-flash"]).map((item) => <option key={item} value={item}>{item}</option>)}</select></label><p className="model-security">密钥只会传给 `127.0.0.1` 上的本机 Agent，并保存到 Windows 凭据管理器；不会存入项目文件、实验记录或网页端。</p>{message ? <p className="model-message">{message}</p> : null}<div className="dialog-actions"><button className="button secondary-button" disabled={busy !== null} onClick={testConnection} type="button">{busy === "testing" ? "正在测试…" : "测试连接"}</button><button className="button primary-button" disabled={busy !== null} onClick={save} type="button">{busy === "saving" ? "正在保存…" : "安全保存"}</button></div></section></div> : null}
  </>;
}
