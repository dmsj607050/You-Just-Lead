import { common } from '@kit.AbilityKit';
import AppTheme from '../common/AppTheme';
import {
  describeError,
  eventTitle,
  experimentStatusLabel,
  experimentStatusTone,
  formatBytes,
  formatNumber,
  formatTimestamp,
  shortHash
} from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import { LedgerEvent } from '../common/LocalLedger';
import {
  DatasetStatus,
  EvidenceStatus,
  ExperimentStatus,
  OfflineStatus,
  readOfflineStatus
} from '../common/LocalStatus';
import { LocalWorkspace } from '../common/LocalWorkspace';
import { CardPanel, EmptyHint, KeyValueRow, StatusBadge } from './Widgets';

/**
 * 端侧离线状态（整页）。
 *
 * 这一页回答的是「后端断了还能看到什么」。能读的（数据审计、实验历史、账本、论文证据）
 * 全部从工作区文件读出来，一个字都不经过 HTTP；不能做的（检索、大模型、训练、重型审计）
 * 明说「需要外部执行器」，而不是让用户盯着一句「连接失败」猜哪个按钮坏了。
 */

/** 账本最多列多少条：账本是流水，全量铺开会把后面的卡片推到十几屏之外。 */
const LEDGER_LIMIT: number = 12;

/** 「需要外部执行器」的能力项。只存 i18n 键名，模块常量里不能调 t()。 */
interface ExecutorCapability {
  key: string;
  titleKey: string;
}

const EXECUTOR_CAPABILITIES: ExecutorCapability[] = [
  { key: 'search', titleKey: 'localStatus.capSearch' },
  { key: 'llm', titleKey: 'localStatus.capLlm' },
  { key: 'training', titleKey: 'localStatus.capTraining' },
  { key: 'audit', titleKey: 'localStatus.capAudit' }
];

function emptyDataset(): DatasetStatus {
  return {
    present: false,
    fileCount: 0,
    issueCount: 0,
    imageCount: 0,
    maskCount: 0,
    totalBytes: 0,
    fingerprint: '',
    generatedAt: ''
  };
}

function emptyEvidence(): EvidenceStatus {
  return { present: false, claimCount: 0, researchRecords: 0, generatedAt: '' };
}

@Component
export struct LocalStatusPage {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  /** 返回上一屏。 */
  onBack: () => void = () => {
  };

  @State workspaceRoot: string = '';
  @State ready: boolean = false;
  @State dataset: DatasetStatus = emptyDataset();
  @State experiments: ExperimentStatus[] = [];
  @State events: LedgerEvent[] = [];
  @State eventTotal: number = 0;
  @State evidence: EvidenceStatus = emptyEvidence();
  @State errorText: string = '';
  @State busy: boolean = false;

  aboutToAppear(): void {
    this.reload();
  }

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  private abilityContext(): common.UIAbilityContext {
    return this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  private async reload(): Promise<void> {
    this.errorText = '';
    this.busy = true;
    try {
      const workspace: LocalWorkspace = await LocalWorkspace.restore(this.abilityContext());
      this.workspaceRoot = workspace.root;
      this.ready = workspace.hasRoot() && workspace.readable;
      if (!this.ready) {
        return;
      }
      const status: OfflineStatus = readOfflineStatus(workspace, LEDGER_LIMIT);
      this.dataset = status.dataset;
      this.experiments = status.experiments;
      this.events = status.events;
      this.eventTotal = status.eventTotal;
      this.evidence = status.evidence;
    } catch (err) {
      this.errorText = describeError(err as Object);
    } finally {
      this.busy = false;
    }
  }

  /** 顶部：返回 + 标题 + 工作区路径。 */
  @Builder
  Header() {
    Column() {
      Row() {
        Text(`← ${this.tr('localStatus.back')}`)
          .fontSize(13)
          .fontColor(AppTheme.PRIMARY)
          .padding({ right: 12, top: 4, bottom: 4 })
          .onClick(() => {
            this.onBack();
          })
        Blank()
        Text(this.tr('common.refresh'))
          .fontSize(13)
          .fontColor(this.busy ? AppTheme.TEXT_TERTIARY : AppTheme.PRIMARY)
          .padding({ left: 12, right: 12, top: 6, bottom: 6 })
          .enabled(!this.busy)
          .onClick(() => {
            this.reload();
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(this.tr('localStatus.title'))
        .fontSize(24)
        .fontWeight(FontWeight.Bold)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .margin({ top: 10 })
      Text(this.tr('localStatus.subtitle'))
        .fontSize(13)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ top: 8 })

      if (this.workspaceRoot.length > 0) {
        Text(this.workspaceRoot)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 6 })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  /** 一条实验：编号 + 状态，下面几个字段。 */
  @Builder
  ExperimentLine(item: ExperimentStatus) {
    Column() {
      Row() {
        Text(item.experimentId)
          .fontSize(13)
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

      if (item.hypothesis.length > 0) {
        Text(item.hypothesis)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 6 })
      }

      KeyValueRow({ label: this.tr('localStatus.experimentMetric'), value: formatNumber(item.validationMetric, 4) })
      KeyValueRow({ label: this.tr('localStatus.experimentData'), value: item.dataVersion })
      KeyValueRow({ label: this.tr('localStatus.experimentChange'), value: item.changeType })

      if (!item.resultPresent) {
        Text(this.tr('localStatus.experimentNoResult'))
          .fontSize(12)
          .fontColor(AppTheme.WARN_TEXT)
          .width('100%')
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 10, bottom: 10 })
    .border({ width: { top: 1 }, color: AppTheme.BORDER })
  }

  @Builder
  DatasetCard() {
    CardPanel({
      title: this.tr('localStatus.dataset'),
      subtitle: this.tr('localStatus.datasetHint')
    }) {
      if (!this.dataset.present) {
        EmptyHint({ text: this.tr('localStatus.datasetMissing') })
      } else {
        KeyValueRow({ label: this.tr('localStatus.datasetFiles'), value: `${this.dataset.fileCount}` })
        KeyValueRow({ label: this.tr('localStatus.datasetIssues'), value: `${this.dataset.issueCount}` })
        KeyValueRow({ label: this.tr('localStatus.datasetImages'), value: `${this.dataset.imageCount}` })
        KeyValueRow({ label: this.tr('localStatus.datasetMasks'), value: `${this.dataset.maskCount}` })
        KeyValueRow({
          label: this.tr('localStatus.datasetFingerprint'),
          value: shortHash(this.dataset.fingerprint),
          mono: true
        })
        KeyValueRow({
          label: this.tr('localStatus.generatedAt'),
          value: formatTimestamp(this.dataset.generatedAt)
        })
        KeyValueRow({
          label: this.tr('localStatus.datasetBytes'),
          value: formatBytes(this.dataset.totalBytes)
        })
      }
    }
  }

  @Builder
  ExperimentsCard() {
    CardPanel({
      title: this.tr('localStatus.experiments'),
      subtitle: this.tr('localStatus.experimentsHint')
    }) {
      if (this.experiments.length === 0) {
        EmptyHint({ text: this.tr('localStatus.experimentsNone') })
      } else {
        ForEach(this.experiments, (item: ExperimentStatus) => {
          this.ExperimentLine(item)
        }, (item: ExperimentStatus) => `${item.experimentId}-${item.status}-${item.resultPresent}`)
      }
    }
  }

  @Builder
  LedgerCard() {
    CardPanel({
      title: this.tr('localStatus.ledger'),
      subtitle: this.eventTotal > this.events.length
        ? this.trf('localStatus.ledgerLatest', [`${this.events.length}`, `${this.eventTotal}`])
        : this.tr('localStatus.ledgerHint')
    }) {
      if (this.events.length === 0) {
        EmptyHint({ text: this.tr('localStatus.ledgerNone') })
      } else {
        ForEach(this.events, (item: LedgerEvent) => {
          Row() {
            Text(eventTitle(this.lang, item.eventType))
              .fontSize(13)
              .fontColor(AppTheme.TEXT_PRIMARY)
              .layoutWeight(1)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            Text(formatTimestamp(item.createdAt))
              .fontSize(12)
              .fontColor(AppTheme.TEXT_TERTIARY)
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)
          .padding({ top: 9, bottom: 9 })
        }, (item: LedgerEvent) => `${item.eventType}-${item.createdAt}`)
      }
    }
  }

  @Builder
  EvidenceCard() {
    CardPanel({
      title: this.tr('localStatus.evidence'),
      subtitle: this.tr('localStatus.evidenceHint')
    }) {
      if (!this.evidence.present) {
        EmptyHint({ text: this.tr('localStatus.evidenceNone') })
      } else {
        KeyValueRow({
          label: this.tr('localStatus.evidenceClaims'),
          value: `${this.evidence.claimCount}`
        })
        KeyValueRow({
          label: this.tr('localStatus.evidenceRecords'),
          value: `${this.evidence.researchRecords}`
        })
        KeyValueRow({
          label: this.tr('localStatus.generatedAt'),
          value: formatTimestamp(this.evidence.generatedAt)
        })
      }
    }
  }

  @Builder
  ExecutorCard() {
    CardPanel({
      title: this.tr('localStatus.executorTitle'),
      subtitle: this.tr('localStatus.executorHint')
    }) {
      ForEach(EXECUTOR_CAPABILITIES, (item: ExecutorCapability) => {
        Row() {
          Text(this.tr(item.titleKey))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .layoutWeight(1)
          StatusBadge({ text: this.tr('localStatus.executorBadge'), tone: 'warn' })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .padding({ top: 9, bottom: 9 })
      }, (item: ExecutorCapability) => item.key)
    }
  }

  build() {
    // 卡片用父容器的间距排版：CardPanel 带尾随闭包时不能再链 `.margin()`。
    Column({ space: 18 }) {
      this.Header()

      if (this.errorText.length > 0) {
        Text(this.errorText)
          .fontSize(12)
          .fontColor(AppTheme.DANGER)
          .width('100%')
      }

      if (this.workspaceRoot.length === 0) {
        CardPanel({
          title: this.tr('localStatus.title'),
          subtitle: this.tr('localStatus.noWorkspace')
        }) {
          Text(this.tr('localStatus.noWorkspaceHint'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .width('100%')
        }
      } else {
        this.DatasetCard()
        this.ExperimentsCard()
        this.LedgerCard()
        this.EvidenceCard()
        this.ExecutorCard()
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }
}
