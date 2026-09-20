/**
 * YAML 子集解析与序列化（端侧自足用）。
 *
 * 只覆盖工作区里实际出现的写法：嵌套映射、字符串/数字/布尔/null 标量、行内列表 `[a, b]`、
 * 以及 `- item` 形式的标量列表。**不支持**锚点、多行块、流式映射、"列表项是映射"这几种形态——
 * 遇到它们直接抛错而不是猜：规格被读歪，比读不出来危险得多。
 *
 * 输出按 PyYAML 的习惯来（2 空格缩进、序列与键同缩进、单引号转义），
 * 这样 Python 侧的 `yaml.safe_load` 能原样读回，两边可以互相核对同一份文件。
 *
 * 为什么用类而不是 `Record<string, X>`：ArkTS 禁止「递归的类型别名」，
 * 而 YAML 天然递归（映射里套列表里套映射）。类可以递归引用，所以这里用 YamlMap / YamlList。
 */

/** YAML 节点：标量、映射或列表。 */
export type YamlNode = string | number | boolean | null | YamlMap | YamlList;

/** YAML 映射：保持插入顺序（dump 时键序与解析前一致）。 */
export class YamlMap {
  private entries: Map<string, YamlNode> = new Map<string, YamlNode>();

  get(key: string): YamlNode | undefined {
    return this.entries.get(key);
  }

  set(key: string, value: YamlNode): void {
    this.entries.set(key, value);
  }

  has(key: string): boolean {
    return this.entries.has(key);
  }

  keys(): string[] {
    const out: string[] = [];
    for (const key of this.entries.keys()) {
      out.push(key);
    }
    return out;
  }

  size(): number {
    return this.entries.size;
  }
}

/** YAML 列表。 */
export class YamlList {
  items: YamlNode[] = [];
}

function isMap(node: YamlNode | undefined): boolean {
  return node instanceof YamlMap;
}

function isList(node: YamlNode | undefined): boolean {
  return node instanceof YamlList;
}

function asMap(node: YamlNode | undefined): YamlMap {
  return node instanceof YamlMap ? node : new YamlMap();
}

function asList(node: YamlNode | undefined): YamlList {
  return node instanceof YamlList ? node : new YamlList();
}

function isEmptyMap(node: YamlNode | undefined): boolean {
  return node instanceof YamlMap && node.size() === 0;
}

/** 去掉一层引号，并处理单引号里的 '' 转义。 */
function unquote(text: string): string {
  const value: string = text.trim();
  if (value.length >= 2) {
    const head: string = value.charAt(0);
    const tail: string = value.charAt(value.length - 1);
    if (head === "'" && tail === "'") {
      return value.substring(1, value.length - 1).split("''").join("'");
    }
    if (head === '"' && tail === '"') {
      return value.substring(1, value.length - 1).replace(/\\"/g, '"').replace(/\\n/g, '\n');
    }
  }
  return value;
}

/** 找 `key:` 里的那个冒号：跳过引号内的内容。返回 -1 表示这行不是映射项。 */
function keySeparator(text: string): number {
  let quote: string = '';
  for (let i = 0; i < text.length; i++) {
    const ch: string = text.charAt(i);
    if (quote.length > 0) {
      if (ch === quote) {
        quote = '';
      }
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if (ch === ':') {
      const next: string = i + 1 < text.length ? text.charAt(i + 1) : ' ';
      if (next === ' ' || i === text.length - 1) {
        return i;
      }
    }
  }
  return -1;
}

/** 把一段行内量解析成标量或列表。 */
function parseScalar(raw: string): YamlNode {
  const text: string = raw.trim();
  if (text.length === 0) {
    return null;
  }
  if (text === '[]') {
    return new YamlList();
  }
  if (text === '{}') {
    return new YamlMap();
  }
  if (text.startsWith('[') && text.endsWith(']')) {
    const inner: string = text.substring(1, text.length - 1).trim();
    const list: YamlList = new YamlList();
    if (inner.length === 0) {
      return list;
    }
    for (const part of inner.split(',')) {
      list.items.push(parseScalar(part));
    }
    return list;
  }
  const head: string = text.charAt(0);
  if (head === "'" || head === '"') {
    return unquote(text);
  }
  const lowered: string = text.toLowerCase();
  if (lowered === 'null' || lowered === '~') {
    return null;
  }
  if (lowered === 'true') {
    return true;
  }
  if (lowered === 'false') {
    return false;
  }
  if (/^-?\d+$/.test(text)) {
    return Number.parseInt(text, 10);
  }
  if (/^-?\d+\.\d+$/.test(text)) {
    return Number.parseFloat(text);
  }
  return text;
}

/** 解析用的一行：缩进宽度 + 去掉首尾空白后的内容。 */
interface YamlLine {
  indent: number;
  text: string;
}

/** 解析游标：ArkTS 没有出参，用一个可变对象带着走。 */
class Cursor {
  index: number = 0;
}

function splitLines(text: string): YamlLine[] {
  const lines: YamlLine[] = [];
  for (const raw of text.split('\n')) {
    const withoutCr: string = raw.endsWith('\r') ? raw.substring(0, raw.length - 1) : raw;
    const trimmed: string = withoutCr.trim();
    if (trimmed.length === 0 || trimmed.startsWith('#')) {
      continue;
    }
    let indent: number = 0;
    while (indent < withoutCr.length && withoutCr.charAt(indent) === ' ') {
      indent++;
    }
    lines.push({ indent: indent, text: trimmed });
  }
  return lines;
}

function parseSequence(lines: YamlLine[], cursor: Cursor, indent: number): YamlList {
  const list: YamlList = new YamlList();
  while (cursor.index < lines.length) {
    const line: YamlLine = lines[cursor.index];
    if (line.indent !== indent || !line.text.startsWith('- ')) {
      break;
    }
    const rest: string = line.text.substring(2).trim();
    cursor.index++;
    if (rest.length === 0) {
      if (cursor.index < lines.length && lines[cursor.index].indent > indent) {
        list.items.push(parseNode(lines, cursor, lines[cursor.index].indent));
      } else {
        list.items.push(null);
      }
      continue;
    }
    const head: string = rest.charAt(0);
    if (head !== "'" && head !== '"' && keySeparator(rest) >= 0) {
      throw new Error(`YamlLite: 暂不支持「列表项是映射」的写法：- ${rest}`);
    }
    list.items.push(parseScalar(rest));
  }
  return list;
}

function parseMapping(lines: YamlLine[], cursor: Cursor, indent: number): YamlMap {
  const map: YamlMap = new YamlMap();
  while (cursor.index < lines.length) {
    const line: YamlLine = lines[cursor.index];
    if (line.indent < indent) {
      break;
    }
    if (line.indent > indent) {
      throw new Error(`YamlLite: 缩进异常：${line.text}`);
    }
    const separator: number = keySeparator(line.text);
    if (separator < 0) {
      throw new Error(`YamlLite: 这一行不是「键: 值」：${line.text}`);
    }
    const key: string = unquote(line.text.substring(0, separator));
    const rest: string = line.text.substring(separator + 1).trim();
    cursor.index++;
    if (rest.length > 0) {
      map.set(key, parseScalar(rest));
      continue;
    }
    if (cursor.index < lines.length && lines[cursor.index].indent > indent) {
      map.set(key, parseNode(lines, cursor, lines[cursor.index].indent));
    } else if (cursor.index < lines.length
      && lines[cursor.index].indent === indent
      && lines[cursor.index].text.startsWith('- ')) {
      // PyYAML 写的序列与键同缩进，这里要一并吃下。
      map.set(key, parseSequence(lines, cursor, indent));
    } else {
      map.set(key, null);
    }
  }
  return map;
}

function parseNode(lines: YamlLine[], cursor: Cursor, indent: number): YamlNode {
  if (cursor.index < lines.length && lines[cursor.index].text.startsWith('- ')) {
    return parseSequence(lines, cursor, indent);
  }
  return parseMapping(lines, cursor, indent);
}

/** 解析一份 YAML 文本；顶层必须是映射。 */
export function parseYaml(text: string): YamlMap {
  const lines: YamlLine[] = splitLines(text);
  if (lines.length === 0) {
    return new YamlMap();
  }
  const cursor: Cursor = new Cursor();
  const node: YamlNode = parseNode(lines, cursor, lines[0].indent);
  if (!(node instanceof YamlMap)) {
    throw new Error('YamlLite: 顶层必须是映射');
  }
  return node;
}

/** 判断一个字符串能不能不加引号地写出去。 */
function needsQuote(text: string): boolean {
  if (text.length === 0) {
    return true;
  }
  const lowered: string = text.toLowerCase();
  if (lowered === 'true' || lowered === 'false' || lowered === 'null' || lowered === '~') {
    return true;
  }
  if (/^-?\d+(\.\d+)?$/.test(text)) {
    return true;
  }
  if (text !== text.trim()) {
    return true;
  }
  for (let i = 0; i < text.length; i++) {
    const ch: string = text.charAt(i);
    if (ch === '\n' || ch === '#' || ch === ':' || ch === "'" || ch === '"') {
      return true;
    }
    if (ch === '-' || ch === '[' || ch === ']' || ch === '{' || ch === '}') {
      return true;
    }
    if (ch.charCodeAt(0) > 127) {
      // 中文等非 ASCII 可以裸写（Python 侧也是 allow_unicode=True）。
      continue;
    }
    if (/[A-Za-z0-9_./]/.test(ch)) {
      continue;
    }
    return true;
  }
  return false;
}

function dumpScalar(node: YamlNode): string {
  if (node === null) {
    return 'null';
  }
  if (typeof node === 'boolean') {
    return node ? 'true' : 'false';
  }
  if (typeof node === 'number') {
    return `${node}`;
  }
  if (node instanceof YamlMap || node instanceof YamlList) {
    throw new Error('YamlLite: 标量位置出现了集合');
  }
  const text: string = `${node}`;
  if (!needsQuote(text)) {
    return text;
  }
  // 单引号里只需要把 ' 翻倍，其余字符原样。
  return `'${text.split("'").join("''")}'`;
}

function dumpMapping(map: YamlMap, indent: number): string {
  const pad: string = ' '.repeat(indent);
  let out: string = '';
  for (const key of map.keys()) {
    const node: YamlNode | undefined = map.get(key);
    const label: string = dumpScalar(key);
    if (node instanceof YamlMap) {
      if (node.size() === 0) {
        out += `${pad}${label}: {}\n`;
      } else {
        out += `${pad}${label}:\n${dumpMapping(node, indent + 2)}`;
      }
      continue;
    }
    if (node instanceof YamlList) {
      if (node.items.length === 0) {
        out += `${pad}${label}: []\n`;
        continue;
      }
      out += `${pad}${label}:\n`;
      for (const item of node.items) {
        if (item instanceof YamlMap || item instanceof YamlList) {
          throw new Error('YamlLite: 暂不支持嵌套在列表里的映射');
        }
        out += `${pad}- ${dumpScalar(item)}\n`;
      }
      continue;
    }
    out += `${pad}${label}: ${dumpScalar(node === undefined ? null : node)}\n`;
  }
  return out;
}

/** 序列化成 YAML 文本（结尾带一个换行）。 */
export function dumpYaml(root: YamlMap): string {
  return dumpMapping(root, 0);
}

/** 按点号路径取值，和 Python 侧的 get_nested 语义一致。 */
export function yamlGet(root: YamlMap, dotted: string): YamlNode | undefined {
  let current: YamlNode | undefined = root;
  for (const key of dotted.split('.')) {
    if (!(current instanceof YamlMap)) {
      return undefined;
    }
    current = current.get(key);
    if (current === undefined) {
      return undefined;
    }
  }
  return current;
}

/** 按点号路径写值，中间缺的映射会自动建出来。 */
export function yamlSet(root: YamlMap, dotted: string, value: YamlNode): void {
  const keys: string[] = dotted.split('.');
  let current: YamlMap = root;
  for (let i = 0; i < keys.length - 1; i++) {
    const next: YamlNode | undefined = current.get(keys[i]);
    if (!(next instanceof YamlMap)) {
      const created: YamlMap = new YamlMap();
      current.set(keys[i], created);
      current = created;
      continue;
    }
    current = next;
  }
  current.set(keys[keys.length - 1], value);
}

/** 把一个节点折成一行可显示文本（对应 Python 侧的 display_value）。 */
export function displayValue(node: YamlNode | undefined): string {
  if (node === undefined || node === null) {
    return '';
  }
  if (typeof node === 'boolean') {
    return node ? 'true' : 'false';
  }
  if (node instanceof YamlList) {
    const parts: string[] = [];
    for (const item of node.items) {
      parts.push(displayValue(item));
    }
    return parts.join(', ');
  }
  if (node instanceof YamlMap) {
    return `{${node.size()} keys}`;
  }
  return `${node}`.trim();
}

/** 供需要判断"是不是空映射"的地方复用。 */
export function isEmptyMapNode(node: YamlNode | undefined): boolean {
  return isEmptyMap(node);
}

/** 把列表节点转成字符串数组（只取标量项）。 */
export function listOfStrings(node: YamlNode | undefined): string[] {
  const out: string[] = [];
  for (const item of asList(node).items) {
    out.push(displayValue(item));
  }
  return out;
}

/** 把映射节点转成「键 → 文本」的行（界面上按行展示时用）。 */
export function mapRows(node: YamlNode | undefined): string[] {
  const rows: string[] = [];
  for (const key of asMap(node).keys()) {
    rows.push(`${key}=${displayValue(asMap(node).get(key))}`);
  }
  return rows;
}

/** 判断节点是不是映射（供外部做类型判断，避免直接 instanceof 散落各处）。 */
export function isMapNode(node: YamlNode | undefined): boolean {
  return isMap(node);
}

/** 判断节点是不是列表。 */
export function isListNode(node: YamlNode | undefined): boolean {
  return isList(node);
}
