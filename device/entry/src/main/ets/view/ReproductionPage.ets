import {
  fetchReproductions,
  ReproductionCommand,
  ReproductionOutputSummary,
  ReproductionPhase,
  ReproductionPlan,
  ReproductionRun,
  ReproductionState,
  runReproduction
} from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import { formatNumber, formatTimestamp } from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import {
  CardPanel,
  ChoiceChips,
  ChoiceSpec,
  EmptyHint,
  KeyValueRow,
  PageHeader,
  RailItemSpec,
  SectionRail,
  StatusBadge
} from './Widgets';

/**
 * 复现页：把第三方仓库放进隔离容器里跑 baseline。
 *
 * 这是整条链上唯一会**执行**外部代码的地方，所以顺序刻意做成三步走：
 * 看计划（仓库/镜像/依赖/数据挂载/候选命令与出处）→ 选一条（可改写）→ 写批准说明并运行。
 * 结果不猜指标：把阶段、退出码、日志尾部和命令自己写出的产物文件摆出来，人去里面认 mAP。
 */

/** 运行状态的可读名称。 */
function runStatusText(lang: string, status: string): string {
  if (status === 'succeeded') {
    return tFor(lang, 'repro.statusSucceeded');
  }
  if (status === 'failed') {
    return tFor(lang, 'repro.statusFailed');
  }
  if (status === 'running') {
    return tFor(lang, 'repro.statusRunning');
  }
  return tFor(lang, 'repro.statusQueued');
}

/** 运行状态的徽章色调。 */
function runStatusTone(status: string): string {
  if (status === 'succeeded') {
    return 'ok';
  }
  if (status === 'failed') {
    return 'danger';
  }
  if (status === 'running') {
    return 'warn';
  }
  return 'muted';
}

/** 入口类型的中文名。类型是后端枚举（train / evaluate / infer / export）。 */
function entryKindLabel(kind: string): string {
  if (kind === 'train') {
    return '训练';
  }
  if (kind === 'evaluate') {
    return '评估';
  }
  if (kind === 'infer') {
    return '推理';
  }
  if (kind === 'export') {
    return '导出';
  }
  return kind;
}

@Component
export struct ReproductionPage {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  @State loading: boolean = false;
  @State errorText: string = '';
  @State dockerAvailable: boolean = false;
  @State dockerVersion: string = '';
  @State dockerReason: string = '';
  @State plans: ReproductionPlan[] = [];
  @State runs: ReproductionRun[] = [];
  @State section: string = 'plans';

  /** 正在批准的计划与命令；计划 id 为空表示还没选。 */
  @State activePlanId: string = '';
  @State activeCommandId: string = '';
  /** 选中命令的出处，显示给人核对。 */
  @State activeCommandSource: string = '';
  /** 命令草稿：选中一条候选命令时预填，人可以改。 */
  @State commandDraft: string = '';
  @State noteDraft: string = '';
  /** 正在提交。 */
  @State busy: boolean = false;
  @State actionError: string = '';

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  aboutToAppear(): void {
    this.load();
  }

  async load(): Promise<void> {
    this.loading = true;
    this.errorText = '';
    try {
      this.apply(await fetchReproductions());
    } catch (err) {
      this.errorText = (err as Error).message;
    } finally {
      this.loading = false;
    }
  }

  private apply(state: ReproductionState): void {
    this.dockerAvailable = state.docker.available;
    this.dockerVersion = state.docker.version === null ? '' : state.docker.version;
    this.dockerReason = state.docker.reason;
    this.plans = state.plans;
    this.runs = state.runs;
  }

  /** 选中一条候选命令：填进命令草稿，人会在这里改成容器里的路径。 */
  private pickCommand(plan: ReproductionPlan, command: ReproductionCommand): void {
    this.activePlanId = plan.plan_id;
    this.activeCommandId = command.id;
    this.activeCommandSource = command.source;
    this.commandDraft = command.command;
    this.actionError = '';
  }

  /** 这个计划是否正被编辑。 */
  private editing(plan: ReproductionPlan): boolean {
    return plan.plan_id === this.activePlanId && this.activeCommandId.length > 0;
  }

  /** 批准并运行。 */
  async approveAndRun(): Promise<void> {
    if (this.busy) {
      return;
    }
    if (this.noteDraft.trim().length === 0) {
      this.actionError = this.tr('repro.notePlaceholder');
      return;
    }
    this.busy = true;
    this.actionError = '';
    try {
      await runReproduction(this.activePlanId, this.activeCommandId,
        this.noteDraft.trim(), this.commandDraft.trim());
      // 提交完收起批准表单：草稿清空、选中清空，列表 key 随之变化后卡片会重建。
      this.noteDraft = '';
      this.commandDraft = '';
      this.activeCommandId = '';
      this.activeCommandSource = '';
      this.section = 'runs';
      await this.load();
    } catch (err) {
      this.actionError = (err as Error).message;
    } finally {
      this.busy = false;
    }
  }

  /** 一行现状：容器引擎 + 计划数 + 运行数。 */
  private statusText(): string {
    const engine: string = this.dockerAvailable
      ? this.trf('repro.engineOk', [this.dockerVersion.length > 0 ? this.dockerVersion : 'ok'])
      : this.tr('repro.engineMissing');
    return this.trf('repro.status', [engine, `${this.plans.length}`, `${this.runs.length}`]);
  }

  /** 分段导航的项。色点说的是这一段通不通。 */
  private railItems(): RailItemSpec[] {
    let plansTone: string = 'muted';
    if (this.plans.length > 0) {
      plansTone = this.dockerAvailable ? 'ok' : 'warn';
    }
    let failed: number = 0;
    for (const run of this.runs) {
      if (run.status === 'failed') {
        failed++;
      }
    }
    let runsTone: string = 'muted';
    if (this.runs.length > 0) {
      runsTone = failed > 0 ? 'warn' : 'ok';
    }
    return [
      { key: 'plans', label: this.tr('repro.section.plans'), tone: plansTone },
      { key: 'runs', label: this.tr('repro.section.runs'), tone: runsTone }
    ];
  }

  /** 某个计划的候选命令，转成可选列表。标签里带出处，方便一眼挑。 */
  private commandChoices(plan: ReproductionPlan): ChoiceSpec[] {
    const items: ChoiceSpec[] = [];
    for (const command of plan.commands) {
      const origin: string = command.origin === 'documented'
        ? this.tr('repro.commandDocumented') : this.tr('repro.commandFallback');
      items.push({
        key: command.id,
        label: `${command.id} · ${origin} · ${command.source}`,
        tone: command.origin === 'documented' ? 'ok' : 'warn'
      });
    }
    return items;
  }

  /** 数据挂载的可读文本。 */
  private datasetText(plan: ReproductionPlan): string {
    if (plan.dataset === null) {
      return this.tr('repro.datasetNone');
    }
    return `${plan.dataset.host_path} → ${plan.dataset.target}`;
  }

  /** 入口清单的一行文本。 */
  private entrypointsText(plan: ReproductionPlan): string {
    const parts: string[] = [];
    for (const item of plan.entrypoints) {
      parts.push(`${entryKindLabel(item.kind)} ${item.path}`);
    }
    return parts.join(' · ');
  }

  /** 有没有产物可以列。 */
  private hasOutputs(run: ReproductionRun): boolean {
    return run.outputs !== null;
  }

  private outputSummaries(run: ReproductionRun): ReproductionOutputSummary[] {
    return run.outputs === null ? [] : run.outputs.summaries;
  }

  private outputFilesText(run: ReproductionRun): string {
    if (run.outputs === null) {
      return '';
    }
    const parts: string[] = [];
    for (const item of run.outputs.files) {
      parts.push(`${item.root}/${item.path}`);
    }
    return parts.join('  ·  ');
  }

  /** 产物摘要的一行：文件名 + 顶层键或表头。 */
  private summaryText(item: ReproductionOutputSummary): string {
    const keys: string[] = item.keys === undefined ? [] : item.keys;
    if (keys.length > 0) {
      return `${item.file} — ${this.trf('repro.outputKeys', [keys.join(', ')])}`;
    }
    const columns: string[] = item.columns === undefined ? [] : item.columns;
    if (columns.length > 0) {
      return `${item.file} — ${this.trf('repro.outputColumns', [columns.join(', ')])}`;
    }
    return item.file;
  }

  @Builder
  ErrorBanner() {
    Column() {
      Text(this.tr('common.connectionFailed'))
        .fontSize(15)
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
  }

  /** 容器引擎不可用时的说明：这一页整个都依赖它，所以顶在最前面。 */
  @Builder
  EngineBanner() {
    Text(this.trf('repro.engineMissingDetail', [this.dockerReason.length > 0 ? this.dockerReason : '?']))
      .fontSize(13)
      .fontColor(AppTheme.WARN_TEXT)
      .width('100%')
      .padding(16)
      .backgroundColor(AppTheme.WARN_SOFT)
      .borderRadius(AppTheme.RADIUS)
  }

  /**
   * 计划卡：仓库与镜像信息 + 候选命令 + 批准表单。
   *
   * 选中态与两个输入框的值都从参数传进来，列表的 key 里也带上选中态：批准表单是随选中
   * 出现 / 收起的，这样它在选中变化时一定会重建，而不是依赖 @Builder 的刷新时机。
   * 输入框的草稿不走 key（否则每敲一个字都会重建、丢焦点），由 onChange 写回状态。
   */
  @Builder
  PlanBlock(plan: ReproductionPlan, editing: boolean, commandDraft: string, commandSource: string,
    noteDraft: string, busy: boolean, dockerAvailable: boolean) {
    CardPanel({
      title: plan.title === null || plan.title.length === 0 ? plan.plan_id : plan.title
    }) {
      Column() {
        KeyValueRow({ label: this.tr('repro.repository'), value: plan.repository })
        KeyValueRow({ label: this.tr('repro.commit'), value: plan.commit === null ? '' : plan.commit, mono: true })
        KeyValueRow({
          label: this.tr('repro.manifest'),
          value: plan.dependency_manifest === null ? this.tr('repro.manifestNone') : plan.dependency_manifest
        })
        KeyValueRow({ label: this.tr('repro.entrypoints'), value: this.entrypointsText(plan) })
        KeyValueRow({ label: this.tr('repro.dataset'), value: this.datasetText(plan) })

        Row() {
          Text(this.tr('repro.image'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width(150)
          Text(plan.image)
            .fontSize(13)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          // GPU 需求是从仓库文本推出来的提示，用徽章说，不写成一整行解释。
          StatusBadge({
            text: plan.requires_gpu ? this.tr('repro.gpuOn') : this.tr('repro.gpuOff'),
            tone: plan.requires_gpu ? 'warn' : 'muted'
          })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .padding({ top: 9, bottom: 9 })

        KeyValueRow({
          label: this.tr('repro.resources'),
          value: this.trf('repro.resourceValue', [
            plan.resources.cpus, plan.resources.memory, `${plan.resources.timeout_seconds}`
          ])
        })

        Text(this.tr('repro.commands'))
          .fontSize(14)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .width('100%')
          .margin({ top: 18, bottom: 10 })

        ChoiceChips({
          items: this.commandChoices(plan),
          active: editing ? this.activeCommandId : '',
          disabled: busy,
          onSelect: (key: string) => {
            const picked: ReproductionCommand | undefined =
              plan.commands.find((item: ReproductionCommand) => item.id === key);
            if (picked !== undefined) {
              this.pickCommand(plan, picked);
            }
          }
        })

        if (editing) {
          // 批准的是下面这一行，所以命令原文与出处必须同时显示出来给人核对。
          Text(this.trf('repro.commandSource', [commandSource]))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .width('100%')
            .margin({ top: 4 })

          TextInput({ text: commandDraft })
            .fontSize(12)
            .width('100%')
            .height(38)
            .backgroundColor(AppTheme.PAGE_BG)
            .borderRadius(AppTheme.RADIUS_SM)
            .margin({ top: 8 })
            .enabled(!busy)
            .onChange((value: string) => {
              this.commandDraft = value;
            })

          Text(this.tr('repro.commandHint'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .width('100%')
            .margin({ top: 8 })

          Row() {
            TextInput({ text: noteDraft, placeholder: this.tr('repro.notePlaceholder') })
              .fontSize(13)
              .layoutWeight(1)
              .height(38)
              .backgroundColor(AppTheme.PAGE_BG)
              .borderRadius(AppTheme.RADIUS_SM)
              .enabled(!busy)
              .onChange((value: string) => {
                this.noteDraft = value;
                this.actionError = '';
              })

            Text(busy ? this.tr('repro.submitting') : this.tr('repro.approveAndRun'))
              .fontSize(13)
              .fontColor(Color.White)
              .backgroundColor(dockerAvailable && !busy ? AppTheme.PRIMARY : AppTheme.TEXT_TERTIARY)
              .borderRadius(AppTheme.RADIUS_SM)
              .padding({ left: 16, right: 16, top: 9, bottom: 9 })
              .margin({ left: 10 })
              .onClick(() => {
                this.approveAndRun();
              })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)
          .margin({ top: 12 })
        }

        // 批准前要说清容器能碰什么：这两行是审批的依据，不是脚注。
        Text(this.tr('repro.policy'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 16 })
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
    }
  }

  /** 一个阶段的摘要行：阶段名 + 网络 + 退出码 + 耗时。 */
  @Builder
  PhaseRow(title: string, phase: ReproductionPhase) {
    Row() {
      Text(title)
        .fontSize(13)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .layoutWeight(1)
      StatusBadge({
        text: phase.network === 'none' ? '无网' : '有网',
        tone: phase.network === 'none' ? 'ok' : 'warn'
      })
      Text(this.trf('repro.exitCode', [`${phase.exit_code}`]))
        .fontSize(12)
        .fontColor(phase.timed_out || phase.exit_code !== 0 ? AppTheme.DANGER : AppTheme.TEXT_SECONDARY)
        .margin({ left: 10 })
      Text(this.trf('repro.duration', [formatNumber(phase.duration_seconds, 1)]))
        .fontSize(12)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .margin({ left: 10 })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
    .padding({ top: 6, bottom: 6 })
  }

  /** 运行卡：状态 + 命令 + 两个阶段 + 产物 + 日志尾部。 */
  @Builder
  RunBlock(run: ReproductionRun) {
    CardPanel({
      title: `${run.run_id} · ${run.repository}`
    }) {
      Column() {
        Row() {
          StatusBadge({ text: runStatusText(this.lang, run.status), tone: runStatusTone(run.status) })
          if (run.command_overridden) {
            StatusBadge({ text: this.tr('repro.rewritten'), tone: 'muted' })
              .margin({ left: 8 })
          }
          Text(formatTimestamp(run.created_at))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ left: 12 })
            .layoutWeight(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        Text(run.command)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .width('100%')
          .margin({ top: 12 })
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })

        if (run.error !== null && run.error.length > 0) {
          Text(run.error)
            .fontSize(12)
            .fontColor(AppTheme.DANGER)
            .width('100%')
            .margin({ top: 10 })
        }

        // 阶段顺序本身就是隔离的说明：先下载（有网），再安装并运行（无网）。
        Column() {
          ForEach(run.phases, (phase: ReproductionPhase) => {
            this.PhaseRow(
              phase.phase === 'download_wheels' ? this.tr('repro.phaseDownload') : this.tr('repro.phaseRun'),
              phase
            )
          }, (phase: ReproductionPhase) => `${phase.phase}-${phase.network}-${phase.exit_code}`)
        }
        .width('100%')
        .margin({ top: 12 })

        if (this.hasOutputs(run)) {
          Text(this.tr('repro.outputs'))
            .fontSize(13)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .width('100%')
            .margin({ top: 16, bottom: 8 })

          if (this.outputSummaries(run).length === 0) {
            Text(this.outputFilesText(run).length > 0 ? this.outputFilesText(run) : this.tr('repro.outputsEmpty'))
              .fontSize(12)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .width('100%')
              .maxLines(4)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          } else {
            // JSON/CSV 摘要写在前：指标就在这些键里。
            ForEach(this.outputSummaries(run), (item: ReproductionOutputSummary) => {
              Text(this.summaryText(item))
                .fontSize(12)
                .fontColor(AppTheme.TEXT_SECONDARY)
                .width('100%')
                .margin({ bottom: 6 })
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }, (item: ReproductionOutputSummary) => item.file)

            Text(this.outputFilesText(run))
              .fontSize(12)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .width('100%')
              .maxLines(4)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
        }

        if (run.log_tail.length > 0) {
          Text(this.tr('repro.logTail'))
            .fontSize(13)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .width('100%')
            .margin({ top: 16, bottom: 8 })
          Text(run.log_tail)
            .fontSize(11)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
            .padding(12)
            .backgroundColor(AppTheme.PAGE_BG)
            .borderRadius(AppTheme.RADIUS_SM)
            .maxLines(16)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
    }
  }

  build() {
    Column({ space: 20 }) {
      PageHeader({
        title: this.tr('nav.reproduction'),
        status: this.statusText(),
        onRefresh: () => {
          this.load();
        }
      })

      if (!this.dockerAvailable) {
        this.EngineBanner()
      }

      if (this.errorText.length > 0) {
        this.ErrorBanner()
      }

      if (this.actionError.length > 0) {
        Text(this.trf('repro.actionFailed', [this.actionError]))
          .fontSize(12)
          .fontColor(AppTheme.DANGER)
          .width('100%')
      }

      SectionRail({
        items: this.railItems(),
        active: this.section,
        onSelect: (key: string) => {
          this.section = key;
        }
      })

      if (this.section === 'runs') {
        if (this.runs.length === 0) {
          CardPanel({ title: this.tr('repro.section.runs') }) {
            EmptyHint({ text: this.tr('repro.noRuns') })
          }
        } else {
          Column({ space: 16 }) {
            ForEach(this.runs, (run: ReproductionRun) => {
              this.RunBlock(run)
            }, (run: ReproductionRun) => `${run.run_id}-${run.status}-${this.lang}`)
          }
          .width('100%')
        }
      } else {
        if (this.plans.length === 0) {
          CardPanel({ title: this.tr('repro.section.plans') }) {
            EmptyHint({ text: this.tr('repro.noPlans') })
          }
        } else {
          Column({ space: 16 }) {
            ForEach(this.plans, (plan: ReproductionPlan) => {
              // 参数按值传：选中态一变，卡片就重建，批准表单才会出现 / 收起。
              this.PlanBlock(plan, this.editing(plan), this.commandDraft, this.activeCommandSource,
                this.noteDraft, this.busy, this.dockerAvailable)
            }, (plan: ReproductionPlan) =>
              // key 里带上选中态与语言：ForEach 按 key 去重，key 不变就不会重建节点。
              `${plan.plan_id}-${plan.commit}-${this.editing(plan) ? this.activeCommandId : 'none'}-${this.lang}`)
          }
          .width('100%')
        }
      }

      if (this.loading) {
        Text(this.tr('common.loading'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 12 })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }
}
