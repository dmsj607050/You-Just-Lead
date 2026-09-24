import { fetchPaper, PaperClaim, PaperPackage } from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import { formatTimestamp } from '../common/Format';
import { tFor, tfFor } from '../common/I18n';
import { CardPanel, EmptyHint, KeyValueRow, PageHeader, RailItemSpec, SectionRail } from './Widgets';

/**
 * 写作页：论文证据包与投稿契约。
 *
 * 论文只写有证据支撑的内容，因此这里展示的是证据链，而不是成稿正文。
 */
@Component
export struct WritingPage {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  @State loading: boolean = false;
  @State errorText: string = '';
  @State pkg: PaperPackage | null = null;
  /**
   * 当前分段：package / structure / contract。
   *
   * 原先证据包、章节结构、证据链、提交合约四张卡加一排统计块堆在一列。
   * 现在一次只看一段，「几条声明、几个章节」写在标题下面一行里。
   */
  @State section: string = 'package';

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
      this.pkg = await fetchPaper();
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.loading = false;
    }
  }

  /** 一行现状：声明数 · 章节数 · 参考文献数 · 文献记录数。 */
  private statusText(): string {
    if (this.pkg === null) {
      return '';
    }
    return this.trf('writing.status', [
      `${this.pkg.claims.length}`,
      `${this.pkg.sections.length}`,
      `${this.pkg.bib_entries}`,
      `${this.pkg.research_records}`
    ]);
  }

  /** 分段导航的项。色点说的是这一段通不通，不是它有多少条。 */
  private railItems(): RailItemSpec[] {
    const ready: boolean = this.pkg !== null && this.pkg.available;
    return [
      { key: 'package', label: this.tr('writing.section.package'), tone: ready ? 'ok' : 'muted' },
      {
        key: 'structure',
        label: this.tr('writing.section.structure'),
        tone: ready && this.pkg !== null && this.pkg.claims.length > 0 ? 'ok' : 'muted'
      },
      { key: 'contract', label: this.tr('writing.section.contract'), tone: 'muted' }
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
  SectionList() {
    Column() {
      ForEach(this.pkg === null ? [] : this.pkg.sections, (title: string, index: number) => {
        Row() {
          Text(`${index + 1}`)
            .fontSize(12)
            .fontColor(AppTheme.PRIMARY_DARK)
            .backgroundColor(AppTheme.PRIMARY_SOFT)
            .borderRadius(11)
            .width(22)
            .height(22)
            .textAlign(TextAlign.Center)
          Text(title)
            .fontSize(13)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .layoutWeight(1)
            .margin({ left: 12 })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .padding({ top: 10, bottom: 10 })
        .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
      }, (title: string, index: number) => `${index}-${title}`)
    }
    .width('100%')
  }

  @Builder
  ClaimList() {
    Column() {
      ForEach(this.pkg === null ? [] : this.pkg.claims, (claim: PaperClaim) => {
        Column() {
          Text(claim.claim)
            .fontSize(13)
            .fontColor(AppTheme.TEXT_PRIMARY)
            .width('100%')
          Text(`${claim.experiment_id} · ${claim.result_path}`)
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 6 })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .padding({ top: 12, bottom: 12 })
        .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
      }, (claim: PaperClaim) => claim.claim)
    }
    .width('100%')
  }

  @Builder
  RequiredFiles() {
    Row() {
      ForEach(this.pkg === null ? [] : this.pkg.submission.required_files, (file: string) => {
        Text(file)
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .backgroundColor(AppTheme.PAGE_BG)
          .borderRadius(6)
          .padding({ left: 10, right: 10, top: 4, bottom: 4 })
          .margin({ right: 8 })
      }, (file: string) => file)
    }
    .width('100%')
  }

  build() {
    Column({ space: 20 }) {
      PageHeader({
        title: this.tr('nav.writing'),
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

      if (this.section === 'structure') {
        Row({ space: 20 }) {
          CardPanel({
            title: this.tr('writing.sectionStructure'),
            weight: 1
          }) {
            if (this.pkg === null || this.pkg.sections.length === 0) {
              EmptyHint({ text: this.tr('writing.noSections') })
            } else {
              this.SectionList()
            }
          }

          CardPanel({
            title: this.tr('writing.evidenceChain'),
            weight: 1
          }) {
            if (this.pkg === null || this.pkg.claims.length === 0) {
              EmptyHint({ text: this.tr('writing.noClaims') })
            } else {
              this.ClaimList()
            }
          }
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
      } else if (this.section === 'contract') {
        CardPanel({
          title: this.tr('writing.submissionContract')
        }) {
          Column() {
            KeyValueRow({
              label: this.tr('writing.submissionFormat'),
              value: this.pkg === null || this.pkg.submission.format === null
                ? '—'
                : this.pkg.submission.format
            })
            KeyValueRow({
              label: this.tr('writing.filenameRule'),
              value: this.pkg === null || this.pkg.submission.filename_rule === null
                ? '—'
                : this.pkg.submission.filename_rule
            })
            KeyValueRow({
              label: this.tr('writing.maskSize'),
              value: this.pkg === null || this.pkg.submission.mask_size.length === 0
                ? '—'
                : this.pkg.submission.mask_size.join(' × ')
            })
            KeyValueRow({
              label: this.tr('writing.dailyLimit'),
              value: this.pkg === null || this.pkg.submission.daily_limit === null
                ? '—'
                : this.trf('writing.dailyLimitValue', [`${this.pkg.submission.daily_limit}`])
            })
            KeyValueRow({
              label: this.tr('writing.validationProfile'),
              value: this.pkg === null || this.pkg.submission.validation_profile === null
                ? '—'
                : this.pkg.submission.validation_profile
            })
            Text(this.tr('writing.requiredFiles'))
              .fontSize(13)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .margin({ top: 12, bottom: 10 })
            if (this.pkg === null || this.pkg.submission.required_files.length === 0) {
              EmptyHint({ text: this.tr('writing.noRequiredFiles') })
            } else {
              this.RequiredFiles()
            }
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
      } else {
        CardPanel({
          title: this.tr('writing.paperPackage')
        }) {
          if (this.pkg === null || !this.pkg.available) {
            EmptyHint({ text: this.tr('writing.noPackage') })
          } else {
            Column() {
              KeyValueRow({
                label: this.tr('writing.generatedAt'),
                value: formatTimestamp(this.pkg.generated_at)
              })
              KeyValueRow({ label: this.tr('writing.packageDir'), value: this.pkg.package_dir, mono: true })
              KeyValueRow({
                label: this.tr('writing.texFile'),
                value: this.pkg.tex_path === null ? '—' : this.pkg.tex_path,
                mono: true
              })
              KeyValueRow({
                label: this.tr('writing.bibFile'),
                value: this.pkg.bib_path === null ? '—' : this.pkg.bib_path,
                mono: true
              })
              KeyValueRow({
                label: this.tr('writing.evidenceFile'),
                value: this.pkg.evidence_path === null ? '—' : this.pkg.evidence_path,
                mono: true
              })
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
