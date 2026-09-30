import { common } from '@kit.AbilityKit';
import { shortHash } from './Format';
import { appendEvent, eventCount } from './LocalLedger';
import { GateApproval, currentApproval } from './LocalRuleGate';
import { RuleReadiness, ruleReadiness } from './LocalRules';
import { LocalWorkspace, WORKSPACE_PERMISSION_DENIED, WORKSPACE_UNSUPPORTED } from './LocalWorkspace';
import { YamlMap, parseYaml } from './YamlLite';

/**
 * 端侧工作区：状态与操作，一处实现两处用。
 *
 * 全部在端侧算，**不经过后端** —— 后端不在时这几项仍然要能显示出来（端侧自足那条支线）。
 * 抽成一个模块是因为「工作区」这件事现在有两处要看、还要能改：启动页的
 * `LocalWorkspaceCard`，以及设置页的工作区卡片与高级信息卡片。各写一份的话，
 * 同一份规格会在一个屏上被算成两个样子。
 */

/** 建骨架时写进账本的载荷（键名与端侧工作区字段一致）。 */
interface WorkspaceInitPayload {
  root: string;
  spec_sha256: string;
}

/** 端侧工作区自检的结果：目录在哪、规格齐不齐、账本记了多少笔。 */
export interface LocalWorkspaceReport {
  /** 工作区根目录；还没准备时是空串。 */
  root: string;
  /** 目录现在读得到吗（被移走或删掉就是 false）。 */
  readable: boolean;
  /** 工作区里有没有 competition_spec.yaml。 */
  specExists: boolean;
  /** 规则档案名（如 aic_multimodal_detection）。 */
  profile: string;
  fieldCount: number;
  missingValue: number;
  missingAnchor: number;
  gapCount: number;
  /** 规格文件的短指纹。 */
  specHash: string;
  /** 规则是否已完成人工批准（读规格里的 requires_human_confirmation）。 */
  ruleApproved: boolean;
  /** 端侧账本里的条数。 */
  ledgerCount: number;
}

/** 准备目录失败的原因。界面据此换成人话，而不是把系统异常原文摊给用户。 */
export const WORKSPACE_FAILED_PERMISSION: string = 'permission';
export const WORKSPACE_FAILED_UNSUPPORTED: string = 'unsupported';

/** 还没准备任何工作区时的那份报告。 */
export function emptyReport(): LocalWorkspaceReport {
  return {
    root: '',
    readable: false,
    specExists: false,
    profile: '',
    fieldCount: 0,
    missingValue: 0,
    missingAnchor: 0,
    gapCount: 0,
    specHash: '',
    ruleApproved: false,
    ledgerCount: 0
  };
}

/** 恢复上次准备的工作区并自检。 */
export async function inspectLocalWorkspace(context: common.UIAbilityContext): Promise<LocalWorkspaceReport> {
  return inspectWorkspace(await LocalWorkspace.restore(context));
}

/**
 * 对一个已知工作区做自检。
 *
 * 读不到目录时返回的那份报告把 `readable` 标成 false，而不是抛错 —— 调用方要能显示
 * 「现在读不到这个目录」，那是一条状态，不是一次异常。
 */
export async function inspectWorkspace(workspace: LocalWorkspace): Promise<LocalWorkspaceReport> {
  const report: LocalWorkspaceReport = emptyReport();
  report.root = workspace.root;
  report.readable = workspace.readable;
  report.ledgerCount = eventCount(workspace);

  if (!workspace.hasRoot() || !workspace.readable) {
    return report;
  }

  report.specExists = workspace.exists('competition_spec.yaml');
  if (!report.specExists) {
    return report;
  }

  const text: string = workspace.readText('competition_spec.yaml');
  const spec: YamlMap = parseYaml(text);
  const readiness: RuleReadiness = ruleReadiness(spec);
  report.profile = readiness.profile;
  report.fieldCount = readiness.requiredFieldCount;
  report.missingValue = readiness.missingValueCount;
  report.missingAnchor = readiness.missingAnchorCount;
  report.gapCount = readiness.gapCount;
  report.specHash = shortHash(await LocalWorkspace.sha256Of(workspace.join('competition_spec.yaml')));
  // 批准状态只认规格里的 requires_human_confirmation，判定口径与后端一致（这里不另立标准）。
  const approval: GateApproval = currentApproval(spec);
  report.ruleApproved = !approval.required;
  return report;
}

/**
 * 准备用户可见的工作区：申请「文档」目录权限 → 建 文档/YouJustLead → 自检。
 *
 * 失败的原因用 `WORKSPACE_FAILED_*` 抛出（`error.message` 就是那个常量），
 * 界面对照常量换成人话。
 */
export async function prepareLocalWorkspace(context: common.UIAbilityContext): Promise<LocalWorkspaceReport> {
  try {
    const workspace: LocalWorkspace = await LocalWorkspace.prepareUserFolder(context);
    return await inspectWorkspace(workspace);
  } catch (err) {
    const message: string = (err as Error).message ?? '';
    if (message.includes(WORKSPACE_PERMISSION_DENIED)) {
      throw new Error(WORKSPACE_FAILED_PERMISSION);
    }
    if (message.includes(WORKSPACE_UNSUPPORTED)) {
      throw new Error(WORKSPACE_FAILED_UNSUPPORTED);
    }
    // ArkTS 不允许 throw 任意类型，所以这里统一重新包一层（否则编译期就红）。
    throw new Error(message.length > 0 ? message : 'workspace preparation failed');
  }
}

/**
 * 建目录骨架 + 一份待确认的规格模板 + 空账本（不覆盖已有文件），然后自检。
 *
 * 端侧自己记第一笔账：既是"端侧真能落账本"的证据，也把工作区的起点固定下来。
 * 只在新建成时记 —— 账本是审计流水，反复点按钮不该刷出重复事件。
 */
export async function buildLocalWorkspaceLayout(root: string): Promise<LocalWorkspaceReport> {
  const workspace: LocalWorkspace = new LocalWorkspace(root);
  const created: boolean = await workspace.initSkeleton();
  if (created) {
    const init: WorkspaceInitPayload = {
      root: root,
      spec_sha256: await LocalWorkspace.sha256Of(workspace.join('competition_spec.yaml'))
    };
    appendEvent(workspace, 'local_workspace_initialized', JSON.stringify(init));
  }
  return inspectWorkspace(workspace);
}
