import {
  DeepSeekSettings,
  fetchDeepSeekSettings,
  fetchHealth,
  fetchRuntime,
  GpuDevice,
  HealthInfo,
  RuntimeSnapshot
} from '../common/BackendClient';
import { ACCESS_TOKEN, BASE_URL } from '../common/BackendConfig';
import AppTheme from '../common/AppTheme';
import { tFor, tfFor } from '../common/I18n';
import { CardPanel, EmptyHint, KeyValueRow, PageHeader, StatTileGrid } from './Widgets';
import { LocalWorkspaceCard } from './LocalWorkspaceCard';

/** 显存容量转成 GB 描述。 */
function memoryGb(mb: number): string {
  return `${(mb / 1024).toFixed(1)} GB`;
}

/**
 * 设置页：连接、模型与运行环境。
 *
 * 地址与令牌仍然是构建期常量，这里只做展示，改配置请改 BackendConfig。
 */
@Component
export struct SettingsPage {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  @State loading: boolean = false;
  @State errorText: string = '';
  @State health: HealthInfo | null = null;
  @State settings: DeepSeekSettings | null = null;
  @State runtime: RuntimeSnapshot | null = null;

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
      this.health = await fetchHealth();
      this.settings = await fetchDeepSeekSettings();
      this.runtime = await fetchRuntime();
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.loading = false;
    }
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
  GpuRow(item: GpuDevice) {
    Column() {
      Text(item.name)
        .fontSize(13)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Text(this.trf('settings.gpuMemory', [
        memoryGb(item.memory_free_mb),
        memoryGb(item.memory_total_mb),
        item.driver_version
      ]))
        .fontSize(12)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .margin({ top: 6 })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12, bottom: 12 })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  build() {
    Column({ space: 20 }) {
      PageHeader({
        title: this.tr('nav.settings'),
        subtitle: this.tr('settings.subtitle'),
        onRefresh: () => {
          this.load();
        }
      })

      if (this.errorText.length > 0) {
        this.ErrorBanner()
      }

      LocalWorkspaceCard()

      StatTileGrid({
        items: [
          {
            label: this.tr('settings.connectionStatus'),
            value: this.health === null ? this.tr('settings.notConnected') : this.tr('menu.backendOk'),
            hint: BASE_URL
          },
          {
            label: this.tr('settings.model'),
            value: this.settings === null ? '—' : this.settings.model,
            hint: this.settings === null ? '' : this.trf('settings.keySourceHint', [this.settings.key_source])
          },
          {
            label: 'GPU',
            value: this.runtime === null
              ? '—'
              : (this.runtime.gpu_available
                ? this.trf('settings.gpuCount', [`${this.runtime.gpus.length}`])
                : this.tr('settings.unavailable')),
            hint: this.tr('settings.gpuHint')
          },
          {
            label: 'Conda',
            value: this.runtime === null
              ? '—'
              : (this.runtime.conda_available ? this.tr('settings.available') : this.tr('settings.unavailable')),
            hint: this.tr('settings.condaHint')
          }
        ]
      })

      CardPanel({
        title: this.tr('menu.backend'),
        subtitle: this.tr('settings.backendSubtitle')
      }) {
        Column() {
          KeyValueRow({ label: this.tr('settings.serviceAddress'), value: BASE_URL, mono: true })
          KeyValueRow({
            label: this.tr('settings.sharedToken'),
            value: ACCESS_TOKEN.length > 0 ? this.tr('settings.configured') : this.tr('settings.tokenNotConfigured')
          })
          KeyValueRow({
            label: this.tr('settings.health'),
            value: this.health === null ? '—' : this.health.status
          })
          KeyValueRow({
            label: this.tr('settings.workspace'),
            value: this.health === null ? '—' : this.health.workspace,
            mono: true
          })
        }
        .width('100%')
      }

      CardPanel({
        title: this.tr('settings.modelSettings'),
        subtitle: this.tr('settings.modelSubtitle')
      }) {
        Column() {
          KeyValueRow({
            label: this.tr('settings.isConfigured'),
            value: this.settings === null
              ? '—'
              : (this.settings.configured ? this.tr('settings.configured') : this.tr('settings.notConfigured'))
          })
          KeyValueRow({
            label: this.tr('settings.keySource'),
            value: this.settings === null ? '—' : this.settings.key_source
          })
          KeyValueRow({
            label: this.tr('settings.secureStorage'),
            value: this.settings === null
              ? '—'
              : (this.settings.secure_storage_available ? this.tr('settings.available') : this.tr('settings.unavailable'))
          })
          Text(this.tr('settings.supportedModels'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .margin({ top: 12, bottom: 10 })
          Row() {
            ForEach(this.settings === null ? [] : this.settings.supported_models, (model: string) => {
              Text(model)
                .fontSize(12)
                .fontColor(model === (this.settings === null ? '' : this.settings.model)
                  ? AppTheme.PRIMARY_DARK
                  : AppTheme.TEXT_SECONDARY)
                .backgroundColor(model === (this.settings === null ? '' : this.settings.model)
                  ? AppTheme.PRIMARY_SOFT
                  : AppTheme.PAGE_BG)
                .borderRadius(6)
                .padding({ left: 10, right: 10, top: 4, bottom: 4 })
                .margin({ right: 8 })
            }, (model: string) => model)
          }
          .width('100%')
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }

      CardPanel({
        title: this.tr('settings.runtime'),
        subtitle: this.tr('settings.runtimeSubtitle')
      }) {
        Column() {
          KeyValueRow({
            label: this.tr('settings.platform'),
            value: this.runtime === null ? '—' : this.runtime.platform
          })
          KeyValueRow({
            label: 'Python',
            value: this.runtime === null ? '—' : this.runtime.python
          })
          if (this.runtime === null || this.runtime.gpus.length === 0) {
            EmptyHint({ text: this.tr('settings.noGpu') })
          } else {
            ForEach(this.runtime.gpus, (item: GpuDevice) => {
              this.GpuRow(item)
            }, (item: GpuDevice) => item.name)
          }
        }
        .width('100%')
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
