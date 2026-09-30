import {
  deleteProvider,
  fetchHealth,
  fetchProviders,
  fetchRuntime,
  GpuDevice,
  HealthInfo,
  ModelProvider,
  ModelProviderPreset,
  ProviderSettings,
  ProviderTestResult,
  RuntimeSnapshot,
  saveProvider,
  setActiveProvider,
  testProvider
} from '../common/BackendClient';
import { ACCESS_TOKEN, BASE_URL } from '../common/BackendConfig';
import AppTheme from '../common/AppTheme';
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
import { LocalWorkspaceCard } from './LocalWorkspaceCard';

/** 显存容量转成 GB 描述。 */
function memoryGb(mb: number): string {
  return `${(mb / 1024).toFixed(1)} GB`;
}

/**
 * 设置页：连接、模型与运行环境。
 *
 * 「模型」这一段是**可改的**：可以存几套来源（DeepSeek / OpenAI / Kimi / 百炼 / 本地 Ollama /
 * 自定义），随时切一套当「当前使用」，也可以逐套测连接。密钥只往系统凭据管理器里写，
 * 端侧界面既不显示也不会把它读回来 —— 编辑时密钥框留空就是「不改已存的那把」。
 *
 * 后端地址与令牌仍然是构建期常量，这里只做展示，改配置请改 BackendConfig。
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
  @State providers: ProviderSettings | null = null;
  @State runtime: RuntimeSnapshot | null = null;
  /**
   * 当前分段：workspace / backend / model / runtime。
   *
   * 设置页原先也是「一排统计块 + 三张卡堆一列」。现在一次只看一段，
   * 「连没连上、模型是什么、有没有 GPU」写在标题下面一行里。
   */
  @State section: string = 'workspace';

  /** 正在编辑的来源 id；空串＝没在编辑，`new`＝新增。 */
  @State providerEditId: string = '';
  @State formPreset: string = 'custom';
  @State formName: string = '';
  @State formBaseUrl: string = '';
  @State formModel: string = '';
  /** 密钥框永远从空开始；提交时留空表示不改已存的那把。 */
  @State formApiKey: string = '';
  /** 等用户确认删除的来源 id；空串＝没有待确认的删除。 */
  @State pendingDelete: string = '';
  @State providerBusy: boolean = false;
  @State providerMessage: string = '';
  /** ok / danger / 空串（普通提示）。 */
  @State providerMessageTone: string = '';

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
      this.providers = await fetchProviders();
      this.runtime = await fetchRuntime();
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.loading = false;
    }
  }

  /** 一行现状：后端连接 · 模型 · GPU · Conda。 */
  private statusText(): string {
    const connected: string = this.health === null ? this.tr('settings.notConnected') : this.tr('menu.backendOk');
    const model: string = this.providers === null || this.providers.model.length === 0
      ? '—'
      : this.providers.model;
    const gpu: string = this.runtime === null
      ? '—'
      : (this.runtime.gpu_available
        ? this.trf('settings.gpuCount', [`${this.runtime.gpus.length}`])
        : this.tr('settings.unavailable'));
    const conda: string = this.runtime === null
      ? '—'
      : (this.runtime.conda_available ? this.tr('settings.available') : this.tr('settings.unavailable'));
    return this.trf('settings.status', [connected, model, gpu, conda]);
  }

  /** 分段导航的项。色点说的是这一段通不通，不是它有多少条。 */
  private railItems(): RailItemSpec[] {
    const modelConfigured: boolean = this.providers !== null && this.providers.configured;
    return [
      { key: 'workspace', label: this.tr('settings.section.workspace'), tone: 'muted' },
      { key: 'backend', label: this.tr('settings.section.backend'), tone: this.health === null ? 'warn' : 'ok' },
      { key: 'model', label: this.tr('settings.section.model'), tone: modelConfigured ? 'ok' : 'warn' },
      {
        key: 'runtime',
        label: this.tr('settings.section.runtime'),
        tone: this.runtime === null ? 'muted' : (this.runtime.gpu_available ? 'ok' : 'warn')
      }
    ];
  }

  /** 当前使用的那套；一套都没有时返回 null。 */
  private currentProvider(): ModelProvider | null {
    const settings: ProviderSettings | null = this.providers;
    if (settings === null) {
      return null;
    }
    const found: ModelProvider | undefined = settings.providers.find(
      (item: ModelProvider) => item.id === settings.active);
    return found === undefined ? null : found;
  }

  /** 当前这套的名字；没有就给一个占位。 */
  private currentNameText(): string {
    const current: ModelProvider | null = this.currentProvider();
    return current === null ? '—' : current.name;
  }

  /** 当前这套的密钥从哪来，只说到「环境变量 / 凭据库」，不回密钥本身。 */
  private keySourceText(): string {
    const settings: ProviderSettings | null = this.providers;
    if (settings === null || settings.key_source === null || settings.key_source.length === 0) {
      return this.tr('settings.keySourceNone');
    }
    return settings.key_source === 'environment'
      ? this.tr('settings.keySourceEnv')
      : this.tr('settings.keySourceStore');
  }

  /** 密钥框的提示语：新增时是「粘贴」，编辑时是「留空＝不改」。 */
  private apiKeyHint(): string {
    return this.providerEditId === 'new' ? this.tr('settings.fieldApiKeyHintNew') : this.tr('settings.fieldApiKeyHintKeep');
  }

  /** 预设选择块。清单来自后端，界面不自己抄一份。 */
  private presetChoices(): ChoiceSpec[] {
    const settings: ProviderSettings | null = this.providers;
    if (settings === null) {
      return [];
    }
    return settings.presets.map((preset: ModelProviderPreset) => {
      const spec: ChoiceSpec = {
        key: preset.id,
        label: preset.name,
        tone: preset.id === this.formPreset ? 'ok' : 'muted'
      };
      return spec;
    });
  }

  private setMessage(tone: string, text: string): void {
    this.providerMessageTone = tone;
    this.providerMessage = text;
  }

  /**
   * 「模型来源」那一段的重建钥匙。
   *
   * ArkUI 不会因为 `@Builder` 里读到的状态变了就重建那棵子树 —— 本页实测：条件为 true
   * 时表单与提示行也不出现，而同一个状态在 `ForEach` 的 key 里就能触发重建。
   * 工程里已在用这个办法（见 `ReproductionPage.PlanBlock` 的注释），这里照做。
   *
   * 键里只放**结构性**的状态：编辑目标、预设、待确认的删除、提示、当前来源、来源条数、
   * 忙闲、语言。**不放输入框里的草稿** —— 那会让每敲一个字都重建一次，光标会丢。
   */
  private modelKeys(): string[] {
    const settings: ProviderSettings | null = this.providers;
    const active: string = settings === null ? 'none' : settings.active;
    const count: string = settings === null ? 'none' : `${settings.providers.length}`;
    const parts: string[] = [
      this.providerEditId, this.formPreset, this.pendingDelete,
      this.providerMessage, this.providerMessageTone,
      active, count, `${this.providerBusy}`, this.lang
    ];
    return [parts.join('|')];
  }

  /** 用预设预填表单。「自定义」只切预设，不动已经填好的内容。 */
  private applyPreset(key: string): void {
    this.formPreset = key;
    const settings: ProviderSettings | null = this.providers;
    if (settings === null || key === 'custom') {
      return;
    }
    const preset: ModelProviderPreset | undefined = settings.presets.find(
      (item: ModelProviderPreset) => item.id === key);
    if (preset === undefined) {
      return;
    }
    this.formName = preset.name;
    this.formBaseUrl = preset.base_url;
  }

  private openNew(): void {
    this.providerEditId = 'new';
    this.formName = '';
    this.formBaseUrl = '';
    this.formModel = '';
    this.formApiKey = '';
    this.pendingDelete = '';
    this.setMessage('', '');
    const settings: ProviderSettings | null = this.providers;
    if (settings !== null && settings.presets.length > 0) {
      this.applyPreset(settings.presets[0].id);
    } else {
      this.formPreset = 'custom';
    }
  }

  private openEdit(item: ModelProvider): void {
    this.providerEditId = item.id;
    this.formPreset = item.preset;
    this.formName = item.name;
    this.formBaseUrl = item.base_url;
    this.formModel = item.model;
    this.formApiKey = '';
    this.pendingDelete = '';
    this.setMessage('', '');
  }

  private closeForm(): void {
    this.providerEditId = '';
    this.formApiKey = '';
  }

  private async save(): Promise<void> {
    this.providerBusy = true;
    try {
      const id: string = this.providerEditId === 'new' ? '' : this.providerEditId;
      this.providers = await saveProvider(id, this.formPreset, this.formName,
        this.formBaseUrl, this.formModel, this.formApiKey);
      this.closeForm();
      this.setMessage('ok', this.tr('settings.saved'));
    } catch (err) {
      const error = err as Error;
      this.setMessage('danger', error.message);
    } finally {
      this.providerBusy = false;
    }
  }

  private async activate(item: ModelProvider): Promise<void> {
    this.providerBusy = true;
    try {
      this.providers = await setActiveProvider(item.id);
      this.setMessage('ok', this.trf('settings.activated', [item.name]));
    } catch (err) {
      const error = err as Error;
      this.setMessage('danger', error.message);
    } finally {
      this.providerBusy = false;
    }
  }

  private async remove(item: ModelProvider): Promise<void> {
    this.providerBusy = true;
    try {
      this.providers = await deleteProvider(item.id);
      this.pendingDelete = '';
      if (this.providerEditId === item.id) {
        this.closeForm();
      }
      this.setMessage('ok', this.trf('settings.deleted', [item.name]));
    } catch (err) {
      const error = err as Error;
      this.setMessage('danger', error.message);
    } finally {
      this.providerBusy = false;
    }
  }

  private async check(item: ModelProvider): Promise<void> {
    this.providerBusy = true;
    this.setMessage('', this.tr('settings.testing'));
    try {
      const result: ProviderTestResult = await testProvider(item.id);
      const model: string = result.model === undefined ? item.model : result.model;
      if (result.ok) {
        this.setMessage('ok', this.trf('settings.testOk', [model]));
      } else {
        this.setMessage('danger', this.trf('settings.testFailed', [result.message]));
      }
    } catch (err) {
      const error = err as Error;
      this.setMessage('danger', error.message);
    } finally {
      this.providerBusy = false;
    }
  }

  /** 提示行。色调只影响文字色，不占额外高度。 */
  @Builder
  MessageLine() {
    if (this.providerMessage.length > 0) {
      Text(this.providerMessage)
        .fontSize(12)
        .fontColor(this.providerMessageTone === 'ok'
          ? AppTheme.PRIMARY_DARK
          : (this.providerMessageTone === 'danger' ? AppTheme.DANGER : AppTheme.TEXT_TERTIARY))
        .width('100%')
        .margin({ top: 12 })
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

  /** 一条已存的来源：名字、模型、地址，以及它可以做的几个动作。 */
  @Builder
  ProviderRow(item: ModelProvider) {
    Column() {
      Row() {
        Text(item.name)
          .fontSize(14)
          .fontWeight(FontWeight.Medium)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .layoutWeight(1)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        if (item.id === (this.providers === null ? '' : this.providers.active)) {
          StatusBadge({ text: this.tr('settings.activeTag'), tone: 'ok' })
        } else if (item.key_required && !item.has_key) {
          StatusBadge({ text: this.tr('settings.needKey'), tone: 'warn' })
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(item.model.length > 0 ? item.model : '—')
        .fontSize(12)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ top: 4 })
      Text(item.base_url)
        .fontSize(11)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .margin({ top: 2 })

      if (this.pendingDelete === item.id) {
        Row({ space: 16 }) {
          Text(this.tr('settings.deleteConfirm'))
            .fontSize(12)
            .fontColor(AppTheme.DANGER)
            .padding({ top: 4, bottom: 4 })
            .onClick(() => {
              if (!this.providerBusy) {
                this.remove(item);
              }
            })
          Text(this.tr('common.cancel'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .padding({ top: 4, bottom: 4 })
            .onClick(() => {
              this.pendingDelete = '';
            })
        }
        .width('100%')
        .margin({ top: 10 })
      } else {
        Row({ space: 16 }) {
          if (item.id !== (this.providers === null ? '' : this.providers.active)) {
            Text(this.tr('settings.activate'))
              .fontSize(12)
              .fontColor(this.providerBusy ? AppTheme.TEXT_TERTIARY : AppTheme.PRIMARY)
              .padding({ top: 4, bottom: 4 })
              .onClick(() => {
                if (!this.providerBusy) {
                  this.activate(item);
                }
              })
          }
          Text(this.providerBusy ? this.tr('settings.testing') : this.tr('settings.test'))
            .fontSize(12)
            .fontColor(this.providerBusy ? AppTheme.TEXT_TERTIARY : AppTheme.PRIMARY)
            .padding({ top: 4, bottom: 4 })
            .onClick(() => {
              if (!this.providerBusy) {
                this.check(item);
              }
            })
          Text(this.tr('settings.edit'))
            .fontSize(12)
            .fontColor(this.providerBusy ? AppTheme.TEXT_TERTIARY : AppTheme.PRIMARY)
            .padding({ top: 4, bottom: 4 })
            .onClick(() => {
              if (!this.providerBusy) {
                this.openEdit(item);
              }
            })
          Text(this.tr('settings.delete'))
            .fontSize(12)
            .fontColor(this.providerBusy ? AppTheme.TEXT_TERTIARY : AppTheme.DANGER)
            .padding({ top: 4, bottom: 4 })
            .onClick(() => {
              if (!this.providerBusy) {
                this.pendingDelete = item.id;
              }
            })
        }
        .width('100%')
        .margin({ top: 10 })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12, bottom: 12 })
    .border({ width: { top: 1 }, color: AppTheme.BORDER_SOFT })
  }

  /** 新增 / 编辑表单。密钥框不显示已存的值，留空即不修改。 */
  @Builder
  ProviderForm() {
    CardPanel({
      title: this.providerEditId === 'new' ? this.tr('settings.newSource') : this.tr('settings.editSource')
    }) {
      Column() {
        Text(this.tr('settings.preset'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
        ChoiceChips({
          items: this.presetChoices(),
          active: this.formPreset,
          disabled: this.providerBusy,
          onSelect: (key: string) => {
            this.applyPreset(key);
          }
        })
          .margin({ top: 8 })

        Text(this.tr('settings.fieldName'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 8 })
        TextInput({ text: this.formName, placeholder: this.tr('settings.fieldNameHint') })
          .fontSize(13)
          .width('100%')
          .height(38)
          .onChange((value: string) => {
            this.formName = value;
          })

        Text(this.tr('settings.fieldBaseUrl'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 8 })
        TextInput({ text: this.formBaseUrl, placeholder: this.tr('settings.fieldBaseUrlHint') })
          .fontSize(13)
          .width('100%')
          .height(38)
          .onChange((value: string) => {
            this.formBaseUrl = value;
          })

        Text(this.tr('settings.fieldModel'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 8 })
        TextInput({ text: this.formModel, placeholder: this.tr('settings.fieldModelHint') })
          .fontSize(13)
          .width('100%')
          .height(38)
          .onChange((value: string) => {
            this.formModel = value;
          })

        Text(this.tr('settings.fieldApiKey'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 8 })
        TextInput({ text: this.formApiKey, placeholder: this.apiKeyHint() })
          .type(InputType.Password)
          .fontSize(13)
          .width('100%')
          .height(38)
          .onChange((value: string) => {
            this.formApiKey = value;
          })

        Row({ space: 12 }) {
          Text(this.providerBusy ? this.tr('settings.saving') : this.tr('settings.save'))
            .fontSize(13)
            .fontColor(Color.White)
            .backgroundColor(AppTheme.PRIMARY)
            .borderRadius(AppTheme.RADIUS_SM)
            .padding({ left: 16, right: 16, top: 8, bottom: 8 })
            .opacity(this.providerBusy ? 0.6 : 1)
            .enabled(!this.providerBusy)
            .onClick(() => {
              this.save();
            })
          Text(this.tr('common.cancel'))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .padding({ left: 8, right: 8, top: 8, bottom: 8 })
            .onClick(() => {
              if (!this.providerBusy) {
                this.closeForm();
              }
            })
        }
        .width('100%')
        .margin({ top: 16 })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  /** 模型来源这一段：当前用哪套、还有哪几套、怎么加一套。`key` 只用来触发重建。 */
  @Builder
  ModelSection(key: string) {
    Column({ space: 20 }) {
      CardPanel({
        title: this.tr('settings.currentSource')
      }) {
        Column() {
          if (this.providers === null || this.providers.providers.length === 0) {
            Text(this.tr('settings.noSource'))
              .fontSize(13)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .width('100%')
              .margin({ bottom: 4 })
          } else {
            KeyValueRow({
              label: this.tr('settings.currentName'),
              value: this.currentNameText()
            })
            KeyValueRow({
              label: this.tr('settings.currentModel'),
              value: this.providers === null || this.providers.model.length === 0 ? '—' : this.providers.model
            })
          }
          KeyValueRow({ label: this.tr('settings.keySource'), value: this.keySourceText() })
          KeyValueRow({
            label: this.tr('settings.secureStorage'),
            value: this.providers === null
              ? '—'
              : (this.providers.secure_storage_available ? this.tr('settings.available') : this.tr('settings.unavailable'))
          })
          KeyValueRow({
            label: this.tr('settings.apiKeyEnv'),
            value: this.providers === null ? '—' : this.providers.api_key_env,
            mono: true
          })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }

      CardPanel({
        title: this.tr('settings.sourceList')
      }) {
        Column() {
          ForEach(this.providers === null ? [] : this.providers.providers, (item: ModelProvider) => {
            this.ProviderRow(item)
          }, (item: ModelProvider) => `${item.id}-${item.model}-${item.has_key}-${this.pendingDelete === item.id}`)

          Row({ space: 12 }) {
            Text(this.tr('settings.newSource'))
              .fontSize(13)
              .fontColor(Color.White)
              .backgroundColor(AppTheme.PRIMARY)
              .borderRadius(AppTheme.RADIUS_SM)
              .padding({ left: 16, right: 16, top: 8, bottom: 8 })
              .opacity(this.providerBusy ? 0.6 : 1)
              .enabled(!this.providerBusy)
              .onClick(() => {
                this.openNew();
              })
          }
          .width('100%')
          .margin({ top: 16 })

          this.MessageLine()
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }

      if (this.providerEditId.length > 0) {
        this.ProviderForm()
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  /** 云端由平台统一维护 DeepSeek 来源；用户只看服务状态，不接触服务器密钥。 */
  @Builder
  ManagedModelSection() {
    CardPanel({ title: this.tr('settings.managedModel') }) {
      Column() {
        KeyValueRow({
          label: this.tr('settings.currentName'),
          value: this.tr('settings.deepseekManaged')
        })
        KeyValueRow({
          label: this.tr('settings.currentModel'),
          value: this.providers === null ? '—' : this.providers.model
        })
        Text(this.tr('settings.managedModelHint'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 10 })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
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

      if (this.section === 'backend') {
        CardPanel({
          title: this.tr('menu.backend')
        }) {
          Column() {
            KeyValueRow({ label: this.tr('settings.serviceAddress'), value: BASE_URL, mono: true })
            KeyValueRow({
              label: this.health !== null && this.health.mode === 'cloud'
                ? this.tr('settings.accountAuth')
                : this.tr('settings.sharedToken'),
              value: this.health !== null && this.health.mode === 'cloud'
                ? this.tr('settings.accountAuthActive')
                : (ACCESS_TOKEN.length > 0 ? this.tr('settings.configured') : this.tr('settings.tokenNotConfigured'))
            })
            KeyValueRow({
              label: this.tr('settings.health'),
              value: this.health === null ? '—' : this.health.status
            })
            KeyValueRow({
              label: this.tr('settings.workspace'),
              value: this.health === null ? '—' : (this.health.workspace || '—'),
              mono: true
            })
          }
          .width('100%')
        }
      } else if (this.section === 'model') {
        if (this.providers !== null && this.providers.managed === true) {
          this.ManagedModelSection()
        } else {
          ForEach(this.modelKeys(), (key: string) => {
            this.ModelSection(key)
          }, (key: string) => key)
        }
      } else if (this.section === 'runtime') {
        CardPanel({
          title: this.tr('settings.runtime')
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
      } else {
        LocalWorkspaceCard()
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
