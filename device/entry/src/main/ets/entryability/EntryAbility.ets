import { AbilityConstant, ConfigurationConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { initLang } from '../common/I18n';

const DOMAIN = 0x0000;

/** 外部唤起时可以带的参数名：一个待确认的问题。 */
const PARAM_QUESTION = 'question';

/** 界面从 AppStorage 里取这个键，预填到提问框。装饰器只接受字面量，两边需保持一致。 */
const PENDING_QUESTION_KEY = 'pendingQuestion';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onCreate');
    this.publishQuestion(want);
    // onCreate 是同步的，不能 await；语言就位后会通过 AppStorage 广播让界面重绘。
    initLang(this.context).catch((err: Error) => {
      hilog.error(DOMAIN, 'testTag', 'Failed to init language. Cause: %{public}s', err.message);
    });
  }

  /**
   * 应用已在运行时再次被唤起。
   *
   * 这样桌面入口、其他应用或系统意图都可以把问题交给本应用，
   * 应用只预填，是否真的提交仍然由用户点「提问」决定。
   */
  onNewWant(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onNewWant');
    this.publishQuestion(want);
  }

  onDestroy(): void {
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onDestroy');
  }

  /** 把 want 里的问题放进 AppStorage，供界面读取。 */
  private publishQuestion(want: Want): void {
    const parameters: Record<string, Object> | undefined = want.parameters;
    if (parameters === undefined) {
      return;
    }
    const value: Object = parameters[PARAM_QUESTION];
    if (typeof value !== 'string' || value.length === 0) {
      return;
    }
    AppStorage.setOrCreate(PENDING_QUESTION_KEY, value);
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    // Main window is created, set main page for this ability
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onWindowStageCreate');

    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        hilog.error(DOMAIN, 'testTag', 'Failed to load the content. Cause: %{public}s', JSON.stringify(err));
        return;
      }
      hilog.info(DOMAIN, 'testTag', 'Succeeded in loading the content.');
    });

    try {
      this.context.getApplicationContext().setColorMode(ConfigurationConstant.ColorMode.COLOR_MODE_NOT_SET);
    } catch (err) {
      hilog.error(DOMAIN, 'testTag', 'Failed to set colorMode. Cause: %{public}s', JSON.stringify(err));
    }
  }

  onWindowStageDestroy(): void {
    // Main window is destroyed, release UI related resources
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onWindowStageDestroy');
  }

  onForeground(): void {
    // Ability has brought to foreground
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onForeground');
  }

  onBackground(): void {
    // Ability has back to background
    hilog.info(DOMAIN, 'testTag', '%{public}s', 'Ability onBackground');
  }
}
