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
import IconPaths from '../common/IconPaths';
import { tFor, tfFor } from '../common/I18n';
import {
  CardPanel,
  ChipButton,
  ChoiceChips,
  ChoiceSpec,
  EmptyHint,
  InfoRow,
  KeyValueRow,
  RailItemSpec,
  SectionCard,
  SectionRail,
  StatusBadge,
  StatusTile
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
  /** 父布局在窄窗口下传入，用于把环境卡片堆叠显示。 */
  @Prop compact: boolean = false;
  @State loading: boolean = false;
  @State errorText: string = '';
  @State health: HealthInfo | null = null;
  @State providers: ProviderSettings | null = null;
  @State runtime: RuntimeSnapshot | null = null;
  /**
   * 当前分段：overview / model / runtime / advanced。
   * 总览持续展示服务和运行环境状态，模型、运行环境详情可分别进入。
   */
  @State section: string = 'overview';

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

  private backendReady(): boolean {
    return this.health !== null;
  }

  private modelReady(): boolean {
    return this.providers !== null && this.providers.configured;
  }

  private missingRuntimeCount(): number {
    if (this.runtime === null) {
      return 0;
    }
    let count: number = 0;
    if (!this.runtime.gpu_available) count += 1;
    if (!this.runtime.conda_available) count += 1;
    return count;
  }

  private readinessTitle(): string {
    if (this.loading && (this.health === null || this.providers === null)) {
      return this.tr('settings.checking');
    }
    if (!this.backendReady() || !this.modelReady()) {
      return this.tr('settings.verdictBlocked');
    }
    return this.missingRuntimeCount() > 0
      ? this.tr('settings.verdictLimited')
      : this.tr('settings.verdictReady');
  }

  private readinessNote(): string {
    if (this.loading && (this.health === null || this.providers === null)) {
      return this.tr('settings.checkingNote');
    }
    if (!this.backendReady()) {
      return this.tr('settings.readiness.backendUnavailable');
    }
    if (!this.modelReady()) {
      return this.tr('settings.readiness.modelUnavailable');
    }
    if (this.missingRuntimeCount() > 0) {
      return this.tr('settings.readiness.limited');
    }
    return this.tr('settings.readiness.ready');
  }

  private readinessTone(): string {
    if (!this.backendReady()) {
      return this.loading && this.errorText.length === 0 ? 'muted' : 'danger';
    }
    if (!this.modelReady()) {
      return this.providers === null && this.loading ? 'muted' : 'warn';
    }
    return this.missingRuntimeCount() > 0 ? 'warn' : 'ok';
  }

  private runtimeGapText(): string {
    const gaps: string[] = [];
    if (this.runtime !== null && !this.runtime.gpu_available) {
      gaps.push(this.tr('settings.gpuCuda'));
    }
    if (this.runtime !== null && !this.runtime.conda_available) {
      gaps.push(this.tr('settings.condaEnv'));
    }
    return gaps.join('、');
  }

  /** 分段导航的项。色点说的是这一段通不通，不是它有多少条。 */
  private railItems(): RailItemSpec[] {
    const modelConfigured: boolean = this.providers !== null && this.providers.configured;
    return [
      { key: 'overview', label: this.tr('settings.section.overview'), tone: this.readinessTone() },
      { key: 'model', label: this.tr('settings.section.model'), tone: modelConfigured ? 'ok' : 'warn' },
      {
        key: 'runtime',
        label: this.tr('settings.section.runtime'),
        tone: this.runtime === null ? 'muted' : (this.runtime.gpu_available ? 'ok' : 'warn')
      },
      { key: 'advanced', label: this.tr('settings.section.advanced'), tone: 'muted' }
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
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(this.providerMessageTone === 'ok'
          ? AppTheme.PRIMARY_DARK
          : (this.providerMessageTone === 'danger' ? AppTheme.DANGER : AppTheme.TEXT_TERTIARY))
        .width('100%')
        .margin({ top: 12 * AppTheme.UI_SCALE })
    }
  }

  @Builder
  ErrorBanner() {
    Column() {
      Text(this.tr('settings.statusReadFailed'))
        .fontSize(15 * AppTheme.UI_SCALE)
        .fontWeight(FontWeight.Medium)
        .fontColor(AppTheme.DANGER)
      Text(this.errorText)
        .fontSize(13 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.DANGER)
        .margin({ top: 8 * AppTheme.UI_SCALE })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(20 * AppTheme.UI_SCALE)
    .backgroundColor(AppTheme.DANGER_SOFT)
    .borderRadius(AppTheme.RADIUS)
    .margin({ bottom: 20 * AppTheme.UI_SCALE })
  }

  /** 一条已存的来源：名字、模型、地址，以及它可以做的几个动作。 */
  @Builder
  ProviderRow(item: ModelProvider) {
    Column() {
      Row() {
        Text(item.name)
          .fontSize(14 * AppTheme.UI_SCALE)
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
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ top: 4 * AppTheme.UI_SCALE })
      Text(item.base_url)
        .fontSize(11 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .margin({ top: 2 * AppTheme.UI_SCALE })

      if (this.pendingDelete === item.id) {
        Row({ space: 16 * AppTheme.UI_SCALE }) {
          Text(this.tr('settings.deleteConfirm'))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.DANGER)
            .padding({ top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
            .onClick(() => {
              if (!this.providerBusy) {
                this.remove(item);
              }
            })
          Text(this.tr('common.cancel'))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .padding({ top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
            .onClick(() => {
              this.pendingDelete = '';
            })
        }
        .width('100%')
        .margin({ top: 10 * AppTheme.UI_SCALE })
      } else {
        Row({ space: 16 * AppTheme.UI_SCALE }) {
          if (item.id !== (this.providers === null ? '' : this.providers.active)) {
            Text(this.tr('settings.activate'))
              .fontSize(12 * AppTheme.UI_SCALE)
              .fontColor(this.providerBusy ? AppTheme.TEXT_TERTIARY : AppTheme.PRIMARY)
              .padding({ top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
              .onClick(() => {
                if (!this.providerBusy) {
                  this.activate(item);
                }
              })
          }
          Text(this.providerBusy ? this.tr('settings.testing') : this.tr('settings.test'))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(this.providerBusy ? AppTheme.TEXT_TERTIARY : AppTheme.PRIMARY)
            .padding({ top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
            .onClick(() => {
              if (!this.providerBusy) {
                this.check(item);
              }
            })
          Text(this.tr('settings.edit'))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(this.providerBusy ? AppTheme.TEXT_TERTIARY : AppTheme.PRIMARY)
            .padding({ top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
            .onClick(() => {
              if (!this.providerBusy) {
                this.openEdit(item);
              }
            })
          Text(this.tr('settings.delete'))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(this.providerBusy ? AppTheme.TEXT_TERTIARY : AppTheme.DANGER)
            .padding({ top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
            .onClick(() => {
              if (!this.providerBusy) {
                this.pendingDelete = item.id;
              }
            })
        }
        .width('100%')
        .margin({ top: 10 * AppTheme.UI_SCALE })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12 * AppTheme.UI_SCALE, bottom: 12 * AppTheme.UI_SCALE })
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
          .fontSize(12 * AppTheme.UI_SCALE)
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
          .margin({ top: 8 * AppTheme.UI_SCALE })

        Text(this.tr('settings.fieldName'))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 8 * AppTheme.UI_SCALE })
        TextInput({ text: this.formName, placeholder: this.tr('settings.fieldNameHint') })
          .fontSize(13 * AppTheme.UI_SCALE)
          .width('100%')
          .height(38 * AppTheme.UI_SCALE)
          .onChange((value: string) => {
            this.formName = value;
          })

        Text(this.tr('settings.fieldBaseUrl'))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 8 * AppTheme.UI_SCALE })
        TextInput({ text: this.formBaseUrl, placeholder: this.tr('settings.fieldBaseUrlHint') })
          .fontSize(13 * AppTheme.UI_SCALE)
          .width('100%')
          .height(38 * AppTheme.UI_SCALE)
          .onChange((value: string) => {
            this.formBaseUrl = value;
          })

        Text(this.tr('settings.fieldModel'))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 8 * AppTheme.UI_SCALE })
        TextInput({ text: this.formModel, placeholder: this.tr('settings.fieldModelHint') })
          .fontSize(13 * AppTheme.UI_SCALE)
          .width('100%')
          .height(38 * AppTheme.UI_SCALE)
          .onChange((value: string) => {
            this.formModel = value;
          })

        Text(this.tr('settings.fieldApiKey'))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 8 * AppTheme.UI_SCALE })
        TextInput({ text: this.formApiKey, placeholder: this.apiKeyHint() })
          .type(InputType.Password)
          .fontSize(13 * AppTheme.UI_SCALE)
          .width('100%')
          .height(38 * AppTheme.UI_SCALE)
          .onChange((value: string) => {
            this.formApiKey = value;
          })

        Row({ space: 12 * AppTheme.UI_SCALE }) {
          Text(this.providerBusy ? this.tr('settings.saving') : this.tr('settings.save'))
            .fontSize(13 * AppTheme.UI_SCALE)
            .fontColor(Color.White)
            .backgroundColor(AppTheme.PRIMARY)
            .borderRadius(AppTheme.RADIUS_SM)
            .padding({ left: 16 * AppTheme.UI_SCALE, right: 16 * AppTheme.UI_SCALE, top: 8 * AppTheme.UI_SCALE, bottom: 8 * AppTheme.UI_SCALE })
            .opacity(this.providerBusy ? 0.6 : 1)
            .enabled(!this.providerBusy)
            .onClick(() => {
              this.save();
            })
          Text(this.tr('common.cancel'))
            .fontSize(13 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .padding({ left: 8 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE, top: 8 * AppTheme.UI_SCALE, bottom: 8 * AppTheme.UI_SCALE })
            .onClick(() => {
              if (!this.providerBusy) {
                this.closeForm();
              }
            })
        }
        .width('100%')
        .margin({ top: 16 * AppTheme.UI_SCALE })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  /** 模型来源这一段：当前用哪套、还有哪几套、怎么加一套。`key` 只用来触发重建。 */
  @Builder
  ModelSection(key: string) {
    Column({ space: 20 * AppTheme.UI_SCALE }) {
      CardPanel({
        title: this.tr('settings.currentSource')
      }) {
        Column() {
          if (this.providers === null || this.providers.providers.length === 0) {
            Text(this.tr('settings.noSource'))
              .fontSize(13 * AppTheme.UI_SCALE)
              .fontColor(AppTheme.TEXT_TERTIARY)
              .width('100%')
              .margin({ bottom: 4 * AppTheme.UI_SCALE })
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

          Row({ space: 12 * AppTheme.UI_SCALE }) {
            Text(this.tr('settings.newSource'))
              .fontSize(13 * AppTheme.UI_SCALE)
              .fontColor(Color.White)
              .backgroundColor(AppTheme.PRIMARY)
              .borderRadius(AppTheme.RADIUS_SM)
              .padding({ left: 16 * AppTheme.UI_SCALE, right: 16 * AppTheme.UI_SCALE, top: 8 * AppTheme.UI_SCALE, bottom: 8 * AppTheme.UI_SCALE })
              .opacity(this.providerBusy ? 0.6 : 1)
              .enabled(!this.providerBusy)
              .onClick(() => {
                this.openNew();
              })
          }
          .width('100%')
          .margin({ top: 16 * AppTheme.UI_SCALE })

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
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .width('100%')
          .margin({ top: 10 * AppTheme.UI_SCALE })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  @Builder
  GpuRow(item: GpuDevice) {
    Column() {
      Text(item.name)
        .fontSize(13 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_PRIMARY)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      Text(this.trf('settings.gpuMemory', [
        memoryGb(item.memory_free_mb),
        memoryGb(item.memory_total_mb),
        item.driver_version
      ]))
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_TERTIARY)
        .margin({ top: 6 * AppTheme.UI_SCALE })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ top: 12 * AppTheme.UI_SCALE, bottom: 12 * AppTheme.UI_SCALE })
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  /** 页面抬头保持克制，让紧随其后的运行就绪结论成为视觉焦点。 */
  @Builder
  SettingsHeading() {
    Column() {
      Text(this.tr('nav.settings'))
        .fontSize(20 * AppTheme.UI_SCALE)
        .fontWeight(FontWeight.Bold)
        .fontColor(AppTheme.TEXT_PRIMARY)
      Text(this.tr('settings.pageDesc'))
        .fontSize(12 * AppTheme.UI_SCALE)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ top: 3 * AppTheme.UI_SCALE })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  /** 总览顶部：服务与模型是能否连上服务的关键；GPU / Conda 只影响对应的计算能力。 */
  @Builder
  ReadinessPanel() {
    Column() {
      Row() {
        Column() {
          Text(this.tr('settings.readiness.title'))
            .fontSize(11 * AppTheme.UI_SCALE)
            .fontWeight(FontWeight.Medium)
            .fontColor(AppTheme.TEXT_TERTIARY)
          Text(this.readinessTitle())
            .fontSize(19 * AppTheme.UI_SCALE)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.readinessTone() === 'danger'
              ? AppTheme.DANGER
              : (this.readinessTone() === 'warn' ? AppTheme.WARN_TEXT : AppTheme.TEXT_PRIMARY))
            .margin({ top: 4 * AppTheme.UI_SCALE })
          Text(this.readinessNote())
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
            .maxLines(2)
            .margin({ top: 4 * AppTheme.UI_SCALE })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        ChipButton({
          icon: IconPaths.REFRESH,
          label: this.loading ? this.tr('settings.checking') : this.tr('settings.recheckAll'),
          tone: 'primary',
          active: !this.loading,
          onTap: () => {
            this.load();
          }
        })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      if (this.missingRuntimeCount() > 0) {
        Column() {
          Row() {
            Text(this.trf('settings.limitedTitle', [`${this.missingRuntimeCount()}`]))
              .fontSize(12 * AppTheme.UI_SCALE)
              .fontWeight(FontWeight.Medium)
              .fontColor(AppTheme.WARN_TEXT)
              .layoutWeight(1)
            Text(this.tr('settings.section.runtime'))
              .fontSize(12 * AppTheme.UI_SCALE)
              .fontColor(AppTheme.WARN_TEXT)
              .padding({ left: 8 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE, top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
              .onClick(() => {
                this.section = 'runtime';
              })
          }
          .width('100%')
          Text(this.trf('settings.limitedBody', [this.runtimeGapText()]))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.WARN_TEXT)
            .width('100%')
            .margin({ top: 4 * AppTheme.UI_SCALE })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .padding({ left: 12 * AppTheme.UI_SCALE, right: 12 * AppTheme.UI_SCALE, top: 9 * AppTheme.UI_SCALE, bottom: 9 * AppTheme.UI_SCALE })
        .backgroundColor(AppTheme.WARN_SOFT)
        .borderRadius(AppTheme.RADIUS_SM)
        .margin({ top: 12 * AppTheme.UI_SCALE })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding(18 * AppTheme.UI_SCALE)
    .backgroundColor(AppTheme.SURFACE)
    .borderRadius(AppTheme.RADIUS_LG)
    .border({ width: 1, color: this.readinessTone() === 'warn' ? AppTheme.WARN_SOFT : AppTheme.BORDER })
  }

  @Builder
  StatusTilesFirstRow() {
    Row({ space: 12 * AppTheme.UI_SCALE }) {
      StatusTile({
        icon: IconPaths.SERVER,
        title: this.tr('settings.tile.backend'),
        subtitle: this.tr('settings.tile.backend'),
        tone: this.backendReady() ? 'ok' : (this.health === null && this.loading ? 'muted' : 'danger'),
        pill: this.backendReady() ? this.tr('settings.pillNormal') : (this.loading ? this.tr('settings.checking') : this.tr('settings.notConnected')),
        value: this.backendReady() ? this.tr('menu.backendOk') : '',
        note: this.backendReady() ? this.tr('settings.tile.noteBackendOk') : this.tr('settings.tile.noteBackendDown')
      }).layoutWeight(1)
      StatusTile({
        icon: IconPaths.BRAIN,
        title: this.tr('settings.tile.model'),
        subtitle: this.providers !== null && this.providers.managed ? this.tr('settings.managedByPlatform') : this.tr('settings.section.model'),
        tone: this.modelReady() ? 'ok' : (this.providers === null && this.loading ? 'muted' : 'warn'),
        pill: this.modelReady() ? this.tr('settings.pillNormal') : (this.loading ? this.tr('settings.checking') : this.tr('settings.pillUnconfigured')),
        value: this.providers === null ? '' : (this.providers.model.length > 0 ? this.providers.model : '—'),
        note: this.modelReady() ? this.tr('settings.tile.noteModelOk') : this.tr('settings.tile.noteModelMissing')
      }).layoutWeight(1)
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }

  @Builder
  StatusTilesSecondRow() {
    Row({ space: 12 * AppTheme.UI_SCALE }) {
      StatusTile({
        icon: IconPaths.BOX,
        title: this.tr('settings.gpuCuda'),
        subtitle: 'GPU / CUDA',
        tone: this.runtime === null ? 'muted' : (this.runtime.gpu_available ? 'ok' : 'warn'),
        pill: this.runtime === null ? this.tr('settings.notProbed') : (this.runtime.gpu_available ? this.tr('settings.pillNormal') : this.tr('settings.pillNotDetected')),
        value: this.runtime !== null && this.runtime.gpus.length > 0 ? this.runtime.gpus[0].name : '',
        note: this.runtime === null ? this.tr('settings.checkingNote') : (this.runtime.gpu_available ? this.tr('settings.tile.noteGpuOk') : this.tr('settings.tile.noteGpuMissing') )
      }).layoutWeight(1)
      StatusTile({
        icon: IconPaths.SLIDERS,
        title: this.tr('settings.condaEnv'),
        subtitle: 'Conda',
        tone: this.runtime === null ? 'muted' : (this.runtime.conda_available ? 'ok' : 'warn'),
        pill: this.runtime === null ? this.tr('settings.notProbed') : (this.runtime.conda_available ? this.tr('settings.pillNormal') : this.tr('settings.pillNotDetected')),
        value: this.runtime !== null && this.runtime.conda_available ? this.tr('settings.available') : '',
        note: this.runtime === null ? this.tr('settings.checkingNote') : (this.runtime.conda_available ? this.tr('settings.tile.noteCondaOk') : this.tr('settings.tile.noteCondaMissing'))
      }).layoutWeight(1)
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }

  @Builder
  StatusTilesWideRow() {
    Row({ space: 12 * AppTheme.UI_SCALE }) {
      StatusTile({
        icon: IconPaths.SERVER,
        title: this.tr('settings.tile.backend'),
        subtitle: 'API',
        tone: this.backendReady() ? 'ok' : (this.health === null && this.loading ? 'muted' : 'danger'),
        pill: this.backendReady() ? this.tr('settings.pillNormal') : (this.loading ? this.tr('settings.checking') : this.tr('settings.notConnected')),
        value: this.backendReady() ? this.tr('menu.backendOk') : '',
        note: this.backendReady() ? this.tr('settings.tile.noteBackendOk') : this.tr('settings.tile.noteBackendDown')
      }).layoutWeight(1)
      StatusTile({
        icon: IconPaths.BRAIN,
        title: this.tr('settings.tile.model'),
        subtitle: this.providers !== null && this.providers.managed ? this.tr('settings.managedByPlatform') : this.tr('settings.section.model'),
        tone: this.modelReady() ? 'ok' : (this.providers === null && this.loading ? 'muted' : 'warn'),
        pill: this.modelReady() ? this.tr('settings.pillNormal') : (this.loading ? this.tr('settings.checking') : this.tr('settings.pillUnconfigured')),
        value: this.providers === null ? '' : (this.providers.model.length > 0 ? this.providers.model : '—'),
        note: this.modelReady() ? this.tr('settings.tile.noteModelOk') : this.tr('settings.tile.noteModelMissing')
      }).layoutWeight(1)
      StatusTile({
        icon: IconPaths.BOX,
        title: this.tr('settings.gpuCuda'),
        subtitle: 'GPU / CUDA',
        tone: this.runtime === null ? 'muted' : (this.runtime.gpu_available ? 'ok' : 'warn'),
        pill: this.runtime === null ? this.tr('settings.notProbed') : (this.runtime.gpu_available ? this.tr('settings.pillNormal') : this.tr('settings.pillNotDetected')),
        value: this.runtime !== null && this.runtime.gpus.length > 0 ? this.runtime.gpus[0].name : '',
        note: this.runtime === null ? this.tr('settings.checkingNote') : (this.runtime.gpu_available ? this.tr('settings.tile.noteGpuOk') : this.tr('settings.tile.noteGpuMissing'))
      }).layoutWeight(1)
      StatusTile({
        icon: IconPaths.SLIDERS,
        title: this.tr('settings.condaEnv'),
        subtitle: 'Conda',
        tone: this.runtime === null ? 'muted' : (this.runtime.conda_available ? 'ok' : 'warn'),
        pill: this.runtime === null ? this.tr('settings.notProbed') : (this.runtime.conda_available ? this.tr('settings.pillNormal') : this.tr('settings.pillNotDetected')),
        value: this.runtime !== null && this.runtime.conda_available ? this.tr('settings.available') : '',
        note: this.runtime === null ? this.tr('settings.checkingNote') : (this.runtime.conda_available ? this.tr('settings.tile.noteCondaOk') : this.tr('settings.tile.noteCondaMissing'))
      }).layoutWeight(1)
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }

  @Builder
  ModelRuntimeSummary() {
    SectionCard({
      title: this.tr('settings.card.modelRuntime'),
      subtitle: this.tr('settings.card.modelRuntimeSub'),
      icon: IconPaths.BOX,
      iconTone: this.modelReady() ? 'ok' : 'warn',
      weight: this.compact ? 0 : 1,
      actionLabel: this.providers !== null && this.providers.managed
        ? this.tr('settings.viewModelInfo')
        : this.tr('settings.section.model'),
      onAction: () => {
        this.section = 'model';
      }
    }) {
      Column() {
        InfoRow({
          label: this.tr('settings.modelProvider'),
          value: this.providers !== null && this.providers.managed ? this.tr('settings.deepseekManaged') : this.currentNameText()
        })
        InfoRow({
          label: this.tr('settings.modelName'),
          value: this.providers === null ? '—' : this.providers.model
        })
        InfoRow({
          label: this.tr('settings.pythonInterpreter'),
          value: this.runtime === null ? '—' : this.runtime.python,
          mono: true
        })
        InfoRow({
          label: this.tr('settings.condaEnv'),
          value: this.runtime === null ? this.tr('settings.notProbed') : (this.runtime.conda_available ? this.tr('settings.available') : this.tr('settings.unavailable')),
          pill: this.runtime === null ? '' : (this.runtime.conda_available ? this.tr('settings.pillNormal') : this.tr('settings.pillNotDetected')),
          tone: this.runtime === null ? 'muted' : (this.runtime.conda_available ? 'ok' : 'warn')
        })
        InfoRow({
          label: this.tr('settings.gpuCuda'),
          value: this.runtime === null ? this.tr('settings.notProbed') : (this.runtime.gpu_available ? this.trf('settings.gpuCount', [`${this.runtime.gpus.length}`]) : this.tr('settings.unavailable')),
          pill: this.runtime === null ? '' : (this.runtime.gpu_available ? this.tr('settings.pillNormal') : this.tr('settings.pillNotDetected')),
          tone: this.runtime === null ? 'muted' : (this.runtime.gpu_available ? 'ok' : 'warn')
        })
        Text(this.providers !== null && this.providers.managed
          ? this.tr('settings.managedModelHint')
          : this.tr('settings.localModelHint'))
          .fontSize(11 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width('100%')
          .margin({ top: 8 * AppTheme.UI_SCALE })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  @Builder
  OverviewSection() {
    Column({ space: 12 * AppTheme.UI_SCALE }) {
      if (this.compact) {
        this.StatusTilesFirstRow()
        this.StatusTilesSecondRow()
      } else {
        this.StatusTilesWideRow()
      }
      if (this.compact) {
        Column({ space: 12 * AppTheme.UI_SCALE }) {
          LocalWorkspaceCard()
          this.ModelRuntimeSummary()
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      } else {
        Row({ space: 12 * AppTheme.UI_SCALE }) {
          LocalWorkspaceCard()
            .layoutWeight(1)
          this.ModelRuntimeSummary()
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  build() {
    Column({ space: 20 * AppTheme.UI_SCALE }) {
      this.SettingsHeading()

      if (this.errorText.length > 0) {
        this.ErrorBanner()
      }

      this.ReadinessPanel()

      SectionRail({
        items: this.railItems(),
        active: this.section,
        onSelect: (key: string) => {
          this.section = key;
        }
      })

      if (this.section === 'overview') {
        this.OverviewSection()
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
            KeyValueRow({
              label: this.tr('settings.condaEnv'),
              value: this.runtime === null ? this.tr('settings.notProbed') : (this.runtime.conda_available ? this.tr('settings.available') : this.tr('settings.unavailable'))
            })
            if (this.runtime === null || this.runtime.gpus.length === 0) {
              EmptyHint({ text: this.runtime === null ? this.tr('settings.notProbed') : this.tr('settings.tile.noteGpuMissing') })
            } else {
              ForEach(this.runtime.gpus, (item: GpuDevice) => {
                this.GpuRow(item)
              }, (item: GpuDevice) => item.name)
            }
            Text(this.tr('settings.runtimeManagementHint'))
              .fontSize(12 * AppTheme.UI_SCALE)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .width('100%')
              .margin({ top: 12 * AppTheme.UI_SCALE })
          }
          .width('100%')
        }
      } else if (this.section === 'advanced') {
        Column({ space: 12 * AppTheme.UI_SCALE }) {
          CardPanel({ title: this.tr('settings.card.advanced') }) {
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
              KeyValueRow({ label: this.tr('settings.health'), value: this.health === null ? '—' : this.health.status })
              KeyValueRow({
                label: this.tr('settings.workspace'),
                value: this.health === null ? '—' : (this.health.workspace || '—'),
                mono: true
              })
              Text(this.tr('settings.advancedHint'))
                .fontSize(12 * AppTheme.UI_SCALE)
                .fontColor(AppTheme.TEXT_SECONDARY)
                .width('100%')
                .margin({ top: 12 * AppTheme.UI_SCALE })
            }
            .width('100%')
          }
          CardPanel({ title: this.tr('settings.card.permissions') }) {
            Text(this.tr('settings.agentPermissionsHint'))
              .fontSize(12 * AppTheme.UI_SCALE)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .width('100%')
          }
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }

      if (this.loading) {
        Text(this.tr('common.loading'))
          .fontSize(12 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 12 * AppTheme.UI_SCALE })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }
}
