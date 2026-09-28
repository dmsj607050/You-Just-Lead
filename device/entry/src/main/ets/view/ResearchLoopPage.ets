import {
  backfillResearchLoop,
  fetchResearchContract,
  fetchResearchLoop,
  ResearchActionSpec,
  ResearchCheckValue,
  ResearchContract,
  ResearchDecision,
  ResearchEvidence,
  ResearchExperiment,
  ResearchHypothesis,
  ResearchLoopJob,
  ResearchLoopSnapshot,
  ResearchLoopStep,
  stepResearchLoop
} from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import { formatTimestamp } from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import { CardPanel, EmptyHint, PageHeader, RailItemSpec, SectionRail, StatusBadge } from './Widgets';

/**
 * 研究循环页：这套编排框架的正面。
 *
 * 四段分别回答「现在在做什么」「有哪些假设」「上次核查查到了什么」「这一路是怎么走过来的」，
 * 与 Windows 端逐段对齐（同一组分段、同样的顺序、同样的措辞）—— 两边看的是同一条循环。
 *
 * **文案一律来自契约**（`GET /api/research/contract`）：动作名、九项核查、判定值、状态与
 * 作业/步骤状态的中文名和色调都在后端定义一次，这里一个都不写死。写死一份的代价不是多几行，
 * 而是静默漂移 —— 后端删掉一个动作，界面还显示着它的名字，谁都不会发现。
 *
 * 这一页只做两件写操作：推进一步、重新回填。要动算力的动作（跑训练、复现）不会被这两下
 * 触发，它们只被登记成待批准 —— 这条边界在界面上点多少下都不会被绕过。
 */

/** 契约缓存：一整份词汇表，取一次就够。取到后靠 contractVersion 触发一次重绘。 */
let vocabulary: ResearchContract | null = null;

/** 轮询句柄。没有在轮询时是 -1。 */
let pollTimer: number = -1;

/** 轮询间隔。一步要真调模型，几秒看一次足够。 */
const POLL_INTERVAL_MS: number = 3000;

@Component
export struct ResearchLoopPage {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';

  @State loading: boolean = false;
  @State errorText: string = '';
  @State section: string = 'now';
  /** 契约是否到位。取到后改一下它，让读到契约的那些节点重建一次。 */
  @State contractVersion: number = -1;

  @State hypotheses: ResearchHypothesis[] = [];
  @State experiments: ResearchExperiment[] = [];
  @State evidence: ResearchEvidence[] = [];
  @State decisions: ResearchDecision[] = [];
  @State jobs: ResearchLoopJob[] = [];
  @State nextActionName: string = '';
  @State nextActionReason: string = '';
  /** 「跑不起来」的设计有哪些（判据在后端，这里只认它的结论）。 */
  @State undesignableIds: string[] = [];

  @State hypothesisTotal: number = 0;
  @State falsifiableTotal: number = 0;
  @State experimentTotal: number = 0;
  @State awaitingEvidence: number = 0;
  @State undesignableTotal: number = 0;
  @State branchTotal: number = 0;
  @State activeBranches: number = 0;
  @State evidenceTotal: number = 0;
  @State runningJob: string = '';

  /** 正在提交推进或回填。 */
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

  aboutToDisappear(): void {
    this.stopPolling();
  }

  async load(): Promise<void> {
    this.loading = true;
    this.errorText = '';
    try {
      await this.ensureVocabulary();
      this.apply(await fetchResearchLoop());
    } catch (err) {
      this.errorText = (err as Error).message;
    } finally {
      this.loading = false;
    }
  }

  /**
   * 取一次契约。取不到不算致命：缺的是中文名，动作名本身还在，界面照样能用 ——
   * 所以这里只记下失败，不把它抛给调用方。
   */
  private async ensureVocabulary(): Promise<void> {
    if (vocabulary !== null) {
      return;
    }
    try {
      const loaded: ResearchContract = await fetchResearchContract();
      vocabulary = loaded;
      this.contractVersion = loaded.contract_version;
    } catch (err) {
      // 契约拿不到时下面所有 lookup 都退回内部名字，界面不会因此空白。
    }
  }

  /** 把快照摊平成各段需要的字段。 */
  private apply(snapshot: ResearchLoopSnapshot): void {
    this.hypotheses = snapshot.hypotheses;
    this.experiments = snapshot.experiments;
    this.evidence = snapshot.evidence;
    this.decisions = snapshot.decisions;
    this.jobs = snapshot.jobs;
    this.nextActionName = snapshot.next_action.action;
    this.nextActionReason = snapshot.next_action.reason;
    this.undesignableIds = snapshot.summary.experiments.undesignable;

    this.hypothesisTotal = snapshot.summary.hypotheses.total;
    this.falsifiableTotal = snapshot.summary.hypotheses.falsifiable;
    this.experimentTotal = snapshot.summary.experiments.total;
    this.awaitingEvidence = snapshot.summary.experiments.awaiting_evidence.length;
    this.undesignableTotal = snapshot.summary.experiments.undesignable.length;
    this.branchTotal = snapshot.summary.branches.total;
    this.activeBranches = snapshot.summary.branches.active.length;
    this.evidenceTotal = snapshot.evidence.length;
    this.runningJob = snapshot.running === null ? '' : snapshot.running;
  }

  // ------------------------------------------------------------------ 契约查询

  /** 动作条目的三个标记（要不要人批准 / 是不是结束）。 */
  private actionSpec(name: string): ResearchActionSpec | null {
    const table: ResearchContract | null = vocabulary;
    if (table !== null) {
      for (const action of table.actions) {
        if (action.name === name) {
          return action;
        }
      }
    }
    return null;
  }

  /** 动作的中文名。契约没到位时退回动作名本身 —— 显示英文也比显示空白好。 */
  private actionLabel(name: string): string {
    const item: ResearchActionSpec | null = this.actionSpec(name);
    return item === null ? name : item.label;
  }

  /** 九项核查在界面上的正向问法（判词那条留给验证器，不在这里显示）。 */
  private checkTitle(name: string): string {
    const table: ResearchContract | null = vocabulary;
    if (table !== null) {
      for (const check of table.checks) {
        if (check.name === name) {
          return check.title;
        }
      }
    }
    return name;
  }

  /** 判定值的中文名。 */
  private verdictLabel(name: string): string {
    const table: ResearchContract | null = vocabulary;
    if (table !== null) {
      for (const verdict of table.verdicts) {
        if (verdict.name === name) {
          return verdict.label;
        }
      }
    }
    return name;
  }

  /** 假设 / 分支 / 作业 / 步骤状态的中文名。内部取值不该直接印给用户看。 */
  private statusLabel(name: string): string {
    const table: ResearchContract | null = vocabulary;
    if (table !== null) {
      for (const item of table.hypothesis_statuses) {
        if (item.name === name) {
          return item.label;
        }
      }
      for (const item of table.branch_statuses) {
        if (item.name === name) {
          return item.label;
        }
      }
      for (const item of table.job_statuses) {
        if (item.name === name) {
          return item.label;
        }
      }
      for (const item of table.step_statuses) {
        if (item.name === name) {
          return item.label;
        }
      }
    }
    return name;
  }

  /** 色调也属于契约：界面不按字符串猜颜色，也不自己维护一张颜色表。 */
  private toneOf(name: string): string {
    const table: ResearchContract | null = vocabulary;
    if (table !== null) {
      for (const item of table.verdicts) {
        if (item.name === name) {
          return item.tone;
        }
      }
      for (const item of table.hypothesis_statuses) {
        if (item.name === name) {
          return item.tone;
        }
      }
      for (const item of table.branch_statuses) {
        if (item.name === name) {
          return item.tone;
        }
      }
      for (const item of table.job_statuses) {
        if (item.name === name) {
          return item.tone;
        }
      }
      for (const item of table.step_statuses) {
        if (item.name === name) {
          return item.tone;
        }
      }
    }
    return 'muted';
  }

  // ------------------------------------------------------------------ 交互

  /** 推进一步或三步。 */
  async step(maxSteps: number): Promise<void> {
    if (this.busy || this.runningJob.length > 0) {
      return;
    }
    this.busy = true;
    this.actionError = '';
    try {
      const job: ResearchLoopJob = await stepResearchLoop(maxSteps);
      this.runningJob = job.job_id;
      this.section = 'now';
      // 后端已经收了这一步，之后靠轮询看它跑到哪儿 —— 与 Windows 端同一套做法。
      this.startPolling();
    } catch (err) {
      this.actionError = (err as Error).message;
    } finally {
      this.busy = false;
    }
  }

  /** 重新把实验记录接进研究状态。幂等。 */
  async backfill(): Promise<void> {
    if (this.busy || this.runningJob.length > 0) {
      return;
    }
    this.busy = true;
    this.actionError = '';
    try {
      this.apply(await backfillResearchLoop());
    } catch (err) {
      this.actionError = (err as Error).message;
    } finally {
      this.busy = false;
    }
  }

  private startPolling(): void {
    if (pollTimer >= 0) {
      return;
    }
    pollTimer = setTimeout(() => {
      pollTimer = -1;
      this.poll();
    }, POLL_INTERVAL_MS);
  }

  private stopPolling(): void {
    if (pollTimer >= 0) {
      clearTimeout(pollTimer);
      pollTimer = -1;
    }
  }

  /** 看一次进度；作业还在跑就再排一次，跑完就停。 */
  private async poll(): Promise<void> {
    try {
      this.apply(await fetchResearchLoop());
    } catch (err) {
      this.errorText = (err as Error).message;
    }
    if (this.runningJob.length > 0) {
      this.startPolling();
    }
  }

  // ------------------------------------------------------------------ 派生文案

  /** 一行现状。空设计单独说：它们既不算"跑完没核查"，也不算在推进。 */
  private statusText(): string {
    const base: string = this.trf('loop.status', [this.hypothesisTotal.toString(),
      this.falsifiableTotal.toString(), this.experimentTotal.toString(),
      this.activeBranches.toString(), this.branchTotal.toString(), this.evidenceTotal.toString()]);
    return this.undesignableTotal > 0
      ? base + this.trf('loop.statusUndesignable', [this.undesignableTotal.toString()])
      : base;
  }

  /** 分段导航的项。色点说的是这一段通不通。 */
  private railItems(): RailItemSpec[] {
    const predicted: ResearchActionSpec | null = this.actionSpec(this.nextActionName);
    const finished: boolean = predicted !== null && predicted.terminal;
    return [
      { key: 'now', label: this.tr('loop.section.now'), tone: finished ? 'ok' : 'warn' },
      { key: 'hypotheses', label: this.tr('loop.section.hypotheses'), tone: this.falsifiableTotal > 0 ? 'ok' : 'danger' },
      { key: 'evidence', label: this.tr('loop.section.evidence'), tone: this.evidenceTotal > 0 ? 'ok' : 'muted' },
      { key: 'history', label: this.tr('loop.section.history'), tone: this.decisions.length > 0 ? 'ok' : 'muted' }
    ];
  }

  /** 这条实验是不是"跑不起来"的空设计。判据来自后端，界面不自己算。 */
  private isUndesignable(experimentId: string): boolean {
    for (const id of this.undesignableIds) {
      if (id === experimentId) {
        return true;
      }
    }
    return false;
  }

  /** 这条假设上挂着的空设计理由；没有就返回空串。 */
  private blockedReason(hypothesisId: string): string {
    for (const experiment of this.experiments) {
      if (experiment.hypothesis_id !== hypothesisId || !this.isUndesignable(experiment.experiment_id)) {
        continue;
      }
      // 更早的记录里没有留下理由（那时还没记这个字段），也要给出说法 ——
      // 否则页面上会出现"有 N 个跑不起来"却哪里都不解释的情况。
      return experiment.blocked.length > 0 ? experiment.blocked : this.tr('loop.blockedUnknown');
    }
    return '';
  }

  /** 待批准动作的中文名，用顿号连起来。 */
  private pendingText(job: ResearchLoopJob): string {
    const parts: string[] = [];
    for (const name of job.pending_approvals) {
      parts.push(this.actionLabel(name));
    }
    return parts.join('、');
  }

  /** 一行文本（列表项）。 */
  private listText(text: string): string {
    return text.length > 0 ? text : '—';
  }

  /** 核查的三态显示：true 是 / false 否 / null 未核查。 */
  private checkValueText(value: boolean | null): string {
    if (value === true) {
      return this.tr('loop.checkYes');
    }
    if (value === false) {
      return this.tr('loop.checkNo');
    }
    return this.tr('loop.checkUnknown');
  }

  private checkValueTone(value: boolean | null): string {
    if (value === true) {
      return 'ok';
    }
    if (value === false) {
      return 'danger';
    }
    return 'muted';
  }

  // ------------------------------------------------------------------ 视图

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

  /** 一个数字块：上面是大数字，下面是它是什么。 */
  @Builder
  Metric(label: string, value: string, tone: string) {
    Column() {
      Text(value)
        .fontSize(26)
        .fontWeight(FontWeight.Bold)
        .fontColor(tone === 'warn' ? AppTheme.WARN_TEXT : AppTheme.TEXT_PRIMARY)
      Text(label)
        .fontSize(12)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ top: 6 })
        .maxLines(2)
    }
    .alignItems(HorizontalAlign.Start)
    .layoutWeight(1)
    .padding({ left: 16, right: 16, top: 14, bottom: 14 })
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
  }

  /** 当前段：五个数字 + 下一步 + 操作 + 最近的推进。 */
  @Builder
  NowSection() {
    Column({ space: 20 }) {
      // 五个数字。后两个分开数：一个是欠着的活，一个是走不通的路。
      Row({ space: 12 }) {
        this.Metric(this.tr('loop.metric.hypotheses'), `${this.hypothesisTotal}`, 'ok')
        this.Metric(this.tr('loop.metric.falsifiable'), `${this.falsifiableTotal}`, 'ok')
        this.Metric(this.tr('loop.metric.experiments'), `${this.experimentTotal}`, 'ok')
        this.Metric(this.tr('loop.metric.awaiting'), `${this.awaitingEvidence}`,
          this.awaitingEvidence > 0 ? 'warn' : 'ok')
        this.Metric(this.tr('loop.metric.undesignable'), `${this.undesignableTotal}`,
          this.undesignableTotal > 0 ? 'warn' : 'ok')
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)

      CardPanel({ title: '' }) {
        Column() {
          Row() {
            Text(this.tr('overview.nextStep'))
              .fontSize(12)
              .fontColor(AppTheme.PRIMARY_DARK)
              .backgroundColor(AppTheme.PRIMARY_SOFT)
              .borderRadius(6)
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
            Text(this.actionLabel(this.nextActionName))
              .fontSize(16)
              .fontWeight(FontWeight.Bold)
              .fontColor(AppTheme.TEXT_PRIMARY)
              .margin({ left: 12 })
              .layoutWeight(1)
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)

          if (this.nextActionReason.length > 0) {
            Text(this.nextActionReason)
              .fontSize(13)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .width('100%')
              .margin({ top: 10 })
          }

          Row() {
            if (this.runningJob.length > 0) {
              // 后端已经收了这一步，正在跑。这个块是状态不是按钮，所以不给它 onClick。
              Text(this.trf('loop.stepping', [this.runningJob]))
                .fontSize(13)
                .fontColor(AppTheme.TEXT_SECONDARY)
                .backgroundColor(AppTheme.PAGE_BG)
                .borderRadius(AppTheme.RADIUS_SM)
                .padding({ left: 16, right: 16, top: 9, bottom: 9 })
                .margin({ right: 10, bottom: 8 })
            } else {
              Text(this.tr('loop.stepOne'))
                .fontSize(13)
                .fontColor(this.busy ? AppTheme.TEXT_SECONDARY : Color.White)
                .backgroundColor(this.busy ? AppTheme.PAGE_BG : AppTheme.PRIMARY)
                .borderRadius(AppTheme.RADIUS_SM)
                .padding({ left: 16, right: 16, top: 9, bottom: 9 })
                .margin({ right: 10, bottom: 8 })
                .onClick(() => {
                  this.step(1);
                })

              Text(this.tr('loop.stepThree'))
                .fontSize(13)
                .fontColor(AppTheme.TEXT_SECONDARY)
                .backgroundColor(AppTheme.PAGE_BG)
                .borderRadius(AppTheme.RADIUS_SM)
                .padding({ left: 16, right: 16, top: 9, bottom: 9 })
                .margin({ right: 10, bottom: 8 })
                .onClick(() => {
                  this.step(3);
                })
            }

            Text(this.tr('loop.backfill'))
              .fontSize(13)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .backgroundColor(AppTheme.PAGE_BG)
              .borderRadius(AppTheme.RADIUS_SM)
              .padding({ left: 16, right: 16, top: 9, bottom: 9 })
              .margin({ right: 10, bottom: 8 })
              .onClick(() => {
                this.backfill();
              })
          }
          .width('100%')
          .margin({ top: 14 })
          .alignItems(VerticalAlign.Center)

          Text(this.tr('loop.hint'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .width('100%')
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
      }

      if (this.jobs.length === 0) {
        CardPanel({ title: this.tr('loop.recent') }) {
          EmptyHint({ text: this.tr('loop.noJobs') })
        }
      } else {
        CardPanel({ title: this.tr('loop.recent') }) {
          Column({ space: 16 }) {
            ForEach(this.jobs, (job: ResearchLoopJob) => {
              this.JobBlock(job)
            }, (job: ResearchLoopJob) => `${job.job_id}-${job.status}-${job.steps.length}-${job.pending_approvals.length}-${this.lang}`)
          }
          .width('100%')
        }
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  /** 一次推进作业：头部状态 + 待批准提示 + 逐步的轨迹。 */
  @Builder
  JobBlock(job: ResearchLoopJob) {
    Column() {
      Row() {
        StatusBadge({ text: this.statusLabel(job.status), tone: this.toneOf(job.status) })
        Text(this.trf('loop.jobMax', [`${job.max_steps}`]))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ left: 10 })
          .layoutWeight(1)
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(job.job_id)
        .fontSize(11)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .width('100%')
        .margin({ top: 6 })

      if (job.stopped_because.length > 0) {
        Text(this.trf('loop.jobStopped', [job.stopped_because]))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 6 })
      }

      if (job.error.length > 0) {
        Text(job.error)
          .fontSize(12)
          .fontColor(AppTheme.DANGER)
          .width('100%')
          .margin({ top: 6 })
      }

      if (job.pending_approvals.length > 0) {
        // 它们没被执行，但也没挡住其他路线 —— 两件事都要说清楚。
        Text(this.trf('loop.pending', [this.pendingText(job)]))
          .fontSize(12)
          .fontColor(AppTheme.WARN_TEXT)
          .width('100%')
          .padding(12)
          .backgroundColor(AppTheme.WARN_SOFT)
          .borderRadius(AppTheme.RADIUS_SM)
          .margin({ top: 12 })
      }

      ForEach(job.steps, (step: ResearchLoopStep, index: number) => {
        this.StepRow(index + 1, step)
      }, (step: ResearchLoopStep) => `${step.decision.decision_id}-${step.status}`)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(16)
    .backgroundColor(AppTheme.PAGE_BG)
    .borderRadius(AppTheme.RADIUS)
  }

  /** 作业里的一步：动作 + 状态 + 详情。序号由它在数组里的位置决定，画在左边。 */
  @Builder
  StepRow(index: number, step: ResearchLoopStep) {
    Row() {
      Text(`${index}`)
        .fontSize(11)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .width(20)
        .margin({ top: 2 })

      Column() {
        Row() {
          Text(this.actionLabel(step.decision.action))
            .fontSize(13)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
          StatusBadge({ text: this.statusLabel(step.status), tone: this.toneOf(step.status) })
            .margin({ left: 8 })
          if (step.decision.target_id !== null && step.decision.target_id.length > 0) {
            Text(step.decision.target_id)
              .fontSize(11)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .margin({ left: 8 })
              .layoutWeight(1)
          }
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        if (step.detail.length > 0) {
          Text(step.detail)
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
            .margin({ top: 6 })
            .maxLines(4)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
    .padding({ top: 10, bottom: 10 })
  }

  /** 假设段：每条假设的状态、预测、反证条件与（如果有）跑不起来的理由。 */
  @Builder
  HypothesesSection() {
    CardPanel({ title: this.tr('loop.section.hypotheses') }) {
      if (this.hypotheses.length === 0) {
        EmptyHint({ text: this.tr('loop.noHypotheses') })
      } else {
        Column({ space: 16 }) {
          ForEach(this.hypotheses, (item: ResearchHypothesis) => {
            this.HypothesisBlock(item)
          }, (item: ResearchHypothesis) => `${item.hypothesis_id}-${item.status}-${item.predictions.length}-${item.falsifiers.length}-${this.lang}`)
        }
        .width('100%')
      }
    }
  }

  /** 一条假设。 */
  @Builder
  HypothesisBlock(item: ResearchHypothesis) {
    Column() {
      Row() {
        Text(item.hypothesis_id)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
        Text(item.statement)
          .fontSize(14)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
          .margin({ left: 10 })
          .maxLines(3)
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)

      Row() {
        StatusBadge({ text: this.statusLabel(item.status), tone: this.toneOf(item.status) })
        if (!item.falsifiable) {
          // 可证伪的判据由后端给出，界面不自己拿两个数组的长度去算。
          StatusBadge({ text: this.tr('loop.unfalsifiable'), tone: 'warn' })
            .margin({ left: 8 })
        }
      }
      .width('100%')
      .margin({ top: 10 })

      this.TextList(this.tr('loop.predictions'), item.predictions)
      this.TextList(this.tr('loop.falsifiers'), item.falsifiers)
      this.TextList(this.tr('loop.rationale'), item.rationale)

      if (!item.falsifiable) {
        Text(this.tr('loop.unfalsifiableHint'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width('100%')
          .margin({ top: 8 })
      }

      if (this.blockedReason(item.hypothesis_id).length > 0) {
        Text(this.trf('loop.blocked', [this.blockedReason(item.hypothesis_id)]))
          .fontSize(12)
          .fontColor(AppTheme.WARN_TEXT)
          .width('100%')
          .padding(12)
          .backgroundColor(AppTheme.WARN_SOFT)
          .borderRadius(AppTheme.RADIUS_SM)
          .margin({ top: 10 })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(16)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
  }

  /** 一个小标题 + 一串条目；没有条目就整块不画。 */
  @Builder
  TextList(title: string, items: string[]) {
    if (items.length > 0) {
      Text(title)
        .fontSize(12)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .width('100%')
        .margin({ top: 12 })
      Column({ space: 4 }) {
        ForEach(items, (line: string) => {
          Text(`· ${line}`)
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
        }, (line: string) => `${title}-${line}`)
      }
      .width('100%')
      .margin({ top: 4 })
    }
  }

  /** 证据段：每条证据的九项核查 + 判定。 */
  @Builder
  EvidenceSection() {
    CardPanel({ title: this.tr('loop.section.evidence') }) {
      if (this.evidence.length === 0) {
        EmptyHint({ text: this.tr('loop.noEvidence') })
      } else {
        Column({ space: 16 }) {
          ForEach(this.evidence, (item: ResearchEvidence) => {
            this.EvidenceBlock(item)
          }, (item: ResearchEvidence) => `${item.evidence_id}-${item.verdict}-${this.lang}`)
        }
        .width('100%')
      }
    }
  }

  /** 一条证据。 */
  @Builder
  EvidenceBlock(item: ResearchEvidence) {
    Column() {
      Row() {
        Text(item.experiment_id)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
        Text(this.verdictLabel(item.verdict))
          .fontSize(14)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
          .margin({ left: 10 })
        StatusBadge({ text: this.verdictLabel(item.verdict), tone: this.toneOf(item.verdict) })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Column({ space: 6 }) {
        ForEach(item.checks, (check: ResearchCheckValue) => {
          this.CheckRow(check)
        }, (check: ResearchCheckValue) => `${check.name}-${check.value}`)
      }
      .width('100%')
      .margin({ top: 12 })

      if (item.notes.length > 0) {
        Text(item.notes)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width('100%')
          .margin({ top: 12 })
          .maxLines(6)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }

      Text(formatTimestamp(item.recorded_at))
        .fontSize(11)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .width('100%')
        .margin({ top: 8 })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(16)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: AppTheme.BORDER })
  }

  /** 一项核查：名称来自契约，取值来自后端配好的那一对。 */
  @Builder
  CheckRow(check: ResearchCheckValue) {
    Row() {
      Text(this.checkTitle(check.name))
        .fontSize(13)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .layoutWeight(1)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      StatusBadge({
        text: this.checkValueText(check.value),
        tone: this.checkValueTone(check.value)
      })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }

  /** 决策轨迹段：每一步为什么这么走。 */
  @Builder
  HistorySection() {
    CardPanel({ title: this.tr('loop.section.history') }) {
      if (this.decisions.length === 0) {
        EmptyHint({ text: this.tr('loop.noDecisions') })
      } else {
        Column() {
          ForEach(this.decisions, (item: ResearchDecision) => {
            this.DecisionRow(item)
          }, (item: ResearchDecision) => `${item.decision_id}-${this.lang}`)
        }
        .width('100%')
      }
    }
  }

  /** 一条决策。接口只给最近 30 条，最新的在最后，所以这里倒过来铺。 */
  @Builder
  DecisionRow(item: ResearchDecision) {
    Row() {
      Column() {
        Row() {
          Text(this.actionLabel(item.action))
            .fontSize(13)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_PRIMARY)
          Text(this.listText(item.target_id === null ? '' : item.target_id))
            .fontSize(11)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ left: 10 })
            .layoutWeight(1)
        }
        .width('100%')

        if (item.reason.length > 0) {
          Text(item.reason)
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
            .margin({ top: 4 })
            .maxLines(3)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
    .padding({ top: 10, bottom: 10 })
  }

  build() {
    Column({ space: 20 }) {
      PageHeader({
        title: this.tr('nav.loop'),
        status: this.statusText(),
        onRefresh: () => {
          this.load();
        }
      })

      if (this.errorText.length > 0) {
        this.ErrorBanner()
      }

      if (this.actionError.length > 0) {
        Text(this.trf('loop.actionFailed', [this.actionError]))
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

      if (this.section === 'hypotheses') {
        this.HypothesesSection()
      } else if (this.section === 'evidence') {
        this.EvidenceSection()
      } else if (this.section === 'history') {
        this.HistorySection()
      } else {
        this.NowSection()
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
