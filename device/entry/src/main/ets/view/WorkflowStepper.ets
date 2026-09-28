import AppTheme from '../common/AppTheme';
import { tFor } from '../common/I18n';
import { StepSpec } from '../common/ViewTypes';

/**
 * 八个环节的文案键，顺序即流程顺序。
 *
 * 这里存键名而不是中文：模块常量在导入时就求值一次，写死中文会把语言定死；
 * 由工作流步骤条渲染时取 `this.tr()`，见 StepDot。
 */
const STEP_KEYS: string[] = ['step.rules', 'step.audit', 'step.research', 'step.baseline',
  'step.iteration', 'step.diagnosis', 'step.approvals', 'step.paper'];

/** 没有拿到后端数据时的初始状态：首步进行中，其余等待，保证结构完整。 */
export function initialSteps(): StepSpec[] {
  const steps: StepSpec[] = [];
  for (let index = 0; index < STEP_KEYS.length; index++) {
    steps.push({ label: STEP_KEYS[index], status: index === 0 ? 'active' : 'pending' });
  }
  return steps;
}

/**
 * 由后端各环节的真实状态推导步骤条。
 *
 * 每个环节的完成条件独立判断，第一个未完成的环节标记为进行中。
 */
export function deriveSteps(rules: string, audit: string, research: string,
  baseline: string, approvals: string, completed: number): StepSpec[] {
  const done: boolean[] = [
    rules === 'approved',
    audit === 'complete',
    research === 'complete',
    baseline === 'complete',
    completed > 0,
    completed > 0,
    approvals === 'recorded',
    false
  ];
  const steps: StepSpec[] = [];
  let activeAssigned: boolean = false;
  for (let index = 0; index < STEP_KEYS.length; index++) {
    let status: string = 'pending';
    if (done[index]) {
      status = 'completed';
    } else if (!activeAssigned) {
      status = 'active';
      activeAssigned = true;
    }
    steps.push({ label: STEP_KEYS[index], status: status });
  }
  return steps;
}

/** 步骤条：已完成 = 绿圆对勾，进行中 = 绿色药丸，未开始 = 空心圆。 */
@Component
export struct WorkflowStepper {
  /** 步骤数组：label 存的是 `step.*` 文案键，渲染时取 this.tr()。 */
  @Prop steps: StepSpec[] = [];
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  @Builder
  StepDot(step: StepSpec) {
    Column() {
      Stack({ alignContent: Alignment.Center }) {
        if (step.status === 'active') {
          Row() {
            Row().width(7).height(7).borderRadius(4).backgroundColor('#FFFFFF')
            Text(this.tr(step.label))
              .fontSize(13)
              .fontWeight(FontWeight.Medium)
              .fontColor('#FFFFFF')
              .margin({ left: 7 })
          }
          .height(30)
          .padding({ left: 13, right: 15 })
          .borderRadius(15)
          .backgroundColor(AppTheme.PRIMARY)
          .alignItems(VerticalAlign.Center)
        } else if (step.status === 'completed') {
          Row()
            .width(26)
            .height(26)
            .borderRadius(13)
            .backgroundColor(AppTheme.PRIMARY)
          Text('✓')
            .fontSize(13)
            .fontColor(Color.White)
        } else {
          Row()
            .width(26)
            .height(26)
            .borderRadius(13)
            .backgroundColor(AppTheme.SURFACE)
            .border({ width: 1, color: AppTheme.BORDER })
          Row().width(5).height(5).borderRadius(3).backgroundColor(AppTheme.TEXT_TERTIARY)
        }
      }
      .height(30)

      if (step.status === 'active') {
        Text(this.tr('step.inProgress'))
          .fontSize(11)
          .fontColor(AppTheme.PRIMARY)
          .margin({ top: 8 })
      } else {
        Text(this.tr(step.label))
          .fontSize(12)
          .fontColor(step.status === 'pending' ? AppTheme.TEXT_TERTIARY : AppTheme.TEXT_PRIMARY)
          .margin({ top: 8 })
          .maxLines(1)
        Text(step.status === 'completed' ? this.tr('step.completed') : this.tr('step.notStarted'))
          .fontSize(11)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .margin({ top: 3 })
          .maxLines(1)
      }
    }
    .width(step.status === 'active' ? 104 : 74)
    .alignItems(HorizontalAlign.Center)
  }

  build() {
    Row() {
      ForEach(this.steps, (step: StepSpec, index: number) => {
        if (index > 0) {
          Row() {
            Divider().strokeWidth(1).color(AppTheme.BORDER)
          }
          .layoutWeight(1)
          .margin({ bottom: 30 })
        }
        this.StepDot(step)
      }, (step: StepSpec, index: number) => `${index}-${step.label}-${step.status}`)
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
  }
}
