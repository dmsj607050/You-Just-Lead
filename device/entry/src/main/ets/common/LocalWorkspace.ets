/**
 * 端侧本地工作区：在用户的「文档」目录里建工作区，读写文件、建骨架、算文件指纹。
 *
 * 数据放在**用户可见的目录**（`文档/YouJustLead`）而不是应用私有沙箱——这样
 * 「证据就在你自己硬盘上、能直接打开核对」这件事才成立。
 *
 * 平台边界（实测，别再踩）：
 * - `DocumentViewPicker` 选文件夹返回的 URI，fs 只能 `openSync` 打开它本身；
 *   往里建文件、建目录、列子项全部报 13900002 No such file or directory
 *   （同样代码写应用沙箱是成功的）。所以工作区改用「文档目录权限 + 真实路径」。
 * - 因此这里用的是**真实路径**，不是 URI；`join()` 直接拼 `/`。
 *
 * 写法约定：ArkTS 静态检查对「会抛异常的系统 API」要求就地处理，所以每个文件操作
 * 都包在 try/catch 里。这里的处理方式是**原样上抛**（保留 BusinessError 的 code，
 * 界面要拿 code 才能说清是权限、编码还是磁盘的问题），而不是就地吞掉。
 */

import { abilityAccessCtrl, common, PermissionRequestResult, Permissions } from '@kit.AbilityKit';
import { preferences } from '@kit.ArkData';
import { util } from '@kit.ArkTS';
import { Environment, fileIo as fs, hash } from '@kit.CoreFileKit';

/** 工作区目录名：建在用户的「文档」下面，文件管理器里能直接看到。 */
export const WORKSPACE_FOLDER: string = 'YouJustLead';

/** 「文档目录读写」权限被拒时抛出的标记，界面据此给出可读提示。 */
export const WORKSPACE_PERMISSION_DENIED: string = 'WORKSPACE_PERMISSION_DENIED';

/** 设备不具备所需系统能力时抛出的标记（旧的或裁剪过的系统上会出现）。 */
export const WORKSPACE_UNSUPPORTED: string = 'WORKSPACE_UNSUPPORTED';

const DOCUMENTS_PERMISSION: Permissions = 'ohos.permission.READ_WRITE_DOCUMENTS_DIRECTORY';

/** 工作区目录骨架，与 Python 侧 `ensure_workspace_layout` 保持一致。 */
export const WORKSPACE_DIRECTORIES: string[] = [
  'configs',
  'reports',
  'experiments/manifests',
  'experiments/results',
  'experiments/artifacts',
  'experiments/drafts',
  'experiments/approvals',
  'submissions/validation',
  'models',
  'input',
  'data/raw',
  'data/interim',
  'data/processed',
  'docs',
  'research',
  'reproductions'
];

const PREF_STORE: string = 'youjustlead_settings';
const PREF_WORKSPACE: string = 'workspace_root';

/** 新建工作区时写入的规格模板：先让字段存在、值待确认，不要编一个像真的规格。 */
const SPEC_TEMPLATE: string = `# 规则待确认：把 competition_spec.yaml 按官方原文补齐后再走规则关口。
competition:
  name: null
  platform: null
  task_type: null
  deadline: null
evaluation:
  primary_metric: null
  direction: maximize
submission:
  format: null
  filename_rule: null
  daily_limit: null
approval:
  requires_human_confirmation: true
  official_evidence:
    source_type: null
    source_locator: null
    reviewed_at: null
    fields: {}
  unresolved_questions: []
`;

/**
 * 判断一个路径/URI 能不能访问。
 *
 * picker 给的是 `file://docs/...` 这种 URI：`fs.accessSync` 对它的支持并不稳定
 * （实测选完目录立刻返回 false），所以再退一步用 `statSync` 判一次。
 */
function canAccess(target: string): boolean {
  try {
    if (fs.accessSync(target)) {
      return true;
    }
  } catch (error) {
    // URI 形式可能不被 accessSync 支持，交给 statSync 再判一次。
  }
  try {
    fs.statSync(target);
    return true;
  } catch (error) {
    return false;
  }
}

/**
 * 取用户「文档」目录。
 *
 * `getUserDocumentDir` 不是所有设备都有（API 11 起），静态检查也要求就地判能力，
 * 所以判在函数里面：没有这个能力就抛标记，让界面说清"这台机器上用不了"。
 */
function userDocumentDir(): string {
  if (canIUse('SystemCapability.FileManagement.File.Environment.FolderObtain')) {
    try {
      return Environment.getUserDocumentDir();
    } catch (error) {
      throw error as Error;
    }
  }
  throw new Error(WORKSPACE_UNSUPPORTED);
}

/**
 * 读一个由文件选择器选中的文件。
 *
 * **不能直接 `fs.readTextSync(uri)`**：picker 给的是 `file://docs/...`，readTextSync 只认沙箱路径，
 * 实测直接报 13900002 No such file or directory（和目录 URI 是同一类限制）。必须先 `openSync`
 * 拿到句柄，再按 fd 读字节，最后自己解码成 UTF-8——这条路径是实测能走通的。
 */
export function readPickedText(uri: string): string {
  let opened: fs.File | null = null;
  try {
    opened = fs.openSync(uri, fs.OpenMode.READ_ONLY);
    const size: number = fs.statSync(opened.fd).size;
    const buffer: ArrayBuffer = new ArrayBuffer(size);
    const read: number = fs.readSync(opened.fd, buffer);
    const decoder: util.TextDecoder = util.TextDecoder.create('utf-8');
    return decoder.decodeToString(new Uint8Array(buffer.slice(0, read)));
  } catch (error) {
    throw error as Error;
  } finally {
    if (opened !== null) {
      try {
        fs.closeSync(opened);
      } catch (closeError) {
        // 句柄随进程结束回收；这里的失败不改变上面读到的内容。
      }
    }
  }
}

/**
 * 建目录，已经存在就跳过。
 *
 * 别省成 `fs.mkdirSync(path, true)`：这个版本上**目录已存在时它会抛 13900015 File exists**
 * （`@ohos.file.fs.d.ts` 的 `mkdirSync(path, recursion)` 就把这条列在 `@throws` 里），
 * 于是"建骨架"第二次点就报错。递归创建只保证多级，不保证幂等。
 */
function ensureDir(target: string): void {
  if (canAccess(target)) {
    return;
  }
  try {
    fs.mkdirSync(target, true);
  } catch (error) {
    throw error as Error;
  }
}

/**
 * 打开一个文件写一段文本再关掉。
 *
 * 写失败和关失败的处理不一样：写失败一定要让调用方知道（这次落盘没成），
 * 关失败只丢一个句柄、随进程结束回收，不该把一次已经成功的写入改判成失败。
 */
function writeTextAt(target: string, text: string, append: boolean): void {
  let opened: fs.File | null = null;
  try {
    const flags: number = append
      ? fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.APPEND
      : fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC;
    opened = fs.openSync(target, flags);
    fs.writeSync(opened.fd, text);
  } catch (error) {
    throw error as Error;
  } finally {
    if (opened !== null) {
      try {
        fs.closeSync(opened);
      } catch (closeError) {
        // 句柄随进程结束回收；这里的失败不改变上面那次写入的结果。
      }
    }
  }
}

export class LocalWorkspace {
  /** 工作区根：用户文档目录下的真实路径，或空串表示还没准备。 */
  root: string = '';
  /** 当前进程是否真的能读到这个目录（授权被收回时会变 false）。 */
  readable: boolean = false;

  constructor(root: string = '') {
    this.root = root;
  }

  /** 从偏好存储里恢复上次准备的工作区，并测一次可读性。 */
  static async restore(context: common.UIAbilityContext): Promise<LocalWorkspace> {
    try {
      const store: preferences.Preferences = await preferences.getPreferences(context, PREF_STORE);
      const saved: preferences.ValueType = await store.get(PREF_WORKSPACE, '');
      const workspace: LocalWorkspace = new LocalWorkspace(typeof saved === 'string' ? saved : '');
      workspace.readable = workspace.canRead();
      return workspace;
    } catch (error) {
      throw error as Error;
    }
  }

  /** 记住工作区根，下次启动直接恢复。 */
  private static async remember(context: common.UIAbilityContext, root: string): Promise<void> {
    try {
      const store: preferences.Preferences = await preferences.getPreferences(context, PREF_STORE);
      await store.put(PREF_WORKSPACE, root);
      await store.flush();
    } catch (error) {
      throw error as Error;
    }
  }

  /**
   * 准备用户可见的工作区：申请「文档目录」权限 → 建 `文档/YouJustLead`。
   *
   * 为什么不用 picker 选任意目录：picker 返回的目录 URI 在本版本上只能用 fs 打开，
   * **不能在它里面创建或列出子项**（实测 13900002 No such file or directory），
   * 而同样这段代码写应用沙箱是成功的。用户文档目录是官方明确允许应用读写的路径，
   * 代价是首次使用会弹一次系统权限确认。
   */
  static async prepareUserFolder(context: common.UIAbilityContext): Promise<LocalWorkspace> {
    try {
      const manager: abilityAccessCtrl.AtManager = abilityAccessCtrl.createAtManager();
      const outcome: PermissionRequestResult =
        await manager.requestPermissionsFromUser(context, [DOCUMENTS_PERMISSION]);
      const granted: boolean = outcome.authResults.length > 0 && outcome.authResults[0] === 0;
      if (!granted) {
        throw new Error(WORKSPACE_PERMISSION_DENIED);
      }
      const root: string = `${userDocumentDir()}/${WORKSPACE_FOLDER}`;
      ensureDir(root);
      await LocalWorkspace.remember(context, root);
      const workspace: LocalWorkspace = new LocalWorkspace(root);
      workspace.readable = workspace.canRead();
      return workspace;
    } catch (error) {
      throw error as Error;
    }
  }

  /** 当前能不能读到这个目录：授权失效时返回 false，界面据此要求重新准备。 */
  canRead(): boolean {
    if (this.root.length === 0) {
      return false;
    }
    return canAccess(this.root);
  }

  /** 是否已经准备过工作区。 */
  hasRoot(): boolean {
    return this.root.length > 0;
  }

  /** 拼一个工作区内的路径（真实路径，不是 URI，直接拼 `/`）。 */
  join(relative: string): string {
    if (this.root.length === 0) {
      throw new Error('还没有准备用户目录');
    }
    const clean: string = relative.startsWith('/') ? relative.substring(1) : relative;
    return this.root.endsWith('/') ? `${this.root}${clean}` : `${this.root}/${clean}`;
  }

  exists(relative: string): boolean {
    return canAccess(this.join(relative));
  }

  /**
   * 建出目录骨架，并放一份待确认的规格模板与空账本。已存在的文件不覆盖。
   *
   * 返回"这次是否新建了文件"：账本是审计流水，重复点按钮不该反复记同一条事件。
   */
  async initSkeleton(): Promise<boolean> {
    try {
      let created: boolean = false;
      for (const relative of WORKSPACE_DIRECTORIES) {
        ensureDir(this.join(relative));
      }
      if (!canAccess(this.join('competition_spec.yaml'))) {
        this.writeText('competition_spec.yaml', SPEC_TEMPLATE);
        created = true;
      }
      if (!canAccess(this.join('ledger.jsonl'))) {
        this.writeText('ledger.jsonl', '');
        created = true;
      }
      return created;
    } catch (error) {
      throw error as Error;
    }
  }

  readText(relative: string): string {
    try {
      return fs.readTextSync(this.join(relative));
    } catch (error) {
      throw error as Error;
    }
  }

  writeText(relative: string, text: string): void {
    writeTextAt(this.join(relative), text, false);
  }

  /** 追加一行（账本用）。 */
  appendLine(relative: string, line: string): void {
    writeTextAt(this.join(relative), `${line}\n`, true);
  }

  /** 删掉一个文件：写坏了的中间产物要能清掉（对齐 Python 侧落盘失败时的 unlink）。 */
  remove(relative: string): void {
    try {
      fs.unlinkSync(this.join(relative));
    } catch (error) {
      throw error as Error;
    }
  }

  /**
   * 工作区里某个文件的 SHA256（小写十六进制）。
   *
   * 用 `fileIo` 自带的 hash：直接摘要**文件字节**，与 Python 侧 `file_sha256()` 完全等价
   * （比在端侧自己编码再喂给加密框架更不容易对不上）；它返回大写，转成小写好比对。
   */
  static async sha256Of(target: string): Promise<string> {
    try {
      return (await hash.hash(target, 'sha256')).toLowerCase();
    } catch (error) {
      throw error as Error;
    }
  }
}
