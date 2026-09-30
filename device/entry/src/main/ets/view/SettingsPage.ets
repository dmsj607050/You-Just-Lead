import { common } from '@kit.AbilityKit';
import { preferences } from '@kit.ArkData';
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
import { describeError } from '../common/Format';
import IconPaths from '../common/IconPaths';
import { tFor, tfFor } from '../common/I18n';
import {
  LocalWorkspaceReport,
  emptyReport,
  inspectLocalWorkspace
} from '../common/LocalWorkspaceState';
import { LocalWorkspaceCard } from './LocalWorkspaceCard';
import {
  ChipButton,
  ChoiceChips,
  ChoiceSpec,
  EmptyHint,
  InfoRow,
  SectionCard,
  StatusPill,
  StatusTile,
  ToggleRow
} from './Widgets';

/** 显存容量转成 GB 描述。 */
function memoryGb(mb: number): string {
  return `${(mb / 1024).toFixed(1)} GB`;
}

/**
 * 两栏并排需要的最小宽度。
 *
 * 900 太高了：这一页住在侧栏右边，2in1 窗口下的可用宽度只有 800 左右 vp，
 * 按 900 判就会在桌面上也退成单栏 —— 参考稿本来就是两栏。720 以上按两栏排，
 * 手机上（360~420）自然落回单栏。
 */
const WIDE_MIN_WIDTH: number = 720;

/** 权限偏好与语言共用同一个偏好文件（端侧设置就这一处）。 */
const PREF_STORE: string = 'youjustlead_settings';
const PREF_PERM_DEPS: string = 'perm_install_deps';
const PREF_PERM_CODE: string = 'perm_edit_code';
const PREF_PERM_EXPERIMENT: string = 'perm_run_experiments';
const PREF_PERM_CONFIRM: string = 'perm_confirm_key_steps';

/**
 * 设置页：先回答「现在能不能用」，再给配置入口。
 *
 * 版式按参考稿重排成一块一块：就绪状态在最上面（用户第一眼要的是结论，不是一堆字段），
 * 下面四张状态磁贴说清每项能力，再接两栏配置卡片与权限、高级信息。
 * 原来的分段导航（本地工作区 / 后端 / 模型 / 运行时）去掉了 —— 它把「系统到底行不行」
 * 拆成了四次点击，而且每次只看得到四分之一。
 *
 * 模型来源那一段仍是可改的（云端模式下由平台托管、端侧只读）：
 * 密钥只往系统凭据管理器里写，界面既不显示也不会把它读回来。
 */
@Component
export struct SettingsPage {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  /** 是否已打开端侧规则检查（整页）。与工作区卡片同一套全局标记。 */
  @StorageLink('localGateOpen') gateOpen: boolean = false;
  /** 是否已打开离线记录（整页）。 */
  @StorageLink('localStatusOpen') statusOpen: boolean = false;

  @State loading: boolean = false;
  @State errorText: string = '';
  @State health: HealthInfo | null = null;
  @State providers: ProviderSettings | null = null;
  @State runtime: RuntimeSnapshot | null = null;
  /** 内容区够宽吗（不够就单栏）。由根节点的 onAreaChange 维护。 */
  @State compact: boolean = false;

  /** 端侧工作区自检结果。工作区卡片自己会显示目录，这里这一份供「高级信息」用。 */
  @State localReport: LocalWorkspaceReport = emptyReport();
  @State localError: string = '';
  /**
   * 端侧自检的刷新计数。
   *
   * 工作区卡片有自己的状态，页面的「重新检测」不该只刷新一半 —— 把计数放进 `ForEach`
   * 的 key 里，点一次就把它整块重建一次，卡片会重新自检。
   */
  @State localRevision: number = 0;

  /** Agent 权限：端侧保存的约定，见卡片脚注。 */
  @State permDeps: boolean = true;
  @State permCode: boolean = true;
  @State permExperiment: boolean = true;
  @State permConfirm: boolean = false;
  @State permBusy: boolean = false;

  /** 「模型与运行时」卡片里测试连接的结果（与来源卡片的消息分开，各自贴着自己的操作）。 */
  @State modelTestText: string = '';
  @State modelTestTone: string = '';

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
    this.loadLocal();
    this.loadPermissions();
  }

  /** 重新检测：后端三项 + 端侧工作区一次全刷。 */
  async recheckAll(): Promise<void> {
    await this.load();
    await this.loadLocal();
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
      // 后端不在时不能留着上一次的数字装作还活着：清掉，磁贴会显示「未连接」。
      this.health = null;
      this.providers = null;
      this.runtime = null;
    } finally {
      this.loading = false;
    }
  }

  // ---- 端侧工作区（不经后端）----

  private abilityContext(): common.UIAbilityContext {
    return this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  async loadLocal(): Promise<void> {
    this.localError = '';
    try {
      this.localReport = await inspectLocalWorkspace(this.abilityContext());
      this.localRevision = this.localRevision + 1;
    } catch (err) {
      this.localError = describeError(err as Object);
    }
  }

  /** 工作区卡片的 key：带上刷新计数，让「重新检测」能把它一起刷新。 */
  private workspaceKeys(): string[] {
    return [`workspace-${this.localRevision}`];
  }

  // ---- Agent 权限（端侧偏好）----

  async loadPermissions(): Promise<void> {
    try {
      const store: preferences.Preferences = await preferences.getPreferences(this.abilityContext(), PREF_STORE);
      const deps: preferences.ValueType = await store.get(PREF_PERM_DEPS, true);
      const code: preferences.ValueType = await store.get(PREF_PERM_CODE, true);
      const experiment: preferences.ValueType = await store.get(PREF_PERM_EXPERIMENT, true);
      const confirm: preferences.ValueType = await store.get(PREF_PERM_CONFIRM, false);
      this.permDeps = deps === true;
      this.permCode = code === true;
      this.permExperiment = experiment === true;
      this.permConfirm = confirm === true;
    } catch (err) {
      // 读不到就用默认值，不打断设置页。
    }
  }

  private async savePermission(key: string, value: boolean): Promise<void> {
    this.permBusy = true;
    try {
      const store: preferences.Preferences = await preferences.getPreferences(this.abilityContext(), PREF_STORE);
      await store.put(key, value);
      await store.flush();
    } catch (err) {
      // 存不下来只影响下次启动的默认值，界面上的开关仍按用户刚点的那个值显示。
    } finally {
      this.permBusy = false;
    }
  }

  // ---- 就绪状态 ----

  /** 后端通不通。 */
  private backendOk(): boolean {
    return this.health !== null;
  }

  /** 有没有一套能用的模型来源（云端托管时以 configured 为准）。 */
  private modelOk(): boolean {
    return this.providers !== null && this.providers.configured;
  }

  private gpuOk(): boolean {
    return this.runtime !== null && this.runtime.gpu_available;
  }

  private condaOk(): boolean {
    return this.runtime !== null && this.runtime.conda_available;
  }

  /** 探测到的显卡列表。写成方法是为了不在模板里对 `this.runtime` 反复做空判断。 */
  private gpuList(): GpuDevice[] {
    return this.runtime === null ? [] : this.runtime.gpus;
  }

  /** 受限的能力有哪几项（名字已本地化，用来拼提示语）。 */
  private limitedNames(): string[] {
    const names: string[] = [];
    if (!this.modelOk()) {
      names.push(this.tr('settings.tile.model'));
    }
    if (!this.gpuOk()) {
      names.push(this.tr('settings.gpuCuda'));
    }
    if (!this.condaOk()) {
      names.push(this.tr('settings.condaEnv'));
    }
    return names;
  }

  private verdict(): string {
    if (!this.backendOk()) {
      return this.tr('settings.verdictBlocked');
    }
    return this.limitedNames().length > 0 ? this.tr('settings.verdictLimited') : this.tr('settings.verdictReady');
  }

  private verdictNote(): string {
    if (!this.backendOk()) {
      return this.tr('settings.verdictBlockedNote');
    }
    return this.limitedNames().length > 0
      ? this.tr('settings.verdictLimitedNote')
      : this.tr('settings.verdictReadyNote');
  }

  private verdictTone(): string {
    if (!this.backendOk()) {
      return 'danger';
    }
    return this.limitedNames().length > 0 ? 'warn' : 'ok';
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

  /** 「模型与运行时」卡片里的测试连接：测的是当前使用的那套。 */
  private async checkCurrent(): Promise<void> {
    const current: ModelProvider | null = this.currentProvider();
    if (current === null) {
      this.modelTestTone = 'warn';
      this.modelTestText = this.tr('settings.noSource');
      return;
    }
    this.providerBusy = true;
    this.modelTestTone = '';
    this.modelTestText = this.tr('settings.testing');
    try {
      const result: ProviderTestResult = await testProvider(current.id);
      const model: string = result.model === undefined ? current.model : result.model;
      if (result.ok) {
        this.modelTestTone = 'ok';
        this.modelTestText = this.trf('settings.testOk', [model]);
      } else {
        this.modelTestTone = 'danger';
        this.modelTestText = this.trf('settings.testFailed', [result.message]);
      }
    } catch (err) {
      const error = err as Error;
      this.modelTestTone = 'danger';
      this.modelTestText = error.message;
    } finally {
      this.providerBusy = false;
    }
  }

  // ---- 版式 ----

  /** 页头：中文大标题 + 英文副标题 + 一行说明。 */
  @Builder
  Head() {
    Column() {
      Row() {
        Text(this.tr('nav.settings'))
          .fontSize(26)
          .fontWeight(FontWeight.Bold)
          .fontColor(AppTheme.TEXT_PRIMARY)
        Text(this.tr('settings.pageSubtitle'))
          .fontSize(13)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ left: 10, top: 8 })
      }
      .alignItems(VerticalAlign.Bottom)

      Text(this.tr('settings.pageDesc'))
        .fontSize(13)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .margin({ top: 8 })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
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

  /** 就绪状态：一句结论 + 一句补充 + 两个入口。全页的视觉焦点。 */
  @Builder
  ReadinessCard() {
    SectionCard({
      title: this.tr('settings.readiness.title'),
      subtitle: 'System readiness',
      icon: IconPaths.SHIELD_CHECK,
      iconTone: this.verdictTone()
    }) {
      Row() {
        StatusPill({ label: this.verdict(), tone: this.verdictTone() })
      }
      .width('100%')

      Text(this.verdictNote())
        .fontSize(13)
        .fontColor(AppTheme.TEXT_SECONDARY)
        .width('100%')
        .margin({ top: 10 })

      Row({ space: 12 }) {
        ChipButton({
          icon: IconPaths.REFRESH,
          label: this.loading ? this.tr('settings.working') : this.tr('settings.recheckAll'),
          tone: 'primary',
          active: !this.loading,
          onTap: () => {
            this.recheckAll();
          }
        })
        ChipButton({
          icon: IconPaths.DOC,
          label: this.tr('settings.offlineRecords'),
          tone: 'outline',
          active: true,
          onTap: () => {
            this.statusOpen = true;
          }
        })
      }
      .width('100%')
      .margin({ top: 16 })
    }
  }

  @Builder
  BackendTile(weight: number) {
    StatusTile({
      icon: IconPaths.SERVER,
      title: this.tr('settings.tile.backend'),
      subtitle: 'Backend Service',
      tone: this.backendOk() ? 'ok' : 'danger',
      pill: this.backendOk() ? this.tr('settings.pillNormal') : this.tr('settings.notConnected'),
      value: '',
      note: this.backendOk() ? this.tr('settings.tile.noteBackendOk') : this.tr('settings.tile.noteBackendDown')
    })
      .layoutWeight(weight)
  }

  @Builder
  ModelTile(weight: number) {
    StatusTile({
      icon: IconPaths.BRAIN,
      title: this.tr('settings.tile.model'),
      subtitle: 'AI Model',
      tone: this.modelOk() ? 'ok' : 'warn',
      pill: this.modelOk() ? this.tr('settings.available') : this.tr('settings.pillUnconfigured'),
      value: this.providers === null || this.providers.model.length === 0 ? '' : this.providers.model,
      note: this.modelOk() ? this.tr('settings.tile.noteModelOk') : this.tr('settings.tile.noteModelMissing')
    })
      .layoutWeight(weight)
  }

  @Builder
  GpuTile(weight: number) {
    StatusTile({
      icon: IconPaths.CHIP,
      title: this.tr('settings.gpuCuda'),
      subtitle: 'Compute',
      tone: this.gpuOk() ? 'ok' : 'warn',
      pill: this.runtime === null
        ? this.tr('settings.pillNotDetected')
        : (this.gpuOk() ? this.tr('settings.available') : this.tr('settings.pillUnconfigured')),
      value: this.gpuOk() && this.gpuList().length > 0 ? this.gpuList()[0].name : '',
      note: this.gpuOk() ? this.tr('settings.tile.noteGpuOk') : this.tr('settings.tile.noteGpuMissing')
    })
      .layoutWeight(weight)
  }

  @Builder
  CondaTile(weight: number) {
    StatusTile({
      icon: IconPaths.BOX,
      title: this.tr('settings.condaEnv'),
      subtitle: 'Environments',
      tone: this.condaOk() ? 'ok' : 'warn',
      pill: this.runtime === null
        ? this.tr('settings.pillNotDetected')
        : (this.condaOk() ? this.tr('settings.available') : this.tr('settings.pillUnconfigured')),
      value: '',
      note: this.condaOk() ? this.tr('settings.tile.noteCondaOk') : this.tr('settings.tile.noteCondaMissing')
    })
      .layoutWeight(weight)
  }

  /** 四张状态磁贴。宽屏一行四个，窄屏两行两个（一行四个在手机上会挤成一条）。 */
  @Builder
  TileGrid() {
    if (this.compact) {
      Column({ space: 12 }) {
        Row({ space: 12 }) {
          this.BackendTile(1)
          this.ModelTile(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)

        Row({ space: 12 }) {
          this.GpuTile(1)
          this.CondaTile(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
      }
      .width('100%')
    } else {
      Row({ space: 12 }) {
        this.BackendTile(1)
        this.ModelTile(1)
        this.GpuTile(1)
        this.CondaTile(1)
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)
    }
  }

  /** 能力受限时的横条：说清缺什么、影响什么。 */
  @Builder
  LimitedStrip() {
    if (this.backendOk() && this.limitedNames().length > 0) {
      Row() {
        StatusPill({ label: this.trf('settings.limitedTitle', [`${this.limitedNames().length}`]), tone: 'warn' })
        Text(this.trf('settings.limitedBody', [this.limitedNames().join('、')]))
          .fontSize(12)
          .fontColor(AppTheme.WARN_TEXT)
          .layoutWeight(1)
          .margin({ left: 12 })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .padding({ left: 16, right: 16, top: 12, bottom: 12 })
      .backgroundColor(AppTheme.WARN_SOFT)
      .borderRadius(AppTheme.RADIUS)
    }
  }

  /**
   * 工作区设置：直接挂 `LocalWorkspaceCard`。
   *
   * 不在这里重画一遍 —— 启动页（项目选择）挂的是同一张卡片，两处必须一模一样；
   * 而且它承载的是「后端不在时仍然能用」那条支线，不能有第二份实现。
   * key 里带上刷新计数：点「重新检测」时把它重建一次，卡片会跟着重新自检。
   */
  @Builder
  WorkspaceSection(weight: number) {
    Column() {
      ForEach(this.workspaceKeys(), (key: string) => {
        LocalWorkspaceCard()
      }, (key: string) => key)
    }
    .width('100%')
    .layoutWeight(weight)
  }

  /** 模型与运行时配置：当前模型 + 三项运行时能力。 */
  @Builder
  ModelRuntimeCard(weight: number) {
    SectionCard({
      title: this.tr('settings.card.modelRuntime'),
      subtitle: 'Model & Runtime',
      weight: weight,
      icon: IconPaths.SLIDERS,
      iconTone: 'muted'
    }) {
      Column() {
        InfoRow({
          label: this.tr('settings.modelProvider'),
          value: this.currentNameText(),
          labelWidth: 108
        })
        InfoRow({
          label: this.tr('settings.modelName'),
          value: this.providers === null ? '' : this.providers.model,
          labelWidth: 108
        })

        Row({ space: 10 }) {
          ChipButton({
            icon: IconPaths.LINK,
            label: this.providerBusy ? this.tr('settings.testing') : this.tr('settings.testConnection'),
            tone: 'outline',
            active: !this.providerBusy && this.currentProvider() !== null,
            onTap: () => {
              this.checkCurrent();
            }
          })
        }
        .width('100%')
        .margin({ bottom: 6 })

        if (this.modelTestText.length > 0) {
          Text(this.modelTestText)
            .fontSize(12)
            .fontColor(this.modelTestTone === 'ok'
              ? AppTheme.PRIMARY_DARK
              : (this.modelTestTone === 'danger' ? AppTheme.DANGER : AppTheme.TEXT_TERTIARY))
            .width('100%')
            .margin({ bottom: 6 })
        }

        Divider()
          .color(AppTheme.BORDER_SOFT)
          .margin({ top: 6, bottom: 6 })

        InfoRow({
          label: this.tr('settings.pythonInterpreter'),
          value: this.runtime === null ? '' : this.runtime.python,
          mono: true,
          labelWidth: 108
        })
        InfoRow({
          label: this.tr('settings.condaEnv'),
          value: '',
          labelWidth: 108,
          pill: this.runtime === null
            ? this.tr('settings.pillNotDetected')
            : (this.condaOk() ? this.tr('settings.available') : this.tr('settings.pillUnconfigured')),
          tone: this.condaOk() ? 'ok' : 'warn'
        })
        InfoRow({
          label: this.tr('settings.gpuCuda'),
          value: this.gpuOk() && this.gpuList().length > 0 ? this.gpuList()[0].name : '',
          labelWidth: 108,
          pill: this.runtime === null
            ? this.tr('settings.pillNotDetected')
            : (this.gpuOk() ? this.tr('settings.available') : this.tr('settings.pillUnconfigured')),
          tone: this.gpuOk() ? 'ok' : 'warn'
        })

        if (this.providers !== null && this.providers.managed === true) {
          Text(this.tr('settings.managedByPlatform'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .width('100%')
            .margin({ top: 10 })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  /** 模型来源：列表 + 预设 + 表单。云端托管时退化成只读说明。 */
  @Builder
  ProviderCard(weight: number) {
    SectionCard({
      title: this.tr('settings.sourceList'),
      subtitle: 'Model sources',
      weight: weight,
      icon: IconPaths.BRAIN,
      iconTone: 'muted',
      actionLabel: this.providers !== null && this.providers.managed === true ? '' : this.tr('settings.newSource'),
      actionActive: !this.providerBusy,
      onAction: () => {
        this.openNew();
      }
    }) {
      Column() {
        if (this.providers !== null && this.providers.managed === true) {
          // 云端托管：来源由平台统一维护，端侧不给编辑入口，也不接触服务器密钥。
          InfoRow({ label: this.tr('settings.currentName'), value: this.tr('settings.deepseekManaged'), labelWidth: 108 })
          InfoRow({
            label: this.tr('settings.currentModel'),
            value: this.providers.model,
            labelWidth: 108
          })
          Text(this.tr('settings.managedModelHint'))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .width('100%')
            .margin({ top: 10 })
        } else {
          InfoRow({ label: this.tr('settings.keySource'), value: this.keySourceText(), labelWidth: 108 })

          ForEach(this.providers === null ? [] : this.providers.providers, (item: ModelProvider) => {
            this.ProviderRow(item)
          }, (item: ModelProvider) => `${item.id}-${item.model}-${item.has_key}-${this.pendingDelete === item.id}`)

          if (this.providers === null || this.providers.providers.length === 0) {
            EmptyHint({ text: this.tr('settings.noSource') })
          }

          this.MessageLine()
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  /** 表单单独一张卡：它出现在列表下面，和列表挤在一张卡里会被当成列表的一部分。 */
  @Builder
  ProviderFormCard() {
    SectionCard({
      title: this.providerEditId === 'new' ? this.tr('settings.newSource') : this.tr('settings.editSource'),
      subtitle: 'Model source',
      icon: IconPaths.SLIDERS,
      iconTone: 'muted'
    }) {
      this.ProviderForm()
    }
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
          StatusPill({ label: this.tr('settings.activeTag'), tone: 'ok' })
        } else if (item.key_required && !item.has_key) {
          StatusPill({ label: this.tr('settings.needKey'), tone: 'warn' })
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
        ChipButton({
          icon: IconPaths.CHECK,
          label: this.providerBusy ? this.tr('settings.saving') : this.tr('settings.save'),
          tone: 'primary',
          active: !this.providerBusy,
          onTap: () => {
            this.save();
          }
        })
        ChipButton({
          label: this.tr('common.cancel'),
          tone: 'outline',
          active: !this.providerBusy,
          onTap: () => {
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

  /** Agent 权限与行为：四条约定 + 一句脚注说清它们现在作用在哪。 */
  @Builder
  PermissionsCard(weight: number) {
    SectionCard({
      title: this.tr('settings.card.permissions'),
      subtitle: 'Agent Permissions',
      weight: weight,
      icon: IconPaths.SHIELD_CHECK,
      iconTone: 'muted'
    }) {
      Column() {
        ToggleRow({
          icon: IconPaths.DOWNLOAD,
          label: this.tr('settings.permDeps'),
          note: this.tr('settings.permDepsNote'),
          checked: this.permDeps,
          busy: this.permBusy,
          onToggle: (value: boolean) => {
            this.permDeps = value;
            this.savePermission(PREF_PERM_DEPS, value);
          }
        })
        ToggleRow({
          icon: IconPaths.CODE,
          label: this.tr('settings.permCode'),
          note: this.tr('settings.permCodeNote'),
          checked: this.permCode,
          busy: this.permBusy,
          onToggle: (value: boolean) => {
            this.permCode = value;
            this.savePermission(PREF_PERM_CODE, value);
          }
        })
        ToggleRow({
          icon: IconPaths.FLASK,
          label: this.tr('settings.permExperiment'),
          note: this.tr('settings.permExperimentNote'),
          checked: this.permExperiment,
          busy: this.permBusy,
          onToggle: (value: boolean) => {
            this.permExperiment = value;
            this.savePermission(PREF_PERM_EXPERIMENT, value);
          }
        })
        ToggleRow({
          icon: IconPaths.USER_CHECK,
          label: this.tr('settings.permConfirm'),
          note: this.tr('settings.permConfirmNote'),
          checked: this.permConfirm,
          busy: this.permBusy,
          onToggle: (value: boolean) => {
            this.permConfirm = value;
            this.savePermission(PREF_PERM_CONFIRM, value);
          }
        })

        Text(this.tr('settings.permFootnote'))
          .fontSize(11)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width('100%')
          .margin({ top: 6 })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  /** 高级信息：规则与账本，以及后端连接细节。 */
  @Builder
  AdvancedCard(weight: number) {
    SectionCard({
      title: this.tr('settings.card.advanced'),
      subtitle: 'Advanced',
      weight: weight,
      icon: IconPaths.GEAR,
      iconTone: 'muted'
    }) {
      Column() {
        Text(this.tr('settings.card.advancedSub'))
          .fontSize(11)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .width('100%')
          .margin({ bottom: 8 })

        InfoRow({ label: this.tr('settings.ruleProfile'), value: this.localReport.profile, labelWidth: 108 })
        InfoRow({
          label: this.tr('settings.ruleFields'),
          value: this.localReport.specExists ? `${this.localReport.fieldCount}` : '',
          labelWidth: 108
        })
        InfoRow({
          label: this.tr('settings.ruleGaps'),
          value: this.localReport.specExists
            ? this.trf('settings.ruleGapsValue', [
              `${this.localReport.gapCount}`,
              `${this.localReport.missingValue}`,
              `${this.localReport.missingAnchor}`
            ])
            : '',
          labelWidth: 108
        })
        InfoRow({
          label: this.tr('settings.ruleStatus'),
          value: this.localReport.specExists ? '' : this.tr('settings.missing'),
          labelWidth: 108,
          pill: this.localReport.specExists
            ? (this.localReport.ruleApproved ? this.tr('localRule.approved') : this.tr('localRule.notApproved'))
            : '',
          tone: this.localReport.ruleApproved ? 'ok' : 'warn'
        })
        InfoRow({
          label: this.tr('settings.specFingerprint'),
          value: this.localReport.specHash,
          mono: true,
          labelWidth: 108
        })
        InfoRow({
          label: this.tr('settings.ledgerEvents'),
          value: `${this.localReport.ledgerCount}`,
          labelWidth: 108
        })

        Divider()
          .color(AppTheme.BORDER_SOFT)
          .margin({ top: 6, bottom: 6 })

        InfoRow({ label: this.tr('settings.serviceAddress'), value: BASE_URL, mono: true, labelWidth: 108 })
        InfoRow({
          label: this.health !== null && this.health.mode === 'cloud'
            ? this.tr('settings.accountAuth')
            : this.tr('settings.sharedToken'),
          value: this.health !== null && this.health.mode === 'cloud'
            ? this.tr('settings.accountAuthActive')
            : (ACCESS_TOKEN.length > 0 ? this.tr('settings.configured') : this.tr('settings.tokenNotConfigured')),
          labelWidth: 108
        })
        InfoRow({
          label: this.tr('settings.health'),
          value: this.health === null ? '' : this.health.status,
          labelWidth: 108
        })
        InfoRow({
          label: this.tr('settings.backendWorkspace'),
          value: this.health === null ? '' : this.health.workspace,
          mono: true,
          labelWidth: 108
        })

        // 探测到的每一张卡：显存与驱动只在这里给，磁贴上只留一张的名字。
        if (this.gpuList().length > 0) {
          Divider()
            .color(AppTheme.BORDER_SOFT)
            .margin({ top: 6, bottom: 6 })
          ForEach(this.gpuList(), (item: GpuDevice) => {
            this.GpuRow(item)
          }, (item: GpuDevice) => item.name)
        }

        // 端侧自检失败时不能装作没有：这一页的规则与账本数字都来自那次自检。
        if (this.localError.length > 0) {
          Text(this.localError)
            .fontSize(12)
            .fontColor(AppTheme.DANGER)
            .width('100%')
            .margin({ top: 10 })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  /** 运行时细节：探测到的每一张卡。放在磁贴之后，只给需要的人看。 */
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
    .padding({ top: 10, bottom: 10 })
  }

  build() {
    Column({ space: 16 }) {
      this.Head()

      if (this.errorText.length > 0) {
        this.ErrorBanner()
      }

      this.ReadinessCard()
      this.TileGrid()
      this.LimitedStrip()

      if (this.compact) {
        this.WorkspaceSection(0)
        this.ModelRuntimeCard(0)
        this.ProviderCard(0)
        if (this.providerEditId.length > 0) {
          this.ProviderFormCard()
        }
        this.PermissionsCard(0)
        this.AdvancedCard(0)
      } else {
        Row({ space: 16 }) {
          this.WorkspaceSection(1)
          this.ModelRuntimeCard(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)

        this.ProviderCard(0)
        if (this.providerEditId.length > 0) {
          this.ProviderFormCard()
        }

        Row({ space: 16 }) {
          this.PermissionsCard(1)
          this.AdvancedCard(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
      }

      if (this.loading) {
        Text(this.tr('common.loading'))
          .fontSize(12)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 4 })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .onAreaChange((_oldArea: Area, newArea: Area) => {
      const compact: boolean = Number(newArea.width) < WIDE_MIN_WIDTH;
      if (this.compact !== compact) {
        this.compact = compact;
      }
    })
  }
}
