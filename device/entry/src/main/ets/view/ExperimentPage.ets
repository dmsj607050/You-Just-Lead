import {
  approveExperiment,
  createExperimentDraft,
  DraftListResponse,
  ExperimentDraft,
  ExperimentRecord,
  ExperimentsResponse,
  fetchExperimentDrafts,
  fetchExperiments,
  fetchTrainingJobs,
  TrainingJob,
  TrainingJobsResponse
} from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import {
  experimentStatusLabel,
  experimentStatusTone,
  formatDuration,
  formatNumber,
  formatTimestamp
} from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import { CardPanel, EmptyHint, PageHeader, RailItemSpec, SectionRail, StatusBadge } from './Widgets';

/**
 * 实验页：实验账本与训练任务队列。
 *
 * 「已完成」只认账本里有 validation_metric 的记录，不显示没有落盘的中间结果。
 */
@Component
export struct ExperimentPage {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  @State loading: boolean = false;
  @State errorText: string = '';
  @State experiments: ExperimentRecord[] = [];
  @State jobs: TrainingJob[] = [];
  @State drafts: ExperimentDraft[] = [];
  @State completed: number = 0;
  @State bestMetric: string = '—';
  /**
   * 当前分段：ledger / jobs / drafts / register。
   *
   * 四张卡原先堆在一列，实验一多就要一路滑到底。现在一次只看一段，
   * 「几个实验、最佳多少」写在标题下面一行里。
   */
  @State section: string = 'ledger';
  /** 正在行内二次确认批准哪个实验；空串表示没有。 */
  @State approvingId: string = '';
  @State approving: boolean = false;
  @State approvalError: string = '';
  @State hypothesis: string = '';
  /** 登记成功的草案 ID：只存原值，提示文案在渲染时按当前语言拼。 */
  @State draftId: string = '';
  /** 假设过短的标记；提示文案在渲染时按当前语言拼。 */
  @State draftTooShort: boolean = false;
  /** 后端返回的错误原文，原样显示。 */
  @State draftError: string = '';
  @State submitting: boolean = false;

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  /** 草案表单的错误提示：过短时按当前语言生成，后端错误原文直接显示。 */
  private draftErrorText(): string {
    return this.draftTooShort ? this.trf('exp.hypothesisTooShort', ['8']) : this.draftError;
  }

  aboutToAppear(): void {
    this.load();
  }

  /**
   * 登记一条实验草案。
   *
   * 只写草案，不启动训练：这是「AI 不越权、人确认」这条线上的第一个可操作动作。
   */
  async submitDraft(): Promise<void> {
    const text: string = this.hypothesis.trim();
    if (this.submitting) {
      return;
    }
    if (text.length < 8) {
      this.draftTooShort = true;
      this.draftError = '';
      this.draftId = '';
      return;
    }
    this.submitting = true;
    this.draftTooShort = false;
    this.draftError = '';
    this.draftId = '';
    try {
      const draft: ExperimentDraft = await createExperimentDraft(text);
      this.draftId = draft.draft_id;
      this.hypothesis = '';
      await this.loadDrafts();
    } catch (err) {
      const error = err as Error;
      this.draftError = error.message;
    } finally {
      this.submitting = false;
    }
  }

  /** 只刷新草案列表；登记成功后用它把新草案立刻显示出来。 */
  private async loadDrafts(): Promise<void> {
    try {
      const draftList: DraftListResponse = await fetchExperimentDrafts();
      this.drafts = draftList.drafts;
    } catch (err) {
      const error = err as Error;
      this.draftTooShort = false;
      this.draftError = error.message;
    }
  }

  /** 记录一条人工批准：只落一条批准记录，不会启动训练。 */
  async approve(item: ExperimentRecord): Promise<void> {
    this.approvalError = '';
    this.approvingId = '';
    this.approving = true;
    try {
      await approveExperiment(item.id);
      await this.load();
    } catch (err) {
      const error = err as Error;
      this.approvalError = error.message;
    } finally {
      this.approving = false;
    }
  }

  async load(): Promise<void> {
    this.loading = true;
    this.errorText = '';
    try {
      const ledger: ExperimentsResponse = await fetchExperiments();
      const queue: TrainingJobsResponse = await fetchTrainingJobs();
      const draftList: DraftListResponse = await fetchExperimentDrafts();
      this.experiments = ledger.experiments;
      this.jobs = queue.jobs;
      this.drafts = draftList.drafts;

      let completed: number = 0;
      let best: number = Number.NEGATIVE_INFINITY;
      for (const item of ledger.experiments) {
        if (item.status === 'completed' && item.metric !== null) {
          completed++;
          if (item.metric > best) {
            best = item.metric;
          }
        }
      }
      this.completed = completed;
      this.bestMetric = best === Number.NEGATIVE_INFINITY ? '—' : best.toFixed(4);
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.loading = false;
    }
  }

  /** 一行现状：实验数 · 已完成 · 最佳指标 · 训练任务数。 */
  private statusText(): string {
    if (this.experiments.length === 0 && this.jobs.length === 0) {
      return '';
    }
    return this.trf('exp.status', [
      `${this.experiments.length}`, `${this.completed}`, this.bestMetric, `${this.jobs.length}`
    ]);
  }

  /** 分段导航的项。色点说的是这一段通不通，不是它有多少条。 */
  private railItems(): RailItemSpec[] {
    return [
      {
        key: 'ledger',
        label: this.tr('exp.section.ledger'),
        tone: this.experiments.length === 0 ? 'muted' : 'ok'
      },
      {
        key: 'jobs',
        label: this.tr('exp.section.jobs'),
        tone: this.jobs.length === 0 ? 'muted' : 'warn'
      },
      {
        key: 'drafts',
        label: this.tr('exp.section.drafts'),
        tone: this.drafts.length === 0 ? 'muted' : 'warn'
      },
      { key: 'register', label: this.tr('exp.section.register'), tone: 'muted' }
    ];
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
    .margin({ bottom: 20 })
  }

  @Builder
  ExperimentRow(item: ExperimentRecord) {
    Row() {
      Column() {
        Text(item.id)
          .fontSize(14)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
        if (item.hypothesis !== null && item.hypothesis.length > 0) {
          Text(item.hypothesis)
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 6 })
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        Text(this.trf('exp.changeType', [item.change_type !== null && item.change_type.length > 0 ? item.change_type : '—']))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 6 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      Column() {
        StatusBadge({
          text: experimentStatusLabel(this.lang, item.status),
          tone: experimentStatusTone(item.status)
        })
        Text(this.trf('exp.metric', [formatNumber(item.metric, 4)]))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .margin({ top: 8 })
        Text(this.trf('exp.runtime', [item.runtime_seconds === null ? '—' : formatDuration(this.lang, item.runtime_seconds)]))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 4 })
      }
      .alignItems(HorizontalAlign.End)

      // 人的关口：只有跑完并有指标的实验才作为候选，未完成的记录不给批准入口。
      if (item.status === 'completed') {
        Column() {
          if (item.approved) {
            Text(this.tr('exp.approved'))
              .fontSize(12)
              .fontColor(AppTheme.PRIMARY_DARK)
              .backgroundColor(AppTheme.PRIMARY_SOFT)
              .borderRadius(6)
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
            if (item.approved_at !== null) {
              Text(this.trf('exp.approvedAt', [formatTimestamp(item.approved_at)]))
                .fontSize(11)
                .fontColor(AppTheme.TEXT_TERTIARY)
                .margin({ top: 6 })
                .maxLines(1)
            }
          } else if (this.approvingId === item.id) {
            Text(this.tr('exp.approveHint'))
              .fontSize(11)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .maxLines(3)
              .textAlign(TextAlign.End)
            Row() {
              Text(this.tr('common.cancel'))
                .fontSize(13)
                .fontColor(AppTheme.TEXT_SECONDARY)
                .padding({ left: 8, right: 8, top: 4, bottom: 4 })
                .onClick(() => {
                  this.approvingId = '';
                })
              Text(this.tr('exp.approveConfirm'))
                .fontSize(13)
                .fontColor(AppTheme.DANGER)
                .padding({ left: 8, right: 2, top: 4, bottom: 4 })
                .onClick(() => {
                  this.approve(item);
                })
            }
            .margin({ top: 8 })
            .alignItems(VerticalAlign.Center)
          } else {
            Text(this.tr('exp.approveAction'))
              .fontSize(13)
              .fontColor(AppTheme.PRIMARY)
              .padding({ left: 8, right: 2, top: 4, bottom: 4 })
              .onClick(() => {
                this.approvingId = item.id;
              })
          }
        }
        .alignItems(HorizontalAlign.End)
        .width(150)
        .margin({ left: 16 })
      }
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
    .padding({ top: 14, bottom: 14 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  @Builder
  JobRow(item: TrainingJob) {
    Column() {
      Row() {
        Text(item.job_id)
          .fontSize(14)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
        StatusBadge({
          text: experimentStatusLabel(this.lang, item.status),
          tone: experimentStatusTone(item.status)
        })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(item.config_path)
        .fontSize(12)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .margin({ top: 8 })
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })

      Row() {
        Text(this.trf('exp.submittedAt', [formatTimestamp(item.created_at)]))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
        Text(this.trf('exp.metric', [formatNumber(item.validation_metric, 4)]))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ left: 16 })
      }
      .margin({ top: 8 })

      if (item.error !== null && item.error.length > 0) {
        Text(item.error)
          .fontSize(12)
          .fontColor(AppTheme.DANGER)
          .margin({ top: 8 })
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 14, bottom: 14 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  /** 一条待批准草案。 */
  @Builder
  DraftRow(item: ExperimentDraft) {
    Column() {
      Row() {
        Text(item.draft_id)
          .fontSize(14)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
        StatusBadge({
          text: experimentStatusLabel(this.lang, item.status),
          tone: experimentStatusTone(item.status)
        })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(item.hypothesis)
        .fontSize(13)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ top: 8 })
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })

      Text(this.trf('exp.registeredAt', [formatTimestamp(item.created_at)]))
        .fontSize(12)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .margin({ top: 6 })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 14, bottom: 14 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  /** 草案表单：一个假设输入框 + 提交按钮 + 成功/失败提示。 */
  @Builder
  DraftPanel() {
    Column() {
      TextInput({
        text: this.hypothesis,
        placeholder: this.tr('exp.hypothesisPlaceholder')
      })
        .width('100%')
        .height(40)
        .fontSize(14)
        .backgroundColor(AppTheme.PAGE_BG)
        .onChange((value: string) => {
          this.hypothesis = value;
        })

      Row() {
        Text(this.tr('exp.draftHint'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .layoutWeight(1)
        Button(this.tr('exp.registerDraft'))
          .height(36)
          .fontSize(14)
          .fontColor(Color.White)
          .backgroundColor(AppTheme.PRIMARY)
          .enabled(!this.submitting)
          .onClick(() => {
            this.submitDraft();
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 12 })

      if (this.draftTooShort || this.draftError.length > 0) {
        Text(this.draftErrorText())
          .fontSize(12)
          .fontColor(AppTheme.DANGER)
          .width('100%')
          .margin({ top: 12 })
      }
      if (this.draftId.length > 0) {
        Text(this.trf('exp.draftSubmitted', [this.draftId]))
          .fontSize(12)
          .fontColor(AppTheme.PRIMARY_DARK)
          .width('100%')
          .padding(12)
          .backgroundColor(AppTheme.PRIMARY_SOFT)
          .borderRadius(AppTheme.RADIUS_SM)
          .margin({ top: 12 })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  build() {
    Column({ space: 20 }) {
      PageHeader({
        title: this.tr('nav.experiment'),
        subtitle: this.tr('exp.subtitle'),
        status: this.statusText(),
        onRefresh: () => {
          this.load();
        }
      })

      if (this.errorText.length > 0) {
        this.ErrorBanner()
      }

      SectionRail({
        items: this.railItems(),
        active: this.section,
        onSelect: (key: string) => {
          this.section = key;
        }
      })

      if (this.section === 'jobs') {
        CardPanel({
          title: this.tr('exp.trainingJobs'),
          subtitle: this.tr('exp.jobsSubtitle')
        }) {
          if (this.jobs.length === 0) {
            EmptyHint({ text: this.tr('exp.jobsEmpty') })
          } else {
            Column() {
              ForEach(this.jobs, (item: TrainingJob) => {
                this.JobRow(item)
              }, (item: TrainingJob) => item.job_id)
            }
            .width('100%')
          }
        }
      } else if (this.section === 'drafts') {
        CardPanel({
          title: this.tr('exp.draftsTitle'),
          subtitle: this.tr('exp.draftsSubtitle')
        }) {
          if (this.drafts.length === 0) {
            EmptyHint({ text: this.tr('exp.draftsEmpty') })
          } else {
            Column() {
              ForEach(this.drafts, (item: ExperimentDraft) => {
                this.DraftRow(item)
              }, (item: ExperimentDraft) => `${item.draft_id}-${item.status}`)
            }
            .width('100%')
          }
        }
      } else if (this.section === 'register') {
        CardPanel({
          title: this.tr('exp.registerTitle'),
          subtitle: this.tr('exp.registerSubtitle')
        }) {
          this.DraftPanel()
        }
      } else {
        CardPanel({
          title: this.tr('exp.ledgerTitle'),
          subtitle: this.tr('exp.ledgerSubtitle')
        }) {
          if (this.approvalError.length > 0) {
            Text(this.approvalError)
              .fontSize(12)
              .fontColor(AppTheme.DANGER)
              .margin({ bottom: 12 })
          }
          if (this.experiments.length === 0) {
            EmptyHint({ text: this.tr('exp.ledgerEmpty') })
          } else {
            Column() {
              ForEach(this.experiments, (item: ExperimentRecord) => {
                this.ExperimentRow(item)
              }, (item: ExperimentRecord) => `${item.id}-${item.approved}`)
            }
            .width('100%')
          }
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
