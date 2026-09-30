import { common } from '@kit.AbilityKit';
import AppTheme from '../common/AppTheme';
import { describeError } from '../common/Format';
import IconPaths from '../common/IconPaths';
import { tFor } from '../common/I18n';
import { LocalWorkspace } from '../common/LocalWorkspace';
import {
  LocalWorkspaceReport,
  WORKSPACE_FAILED_PERMISSION,
  WORKSPACE_FAILED_UNSUPPORTED,
  buildLocalWorkspaceLayout,
  inspectLocalWorkspace,
  inspectWorkspace,
  prepareLocalWorkspace
} from '../common/LocalWorkspaceState';
import { ChipButton, InfoRow, SectionCard, StatusPill } from './Widgets';

/**
 * 工作区设置卡片：目录在哪、能不能读，以及四个端侧操作。
 *
 * 这是「端侧自足」的入口，**必须能在没有后端时使用**——所以它自己取上下文、自己读文件，
 * 不依赖任何 HTTP 调用，并且同时挂在启动页与设置页上：后端挂了也走得到。
 */
@Component
export struct LocalWorkspaceCard {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  /**
   * 是否已打开端侧规则关口（整页）。用 AppStorage 而不是回调：这张卡片同时挂在
   * 启动页和设置页上，走全局标记就不用把回调一层层穿过侧栏传下来。
   */
  @StorageLink('localGateOpen') gateOpen: boolean = false;
  /**
   * 是否已打开端侧离线状态（整页）。与规则关口同理：这一页要在后端不在时才最有用，
   * 所以同样走全局标记，从启动页和设置页都能开。
   */
  @StorageLink('localStatusOpen') statusOpen: boolean = false;
  @State workspaceRoot: string = '';
  @State readable: boolean = false;
  @State localError: string = '';
  @State busy: boolean = false;

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
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
      this.apply(await inspectLocalWorkspace(this.abilityContext()));
    } catch (err) {
      this.localError = describeError(err as Object);
    }
  }

  /** 准备用户可见的工作区（申请文档目录权限 → 建 文档/YouJustLead）。 */
  async choose(): Promise<void> {
    this.busy = true;
    this.localError = '';
    try {
      this.apply(await prepareLocalWorkspace(this.abilityContext()));
    } catch (err) {
      const message: string = describeError(err as Object);
      if (message.includes(WORKSPACE_FAILED_PERMISSION)) {
        this.localError = this.tr('settings.workspacePermissionDenied');
      } else if (message.includes(WORKSPACE_FAILED_UNSUPPORTED)) {
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
      this.apply(await buildLocalWorkspaceLayout(this.workspaceRoot));
    } catch (err) {
      this.localError = describeError(err as Object);
    } finally {
      this.busy = false;
    }
  }

  async recheck(): Promise<void> {
    this.busy = true;
    try {
      this.apply(await inspectWorkspace(new LocalWorkspace(this.workspaceRoot)));
    } catch (err) {
      this.localError = describeError(err as Object);
    } finally {
      this.busy = false;
    }
  }

  /** 把一份自检报告落到卡片的状态上。
   *
   * 卡片只显示「目录在哪、能不能读」——规则与账本的明细在设置页的「高级信息」里，
   * 那一页读的是同一份报告（`common/LocalWorkspaceState.ets`）。
   */
  private apply(report: LocalWorkspaceReport): void {
    this.localError = '';
    this.workspaceRoot = report.root;
    this.readable = report.readable;
  }

  build() {
    SectionCard({
      title: this.tr('settings.card.workspace'),
      subtitle: 'Workspace',
      icon: IconPaths.FOLDER,
      iconTone: this.readable ? 'ok' : 'muted'
    }) {
      Column() {
        InfoRow({
          label: this.tr('settings.workspacePath'),
          value: this.workspaceRoot.length > 0 ? this.workspaceRoot : this.tr('settings.workspaceNone'),
          mono: true,
          labelWidth: 96
        })

        if (this.workspaceRoot.length > 0) {
          Row() {
            StatusPill({
              label: this.readable ? this.tr('settings.available') : this.tr('settings.unavailable'),
              tone: this.readable ? 'ok' : 'warn'
            })
          }
          .width('100%')
          .margin({ bottom: 10 })
        }

        Text(this.tr('settings.workspacePurpose'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width('100%')
          .margin({ bottom: 14 })

        Row({ space: 10 }) {
          ChipButton({
            icon: IconPaths.FOLDER,
            label: this.busy ? this.tr('settings.working') : this.tr('settings.chooseFolder'),
            tone: 'outline',
            active: !this.busy,
            onTap: () => {
              this.choose();
            }
          })
          ChipButton({
            icon: IconPaths.PLUS,
            label: this.tr('settings.initSkeleton'),
            tone: 'outline',
            active: !this.busy && this.readable,
            onTap: () => {
              this.createLayout();
            }
          })
        }
        .width('100%')

        Row({ space: 10 }) {
          ChipButton({
            icon: IconPaths.REFRESH,
            label: this.tr('settings.recheck'),
            tone: 'outline',
            active: !this.busy && this.readable,
            onTap: () => {
              this.recheck();
            }
          })
          ChipButton({
            icon: IconPaths.CHECK,
            label: this.tr('settings.ruleGate'),
            tone: 'outline',
            active: !this.busy && this.readable,
            onTap: () => {
              this.gateOpen = true;
            }
          })
          ChipButton({
            icon: IconPaths.DOC,
            label: this.tr('settings.offlineStatus'),
            tone: 'outline',
            active: !this.busy && this.readable,
            onTap: () => {
              this.statusOpen = true;
            }
          })
        }
        .width('100%')
        .margin({ top: 10 })

        if (this.localError.length > 0) {
          Text(this.localError)
            .fontSize(12)
            .fontColor(AppTheme.DANGER)
            .width('100%')
            .margin({ top: 12 })
        }

        if (this.workspaceRoot.length === 0) {
          Text(this.tr('settings.workspaceHint'))
            .fontSize(11)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .width('100%')
            .margin({ top: 12 })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }
}
