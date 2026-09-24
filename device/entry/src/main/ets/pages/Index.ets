import {
  DashboardSnapshot,
  fetchDashboard,
  NextAction,
  ProjectSummary,
  RecentEvent,
  RunnerCapability
} from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import { priorityLabel, relativeTime, stageLabel } from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import { StepSpec, UpdateSpec } from '../common/ViewTypes';
import { WorkflowStepper, deriveSteps, initialSteps } from '../view/WorkflowStepper';
import { TopBar } from '../view/TopBar';
import { ProjectGate } from '../view/ProjectGate';
import { UserMenu } from '../view/UserMenu';
import { SideNav } from '../view/SideNav';
import { CapabilityGrid } from '../view/CapabilityGrid';
import { RecentUpdates } from '../view/RecentUpdates';
import { CardPanel, KeyValueRow, PageHeader, ProgressBar, RailItemSpec, SectionRail, StatusBadge } from '../view/Widgets';
import { WorkflowPage } from '../view/WorkflowPage';
import { ExperimentPage } from '../view/ExperimentPage';
import { LiteraturePage } from '../view/LiteraturePage';
import { DataPage } from '../view/DataPage';
import { WritingPage } from '../view/WritingPage';
import { TracePage } from '../view/TracePage';
import { ReproductionPage } from '../view/ReproductionPage';
import { SettingsPage } from '../view/SettingsPage';
import { LocalRulePage } from '../view/LocalRulePage';
import { LocalStatusPage } from '../view/LocalStatusPage';

/**
 * 主页面。
 *
 * 只负责两件事：从后端取数、把数据分发给各视图组件。
 * 具体布局与样式都在 view/ 下的组件里，页面本身不做视觉细节。
 */
@Entry
@Component
struct Index {
  /**
   * 当前语言。它必须在每个要跟着语言重绘的节点里被读到：ArkUI 只重建读到状态变量的
   * 节点，所以下面所有文案都走 `this.tr()` / `this.trf()`，由它们读一次 this.lang。
   */
  @StorageLink('lang') lang: string = 'zh';
  @State loading: boolean = false;
  @State errorText: string = '';
  /** 侧栏当前页。项目不是侧栏项，所以默认落在概览。 */
  @State activeNav: string = 'overview';
  /**
   * 概览页当前展开的一段。
   *
   * 概览原先是一整条竖着的卡片流（欢迎横幅、下一步、项目卡、能力网格、动态、快速开始），
   * 一屏装不下也没有主次。和其余长页面一样切成四段，一次只铺一段。
   */
  @State overviewSection: string = 'project';
  /** 是否已经选好项目。没选就停在项目选择页。 */
  @State entered: boolean = false;
  /** 当前项目名，顶栏显示用。 */
  @State projectName: string = '';
  /** 账户菜单是否展开。 */
  @State menuOpen: boolean = false;
  /** 最近一次取数是否成功，账户菜单据此显示后端连接状态。 */
  @State backendOnline: boolean = true;
  /** 外部唤起带进来的问题（键名与 EntryAbility 里的 PENDING_QUESTION_KEY 一致）。 */
  @StorageLink('pendingQuestion') @Watch('onPendingQuestion') pendingQuestion: string = '';
  /** 端侧规则关口是否打开。由「本地工作区」卡片置位，见 LocalWorkspaceCard。 */
  @StorageLink('localGateOpen') localGateOpen: boolean = false;
  /** 端侧离线状态是否打开。同样由「本地工作区」卡片置位。 */
  @StorageLink('localStatusOpen') localStatusOpen: boolean = false;

  @State competitionName: string = '';
  @State taskType: string = '';
  @State runner: string = '';
  @State metric: string = '';
  @State stage: string = '';
  @State blockers: string[] = [];
  @State actions: NextAction[] = [];
  @State runners: RunnerCapability[] = [];
  @State updates: UpdateSpec[] = [];
  @State steps: StepSpec[] = initialSteps();

  @State ruleTotal: number = 0;
  @State ruleMissing: number = 0;
  @State dataFiles: number = 0;
  @State dataIssues: number = 0;
  @State researchRecords: number = 0;
  @State completedExperiments: number = 0;
  /** 最新一条事件的原始时间戳，相对时间在渲染时才格式化。 */
  @State lastUpdatedAt: string = '';

  aboutToAppear(): void {
    // 冷启动时 @StorageLink 一上来就带着值，@Watch 不会触发，这里补一次。
    this.onPendingQuestion();
    this.load();
  }

  /** 有外部问题进来时直接落到工作流页，那里负责预填与提交。 */
  onPendingQuestion(): void {
    if (this.pendingQuestion.length > 0) {
      this.activeNav = 'workflow';
    }
  }

  /** 选定项目后进入工作台，并把界面重新拉一遍数据。 */
  private enterProject(project: ProjectSummary): void {
    this.projectName = project.name;
    this.activeNav = 'overview';
    this.menuOpen = false;
    this.entered = true;
    this.load();
  }

  /** 回到项目选择页。进去时页面组件会被重建，数据各自重新取。 */
  private returnToProjects(): void {
    this.menuOpen = false;
    this.entered = false;
  }

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  /** 项目卡上的「最后更新」，由原始时间戳算相对时间。 */
  private lastUpdatedText(): string {
    return this.lastUpdatedAt.length > 0 ? relativeTime(this.lang, this.lastUpdatedAt) : '';
  }

  /** 概览的一行现状：阶段 + 四个数字，压在标题下面。 */
  private overviewStatus(): string {
    return this.trf('overview.status', [stageLabel(this.lang, this.stage), `${this.dataFiles}`,
      `${this.dataIssues}`, `${this.researchRecords}`, `${this.completedExperiments}`]);
  }

  /** 后端给出的最高优先级动作；没有待办时返回空串。 */
  private nextActionText(): string {
    return this.actions.length > 0 ? this.actions[0].action : '';
  }

  /**
   * 概览分段导航的项。色点说的是这一段通不通，不是它有多少条。
   *
   * 规则字段一项用「有没有必填字段」和「缺几项」分档：没有规则档案是 danger（这条链根本没开始），
   * 有档案但缺项是 warn。
   */
  private overviewRail(): RailItemSpec[] {
    return [
      {
        key: 'project',
        label: this.tr('overview.section.project'),
        tone: this.ruleTotal === 0 ? 'danger' : (this.ruleMissing > 0 ? 'warn' : 'ok')
      },
      {
        key: 'workflow',
        label: this.tr('overview.section.workflow'),
        tone: this.blockers.length > 0 ? 'danger' : 'ok'
      },
      {
        key: 'capabilities',
        label: this.tr('overview.section.capabilities'),
        tone: this.runners.length > 0 ? 'ok' : 'danger'
      },
      {
        key: 'recent',
        label: this.tr('overview.section.recent'),
        tone: this.updates.length > 0 ? 'ok' : 'muted'
      }
    ];
  }

  /** 读取一次仪表盘快照，并把返回值摊平成各组件需要的字段。 */
  async load(): Promise<void> {
    this.loading = true;
    this.errorText = '';
    try {
      const snapshot: DashboardSnapshot = await fetchDashboard();
      // 新建项目还没填规则时这几个字段是 null，统一折成空串，界面按「未配置」显示。
      this.competitionName = snapshot.competition.name !== null ? snapshot.competition.name : '';
      this.taskType = snapshot.competition.task_type !== null ? snapshot.competition.task_type : '';
      this.runner = snapshot.competition.preferred_runner !== null ? snapshot.competition.preferred_runner : '';
      this.metric = snapshot.competition.metric !== null ? snapshot.competition.metric : '';
      this.stage = snapshot.workflow.stage;
      this.blockers = snapshot.workflow.blockers;
      this.actions = snapshot.next_actions;
      this.runners = snapshot.capabilities.runners;
      this.dataFiles = snapshot.summary.data_files;
      this.dataIssues = snapshot.summary.data_issues;
      this.researchRecords = snapshot.summary.research_records;
      this.completedExperiments = snapshot.summary.completed_experiments;

      this.ruleTotal = snapshot.competition.rule_readiness.required_fields.length;
      this.ruleMissing = this.countRuleGaps(snapshot);

      const components = snapshot.workflow.components;
      this.steps = deriveSteps(components.rules, components.data_audit, components.research,
        components.baseline, components.approvals, snapshot.workflow.completed_experiments);

      this.updates = this.buildUpdates(snapshot);
      this.lastUpdatedAt = this.newestEventTime(snapshot);
      this.backendOnline = true;
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
      this.backendOnline = false;
    } finally {
      this.loading = false;
    }
  }

  /** 统计必填规则里还缺几项。 */
  private countRuleGaps(snapshot: DashboardSnapshot): number {
    const readiness = snapshot.competition.rule_readiness;
    let missing: number = 0;
    for (const field of readiness.required_fields) {
      for (const gap of readiness.gaps) {
        if (gap.field === field) {
          missing++;
          break;
        }
      }
    }
    return missing;
  }

  /** 取最新的四条事件，最新的排在最前。不依赖接口返回顺序，也不在这里翻译。 */
  private buildUpdates(snapshot: DashboardSnapshot): UpdateSpec[] {
    const sorted: RecentEvent[] = snapshot.recent_events.slice();
    sorted.sort((left: RecentEvent, right: RecentEvent) => {
      return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
    });

    const events: UpdateSpec[] = [];
    for (const event of sorted.slice(0, 4)) {
      events.push({ eventType: event.event_type, createdAt: event.created_at });
    }
    return events;
  }

  /** 事件流里最新一条事件的时间戳，用于项目卡的「最后更新」。 */
  private newestEventTime(snapshot: DashboardSnapshot): string {
    let newestMs: number = 0;
    for (const event of snapshot.recent_events) {
      const ms: number = new Date(event.created_at).getTime();
      if (!isNaN(ms) && ms > newestMs) {
        newestMs = ms;
      }
    }
    return newestMs > 0 ? new Date(newestMs).toISOString() : '';
  }

  /** 侧栏 key 对应的页面。每个页面自己取数，切页即重新读取。 */
  @Builder
  ActivePage() {
    if (this.activeNav === 'workflow') {
      WorkflowPage()
    } else if (this.activeNav === 'experiment') {
      ExperimentPage()
    } else if (this.activeNav === 'literature') {
      LiteraturePage({
        onOpenReproduction: () => {
          this.activeNav = 'reproduction';
        }
      })
    } else if (this.activeNav === 'data') {
      DataPage()
    } else if (this.activeNav === 'writing') {
      WritingPage()
    } else if (this.activeNav === 'trace') {
      TracePage()
    } else if (this.activeNav === 'reproduction') {
      ReproductionPage()
    } else if (this.activeNav === 'settings') {
      SettingsPage()
    } else {
      this.OverviewBody()
    }
  }

  /**
   * 概览：标题 + 一行现状 + 分段导航，一次只铺一段。
   *
   * 四段分别回答「这个项目是什么」「走到哪了」「能跑什么」「刚发生了什么」。
   * 原先压在这一页上的欢迎横幅（「欢迎回来…」加三句口号）和「快速开始」入口已删除：
   * 前者没有一个数字、只是装饰，后者就是侧栏那几项，重复一遍还多出六行灰字。
   */
  @Builder
  OverviewBody() {
    Column({ space: 20 }) {
      PageHeader({
        title: this.tr('nav.overview'),
        status: this.overviewStatus(),
        onRefresh: () => {
          this.load();
        }
      })

      SectionRail({
        items: this.overviewRail(),
        active: this.overviewSection,
        onSelect: (key: string) => {
          this.overviewSection = key;
        }
      })

      if (this.overviewSection === 'project') {
        this.ProjectSection()
      } else if (this.overviewSection === 'workflow') {
        this.WorkflowSection()
      } else if (this.overviewSection === 'capabilities') {
        CapabilityGrid({ runners: this.runners })
      } else {
        RecentUpdates({ updates: this.updates })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  /** 项目段：竞赛配置 + 规则字段进度 + 阻塞项。 */
  @Builder
  ProjectSection() {
    CardPanel({ title: this.tr('overview.section.project') }) {
      KeyValueRow({
        label: this.tr('overview.field.competition'),
        value: this.competitionName
      })
      KeyValueRow({
        label: this.tr('overview.field.taskType'),
        value: this.taskType
      })
      KeyValueRow({
        label: this.tr('overview.field.metric'),
        value: this.metric
      })
      KeyValueRow({
        label: this.tr('overview.field.adapter'),
        value: this.runner
      })
      KeyValueRow({
        label: this.tr('overview.field.lastUpdated'),
        value: this.lastUpdatedText()
      })

      // 规则字段本来就是「几分之几」，画成条比写成「规则字段 24/24」快。
      ProgressBar({
        label: this.tr('overview.field.ruleFields'),
        current: this.ruleTotal - this.ruleMissing,
        total: this.ruleTotal
      })
        .margin({ top: 16 })

      Row() {
        Text(this.tr('overview.field.blockers'))
          .fontSize(13)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .layoutWeight(1)
        StatusBadge({
          text: `${this.blockers.length}`,
          tone: this.blockers.length > 0 ? 'danger' : 'ok'
        })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 18 })
    }
  }

  /** 工作流段：下一步动作 + 八步进度条。 */
  @Builder
  WorkflowSection() {
    CardPanel({ title: this.tr('card.workflow') }) {
      Row() {
        Text(this.tr('overview.nextStep'))
          .fontSize(12)
          .fontColor(AppTheme.PRIMARY_DARK)
          .backgroundColor(AppTheme.PRIMARY_SOFT)
          .borderRadius(6)
          .padding({ left: 10, right: 10, top: 4, bottom: 4 })

        Text(this.nextActionText().length > 0 ? this.nextActionText() : this.tr('overview.noPendingActions'))
          .fontSize(13)
          .fontColor(this.nextActionText().length > 0 ? AppTheme.TEXT_PRIMARY : AppTheme.TEXT_TERTIARY)
          .layoutWeight(1)
          .margin({ left: 12 })
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })

        if (this.nextActionText().length > 0) {
          Text(priorityLabel(this.lang, this.actions[0].priority))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      // 步骤条画在浅底色上：未开始的步骤点子本身是白底描边，铺在白卡上会看不见。
      Column() {
        WorkflowStepper({ steps: this.steps })
      }
      .width('100%')
      .padding({ left: 20, right: 20, top: 18, bottom: 12 })
      .margin({ top: 18 })
      .backgroundColor(AppTheme.PAGE_BG)
      .borderRadius(AppTheme.RADIUS)
    }
  }

  build() {
    if (this.localGateOpen) {
      // 端侧规则关口整页覆盖：它不依赖后端项目，所以判断放在最外层，
      // 从启动页和设置页都能打开（少了这一点，没选项目时就走不到端侧关口）。
      this.LocalGateScreen()
    } else if (this.localStatusOpen) {
      // 端侧离线状态同理：它的存在意义就是"后端不在时也能看"，更不能依赖后端项目。
      this.LocalStatusScreen()
    } else if (this.entered) {
      this.Workspace()
    } else {
      // 启动先进项目选择页：项目是侧栏那些模块的上一层容器，先选定再进工作台。
      ProjectGate({
        onEnter: (project: ProjectSummary) => {
          this.enterProject(project);
        }
      })
    }
  }

  /** 端侧离线状态的整页容器：与规则关口同样的留白与滚动。 */
  @Builder
  LocalStatusScreen() {
    Column() {
      Scroll() {
        Column() {
          LocalStatusPage({
            onBack: () => {
              this.localStatusOpen = false;
            }
          })
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .constraintSize({ maxWidth: AppTheme.CONTENT_MAX_WIDTH })
        .padding({ left: 32, right: 32, top: 26, bottom: 40 })
      }
      .layoutWeight(1)
      .align(Alignment.Top)
      .scrollBar(BarState.Auto)
    }
    .width('100%')
    .height('100%')
    .backgroundColor(AppTheme.PAGE_BG)
  }

  /** 端侧规则关口的整页容器：与工作台内容区同样的留白与滚动，视觉上是一屏而不是弹层。 */
  @Builder
  LocalGateScreen() {
    Column() {
      Scroll() {
        Column() {
          LocalRulePage({
            onBack: () => {
              this.localGateOpen = false;
            }
          })
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .constraintSize({ maxWidth: AppTheme.CONTENT_MAX_WIDTH })
        .padding({ left: 32, right: 32, top: 26, bottom: 40 })
      }
      .layoutWeight(1)
      .align(Alignment.Top)
      .scrollBar(BarState.Auto)
    }
    .width('100%')
    .height('100%')
    .backgroundColor(AppTheme.PAGE_BG)
  }

  /** 工作台：顶栏（含当前项目）+ 侧栏 + 当前页面。 */
  @Builder
  Workspace() {
    // 账户菜单浮在整个界面之上，所以最外层要用 Stack 而不是 Column。
    Stack({ alignContent: Alignment.TopEnd }) {
      Column() {
        TopBar({
          projectName: this.projectName,
          onSwitchProject: () => {
            this.returnToProjects();
          },
          onAvatarClick: () => {
            this.menuOpen = !this.menuOpen;
          }
        })
        Divider().color(AppTheme.BORDER)

        SideBarContainer(SideBarContainerType.Embed) {
          SideNav({
            activeKey: this.activeNav,
            blockerCount: this.blockers.length,
            onSelect: (key: string) => {
              this.activeNav = key;
            }
          })

          Scroll() {
            Column() {
              if (this.errorText.length > 0) {
                Column() {
                  Text(this.tr('common.connectionFailed'))
                    .fontSize(16)
                    .fontWeight(FontWeight.Medium)
                    .fontColor(AppTheme.DANGER)
                  Text(this.errorText)
                    .fontSize(13)
                    .fontColor(AppTheme.DANGER)
                    .margin({ top: 8 })
                }
                .alignItems(HorizontalAlign.Start)
                .width('100%')
                .padding(20)
                .backgroundColor(AppTheme.DANGER_SOFT)
                .borderRadius(AppTheme.RADIUS)
                .margin({ bottom: 20 })
              }

              this.ActivePage()

              if (this.loading) {
                Text(this.tr('common.loading'))
                  .fontSize(12)
                  .fontColor(AppTheme.TEXT_TERTIARY)
                  .margin({ top: 12 })
              }
            }
            .alignItems(HorizontalAlign.Start)
            .width('100%')
            .constraintSize({ maxWidth: AppTheme.CONTENT_MAX_WIDTH })
            .padding({ left: 32, right: 32, top: 26, bottom: 40 })
          }
          .layoutWeight(1)
          .align(Alignment.Top)
          .scrollBar(BarState.Auto)
        }
        .layoutWeight(1)
        .autoHide(true)
        .sideBarWidth(AppTheme.SIDEBAR_WIDTH)
        .minSideBarWidth(200)
        .maxSideBarWidth(280)
        .minContentWidth(420)
        .showControlButton(true)
        .divider({ strokeWidth: 1, color: AppTheme.BORDER })
      }
      .width('100%')
      .height('100%')
      .backgroundColor(AppTheme.PAGE_BG)

      if (this.menuOpen) {
        // 全屏遮罩：背景几乎全透明（留 1/255 不透明度以便稳定接收点击），点空白处关菜单。
        Column()
          .width('100%')
          .height('100%')
          .backgroundColor('#01000000')
          .onClick(() => {
            this.menuOpen = false;
          })

        UserMenu({
          blockerCount: this.blockers.length,
          backendOnline: this.backendOnline,
          onClose: () => {
            this.menuOpen = false;
          },
          onRefresh: () => {
            this.load();
          },
          onNavigate: (key: string) => {
            this.activeNav = key;
          },
          onSwitchProject: () => {
            this.returnToProjects();
          }
        })
          .margin({ top: AppTheme.TOPBAR_HEIGHT + 8, right: 24 })
      }
    }
    .width('100%')
    .height('100%')
  }
}
