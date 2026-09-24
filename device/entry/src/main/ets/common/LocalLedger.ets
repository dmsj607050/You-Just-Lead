/**
 * 端侧账本：一行一个 JSON 事件（JSONL）。
 *
 * Python 侧是一张 SQLite 表；端侧自足之后不该再依赖数据库文件，所以用追加写的 JSONL——
 * 优点是人能直接打开看、能进版本库、坏一行也不至于整表读不出来。
 * 事件字段与 Python 侧 `workflow_events` 对齐：`event_type` / `created_at` / `payload`。
 */

import { LocalWorkspace } from './LocalWorkspace';

const LEDGER_FILE: string = 'ledger.jsonl';

/** 账本里的一行。payload 存 JSON 文本，与 Python 侧的 `payload_json` 一样。 */
interface LedgerRecord {
  event_type: string;
  created_at: string;
  payload: string;
}

function linesOf(text: string): string[] {
  const lines: string[] = [];
  for (const raw of text.split('\n')) {
    if (raw.trim().length > 0) {
      lines.push(raw.trim());
    }
  }
  return lines;
}

/** 与 Python 侧 `tools/provenance.py::utc_now()` 同一格式：秒级 UTC，偏移写 `+00:00`。 */
export function utcNow(): string {
  return `${new Date().toISOString().substring(0, 19)}+00:00`;
}

/** 去掉分隔符的 UTC 时间戳，用于文件名（对齐 Python 侧 `utc_now().replace(...)`）。 */
export function utcStamp(): string {
  return utcNow().replace(/-/g, '').replace(/:/g, '').replace('+00:00', 'Z');
}

/** 事件条数；账本不存在时返回 0。 */
export function eventCount(workspace: LocalWorkspace): number {
  if (!workspace.exists(LEDGER_FILE)) {
    return 0;
  }
  return linesOf(workspace.readText(LEDGER_FILE)).length;
}

/**
 * 追加一条事件。
 *
 * `event_type` 用与 Python 侧同一套命名（小写蛇形，如 `local_workspace_initialized`），
 * 否则两端的事件流对不上；`payloadText` 由调用方用有类型的对象 `JSON.stringify` 出来。
 */
export function appendEvent(workspace: LocalWorkspace, eventType: string, payloadText: string): void {
  const record: LedgerRecord = {
    event_type: eventType,
    created_at: utcNow(),
    payload: payloadText
  };
  workspace.appendLine(LEDGER_FILE, JSON.stringify(record));
}
