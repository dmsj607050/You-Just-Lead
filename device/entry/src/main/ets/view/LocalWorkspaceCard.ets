import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import AppTheme from '../common/AppTheme';
import { tFor, tfFor } from '../common/I18n';
import { appendEvent, eventCount } from '../common/LocalLedger';
import { RuleReadiness, ruleReadiness } from '../common/LocalRules';
import { LocalWorkspace, WORKSPACE_PERMISSION_DENIED, WORKSPACE_UNSUPPORTED } from '../common/LocalWorkspace';
import { YamlMap, parseYaml } from '../common/YamlLite';
import { CardPanel, EmptyHint, KeyValueRow } from './Widgets';

/**
 * 本地工作区卡片：选目录、建骨架、自检。
 *
 * 这是「端侧自足」的入口，**必须能在没有后端时使用**——所以它自己取上下文、自己读文件，
 * 不依赖任何 HTTP 调用，并且同时挂在启动页与设置页上：后端挂了也走得到。
 */

/** 指纹只显示前 12 位。 */
function shortHash(value: string): string {
  if (value.length === 0) {
    return '';
  }
  return value.length > 12 ? value.substring(0, 12) : value;
}

/**
 * 把异常变成一句能定位问题的提示。
 *
 * 系统 API 的 message 常常只有一句 "Permission denied"，光看这句分不清是授权没拿到
 * 还是这个目录根本不可写；带上 code（如 201 / 13900001）才能查。
 */
function describeError(error: Object): string {
  const failure: BusinessError = error as BusinessError;
  const message: string = failure.message !== undefined ? failure.message : `${error}`;
  if (failure.code === undefined || failure.code === 0) {
    return message;
  }
  return `${message}（code ${failure.code}）`;
}

/** 建骨架时写进账本的载荷（键名与端侧工作区字段一致）。 */
interface WorkspaceInitPayload {
  root: string;
  spec_sha256: string;
}

/**
 * 卡片上的一个文字按钮。
 *
 * 必须是 @Component 而不是 @Builder：@Builder 的按值参数只在首帧取值，
 * 后来可点状态从 false 变 true 时按钮仍然是禁用的（状态行变了、按钮没变，
 * 看起来就像"点了没反应"）。@Prop 才会跟着父组件刷新。
 */
@Component
struct LocalActionButton {
  @Prop label: string = '';
  /** 不能叫 `enabled`：与通用属性同名，ArkTS 会报不可赋值。 */
  @Prop active: boolean = false;
  onTap: () => void = () => {
  };

  build() {
    Text(this.label)
      .fontSize(13)
      .fontColor(this.active ? AppTheme.PRIMARY : AppTheme.TEXT_TERTIARY)
      .padding({ left: 12, right: 12, top: 6, bottom: 6 })
      .enabled(this.active)
      .onClick(() => {
        this.onTap();
      })
  }
}

@Component
export struct LocalWorkspaceCard {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  @State workspaceRoot: string = '';
  @State readable: boolean = false;
  @State specExists: boolean = false;
  @State profile: string = '';
  @State fieldCount: number = 0;
  @State missingValue: number = 0;
  @State missingAnchor: number = 0;
  @State gapCount: number = 0;
  @State specHash: string = '';
  @State ledgerCount: number = 0;
  @State localError: string = '';
  @State busy: boolean = false;

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  aboutToAppear(): void {
    this.restore();
  }

  private abilityContext(): common.UIAbilityContext {
    return this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  /** 恢复上次准备的工作区，并顺带自检一次。 */
  async restore(): Promise<void> {
    this.localError = '';
    try {
      const workspace: LocalWorkspace = await LocalWorkspace.restore(this.abilityContext());
      this.workspaceRoot = workspace.root;
      this.readable = workspace.readable;
      if (workspace.hasRoot() && workspace.readable) {
        await this.inspect(workspace);
      }
    } catch (err) {
      this.localError = describeError(err as Object);
    }
  }

  /** 准备用户可见的工作区（申请文档目录权限 → 建 文档/YouJustLead）。 */
  async choose(): Promise<void> {
    this.busy = true;
    this.localError = '';
    try {
      const workspace: LocalWorkspace = await LocalWorkspace.prepareUserFolder(this.abilityContext());
      this.workspaceRoot = workspace.root;
      this.readable = workspace.readable;
      await this.inspect(workspace);
    } catch (err) {
      const message: string = describeError(err as Object);
      if (message.includes(WORKSPACE_PERMISSION_DENIED)) {
        this.localError = this.tr('settings.workspacePermissionDenied');
      } else if (message.includes(WORKSPACE_UNSUPPORTED)) {
        this.localError = this.tr('settings.workspaceUnsupported');
      } else {
        this.localError = message;
      }
    } finally {
      this.busy = false;
    }
  }

  /** 建目录骨架 + 一份待确认的规格模板 + 空账本（不覆盖已有文件）。 */
  async createLayout(): Promise<void> {
    this.busy = true;
    this.localError = '';
    try {
      const workspace: LocalWorkspace = new LocalWorkspace(this.workspaceRoot);
      const created: boolean = await workspace.initSkeleton();
      // 端侧自己记第一笔账：既是"端侧真能落账本"的证据，也把工作区的起点固定下来。
      // 只在新建成时记——账本是审计流水，反复点按钮不该刷出重复事件。
      if (created) {
        const init: WorkspaceInitPayload = {
          root: this.workspaceRoot,
          spec_sha256: await LocalWorkspace.sha256Of(workspace.join('competition_spec.yaml'))
        };
        appendEvent(workspace, 'local_workspace_initialized', JSON.stringify(init));
      }
      await this.inspect(workspace);
    } catch (err) {
      this.localError = describeError(err as Object);
    } finally {
      this.busy = false;
    }
  }

  async recheck(): Promise<void> {
    this.busy = true;
    try {
      await this.inspect(new LocalWorkspace(this.workspaceRoot));
    } catch (err) {
      this.localError = describeError(err as Object);
    } finally {
      this.busy = false;
    }
  }

  /**
   * 自检：读规格 → 解析 → 算就绪度 → 算指纹 → 数账本。
   *
   * 全部在端侧算，不经过后端；这也是「端侧真的能读懂工作区」的证据。
   */
  private async inspect(workspace: LocalWorkspace): Promise<void> {
    this.localError = '';
    this.specExists = workspace.exists('competition_spec.yaml');
    this.ledgerCount = eventCount(workspace);
    if (!this.specExists) {
      this.profile = '';
      this.fieldCount = 0;
      this.missingValue = 0;
      this.missingAnchor = 0;
      this.gapCount = 0;
      this.specHash = '';
      return;
    }
    const text: string = workspace.readText('competition_spec.yaml');
    const spec: YamlMap = parseYaml(text);
    const readiness: RuleReadiness = ruleReadiness(spec);
    this.profile = readiness.profile;
    this.fieldCount = readiness.requiredFieldCount;
    this.missingValue = readiness.missingValueCount;
    this.missingAnchor = readiness.missingAnchorCount;
    this.gapCount = readiness.gapCount;
    this.specHash = shortHash(await LocalWorkspace.sha256Of(workspace.join('competition_spec.yaml')));
  }

  build() {
    CardPanel({
      title: this.tr('settings.localWorkspace'),
      subtitle: this.tr('settings.localWorkspaceSubtitle')
    }) {
      Column() {
        KeyValueRow({
          label: this.tr('settings.workspacePath'),
          value: this.workspaceRoot.length > 0 ? this.workspaceRoot : this.tr('settings.workspaceNone'),
          mono: true
        })

        if (this.workspaceRoot.length > 0) {
          Text(this.readable ? this.tr('settings.workspaceReady') : this.tr('settings.workspaceNotReadable'))
            .fontSize(12)
            .fontColor(this.readable ? AppTheme.TEXT_TERTIARY : AppTheme.WARN_TEXT)
            .width('100%')
            .margin({ top: 4 })
        }

        Row({ space: 8 }) {
          LocalActionButton({
            label: this.busy ? this.tr('settings.working') : this.tr('settings.chooseFolder'),
            active: !this.busy,
            onTap: () => {
              this.choose();
            }
          })
          LocalActionButton({
            label: this.tr('settings.initSkeleton'),
            active: !this.busy && this.readable,
            onTap: () => {
              this.createLayout();
            }
          })
          LocalActionButton({
            label: this.tr('settings.recheck'),
            active: !this.busy && this.readable,
            onTap: () => {
              this.recheck();
            }
          })
        }
        .width('100%')
        .margin({ top: 12, bottom: 12 })

        if (this.localError.length > 0) {
          Text(this.localError)
            .fontSize(12)
            .fontColor(AppTheme.DANGER)
            .width('100%')
            .margin({ bottom: 10 })
        }

        if (this.workspaceRoot.length === 0) {
          EmptyHint({ text: this.tr('settings.workspaceHint') })
        } else {
          KeyValueRow({
            label: this.tr('settings.specFile'),
            value: this.specExists ? this.tr('settings.present') : this.tr('settings.missing')
          })
          KeyValueRow({ label: this.tr('settings.ruleProfile'), value: this.profile })
          KeyValueRow({ label: this.tr('settings.ruleFields'), value: `${this.fieldCount}` })
          KeyValueRow({
            label: this.tr('settings.ruleGaps'),
            value: this.trf('settings.ruleGapsValue', [
              `${this.gapCount}`, `${this.missingValue}`, `${this.missingAnchor}`
            ])
          })
          KeyValueRow({ label: this.tr('settings.specFingerprint'), value: this.specHash, mono: true })
          KeyValueRow({ label: this.tr('settings.ledgerEvents'), value: `${this.ledgerCount}` })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }
}
