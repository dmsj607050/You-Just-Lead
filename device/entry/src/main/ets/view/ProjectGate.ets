import { createProject, deleteProject, fetchProjects, ProjectSummary, selectProject } from '../common/BackendClient';
import AppTheme from '../common/AppTheme';
import { formatTimestamp } from '../common/Format';
import IconPaths from '../common/IconPaths';
import { LANG_EN, LANG_ZH, langName, setLang, tFor, tfFor } from '../common/I18n';
import { AppIcon } from './AppIcon';
import { LocalWorkspaceCard } from './LocalWorkspaceCard';

/**
 * 项目选择页：应用启动后的第一屏。
 *
 * 项目是侧栏那些模块的上一层容器（像 IDE 里先开工程再进工作区），所以它单独占一屏，
 * 而不是侧栏里的一个平级导航项。这里只做两件事：列出后端已有的项目、新建一个并进入。
 * 选中由后端记录，进入工作台之后所有接口都作用在那个项目的工作区上。
 */
@Component
export struct ProjectGate {
  /**
   * 当前语言。ArkUI 只重建读到状态变量的节点，所以本组件所有文案都走 this.tr()，
   * 由它读一次 this.lang，等于把用到的节点登记到语言变化上。
   */
  @StorageLink('lang') lang: string = 'zh';
  /** 选中某个项目后进入工作台。 */
  onEnter: (project: ProjectSummary) => void = () => {
  };

  @State projects: ProjectSummary[] = [];
  @State loading: boolean = false;
  @State errorText: string = '';
  @State newName: string = '';
  @State nameError: string = '';
  @State creating: boolean = false;
  /** 正在行内二次确认删除的项目 id；空串表示没有。 */
  @State pendingDeleteId: string = '';

  aboutToAppear(): void {
    this.load();
  }

  /** 取文案：读一次 lang，让调用它的节点订阅语言变化。 */
  private tr(key: string): string {
    return tFor(this.lang, key);
  }

  /** 带占位符取文案。 */
  private trf(key: string, args: string[]): string {
    return tfFor(this.lang, key, args);
  }

  /** 列出后端已有的项目。 */
  async load(): Promise<void> {
    this.loading = true;
    this.errorText = '';
    try {
      const listed = await fetchProjects();
      this.projects = listed.projects;
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.loading = false;
    }
  }

  /** 进入项目：当前项目直接进，其它项目先让后端切换再进。 */
  async enter(project: ProjectSummary): Promise<void> {
    this.errorText = '';
    if (project.current) {
      this.onEnter(project);
      return;
    }
    this.loading = true;
    try {
      const selected = await selectProject(project.id);
      this.onEnter(selected.project === null ? project : selected.project);
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.loading = false;
    }
  }

  /** 新建项目：后端建好工作区骨架并设为当前项目，随后直接进入。 */
  async createAndEnter(): Promise<void> {
    const name: string = this.newName.trim();
    if (name.length === 0 || name.length > 60) {
      this.nameError = this.tr('gate.nameRequired');
      return;
    }
    this.nameError = '';
    this.errorText = '';
    this.creating = true;
    try {
      const created = await createProject(name);
      this.newName = '';
      this.onEnter(created.project === null ? created.projects[created.projects.length - 1] : created.project);
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.creating = false;
    }
  }

  /** 删除项目：后端会连工作区目录一起删掉，删不掉时把原因显示出来。 */
  async remove(project: ProjectSummary): Promise<void> {
    this.errorText = '';
    this.pendingDeleteId = '';
    this.loading = true;
    try {
      const remaining = await deleteProject(project.id);
      this.projects = remaining.projects;
    } catch (err) {
      const error = err as Error;
      this.errorText = error.message;
    } finally {
      this.loading = false;
    }
  }

  /** 项目行：左侧整块用于进入；右侧「删除」在行内二次确认，不弹对话框。 */
  @Builder
  ProjectRow(project: ProjectSummary) {
    Row() {
      Row() {
        Stack({ alignContent: Alignment.Center }) {
          AppIcon({ commands: IconPaths.FOLDER, color: AppTheme.PRIMARY, filled: true, iconSize: 22 })
        }
        .width(38)
        .height(38)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(AppTheme.RADIUS_SM)

        Column() {
          Row() {
            Text(project.name)
              .fontSize(15)
              .fontWeight(FontWeight.Medium)
              .fontColor(AppTheme.TEXT_PRIMARY)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            if (project.current) {
              Text(this.tr('gate.current'))
                .fontSize(11)
                .fontColor(AppTheme.PRIMARY_DARK)
                .backgroundColor(AppTheme.PRIMARY_SOFT)
                .borderRadius(6)
                .padding({ left: 8, right: 8, top: 2, bottom: 2 })
                .margin({ left: 8 })
            }
          }
          .alignItems(VerticalAlign.Center)

          Text(this.trf('gate.createdAt', [formatTimestamp(project.created_at)]))
            .fontSize(12)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 4 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        .margin({ left: 12 })

        Text(this.tr('gate.enter'))
          .fontSize(13)
          .fontColor(AppTheme.PRIMARY)
        AppIcon({ commands: IconPaths.CHEVRON_SMALL, color: AppTheme.PRIMARY, filled: false, iconSize: 14 })
          .margin({ left: 4 })
      }
      .layoutWeight(1)
      .alignItems(VerticalAlign.Center)
      .onClick(() => {
        this.enter(project);
      })

      if (this.pendingDeleteId === project.id) {
        Text(this.tr('common.cancel'))
          .fontSize(13)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .padding({ left: 10, right: 10, top: 6, bottom: 6 })
          .onClick(() => {
            this.pendingDeleteId = '';
          })
        Text(this.tr('gate.deleteConfirm'))
          .fontSize(13)
          .fontColor(AppTheme.DANGER)
          .padding({ left: 10, right: 2, top: 6, bottom: 6 })
          .onClick(() => {
            this.remove(project);
          })
      } else {
        Text(this.tr('gate.delete'))
          .fontSize(13)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .padding({ left: 14, right: 2, top: 6, bottom: 6 })
          .onClick(() => {
            this.pendingDeleteId = project.id;
          })
      }
    }
    .width('100%')
    .padding({ top: 14, bottom: 14 })
    .alignItems(VerticalAlign.Center)
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  build() {
    Column() {
      Row() {
        // 品牌标记（无文字版 logo）；标语走 i18n，切换语言时才不会留着中文。
        Image($r('app.media.logo_mark'))
          .width(30)
          .height(30)
          .objectFit(ImageFit.Contain)
        Text('You Just Lead')
          .fontSize(19)
          .fontWeight(FontWeight.Bold)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .margin({ left: 12 })
        Divider()
          .vertical(true)
          .height(20)
          .color(AppTheme.BORDER)
          .margin({ left: 16, right: 16 })
        Text(this.tr('topbar.tagline'))
          .fontSize(14)
          .fontColor(AppTheme.TEXT_SECONDARY)

        Blank()

        // 还没进工作台就没有账户菜单，语言切换留在这里，免得选项目时被语言卡住。
        Row() {
          AppIcon({ commands: IconPaths.GLOBE, color: AppTheme.TEXT_SECONDARY, filled: false, iconSize: 18 })
          Text(langName(this.lang))
            .fontSize(13)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .margin({ left: 8 })
        }
        .height(34)
        .padding({ left: 12, right: 12 })
        .borderRadius(AppTheme.RADIUS_SM)
        .alignItems(VerticalAlign.Center)
        .onClick(() => {
          setLang(this.lang === LANG_EN ? LANG_ZH : LANG_EN);
        })
      }
      .width('100%')
      .height(AppTheme.TOPBAR_HEIGHT)
      .padding({ left: 24, right: 24 })
      .backgroundColor(AppTheme.SURFACE)
      .alignItems(VerticalAlign.Center)

      Divider().color(AppTheme.BORDER)

      Scroll() {
        Column() {
          Column() {
            Text(this.tr('gate.title'))
              .fontSize(26)
              .fontWeight(FontWeight.Bold)
              .fontColor(AppTheme.TEXT_PRIMARY)
            Text(this.tr('gate.subtitle'))
              .fontSize(13)
              .fontColor(AppTheme.TEXT_SECONDARY)
              .margin({ top: 10 })

            if (this.errorText.length > 0) {
              Column() {
                Text(this.tr('common.connectionFailed'))
                  .fontSize(14)
                  .fontWeight(FontWeight.Medium)
                  .fontColor(AppTheme.DANGER)
                Text(this.errorText)
                  .fontSize(12)
                  .fontColor(AppTheme.DANGER)
                  .margin({ top: 6 })
                Text(this.tr('common.retry'))
                  .fontSize(13)
                  .fontColor(AppTheme.PRIMARY)
                  .margin({ top: 10 })
                  .onClick(() => {
                    this.load();
                  })
              }
              .alignItems(HorizontalAlign.Start)
              .width('100%')
              .padding(16)
              .backgroundColor(AppTheme.DANGER_SOFT)
              .borderRadius(AppTheme.RADIUS)
              .margin({ top: 22 })
            }

            Column() {
              if (this.projects.length === 0 && !this.loading) {
                Text(this.tr('gate.empty'))
                  .fontSize(13)
                  .fontColor(AppTheme.TEXT_TERTIARY)
                  .width('100%')
                  .padding({ top: 4, bottom: 4 })
              }
              ForEach(this.projects, (project: ProjectSummary) => {
                this.ProjectRow(project)
              }, (project: ProjectSummary) => project.id)
            }
            .width('100%')
            .margin({ top: 18 })
            .padding({ left: 20, right: 20 })
            .backgroundColor(AppTheme.SURFACE)
            .borderRadius(AppTheme.RADIUS_LG)
            .border({ width: 1, color: AppTheme.BORDER })

            Column() {
              Text(this.tr('gate.newTitle'))
                .fontSize(15)
                .fontWeight(FontWeight.Medium)
                .fontColor(AppTheme.TEXT_PRIMARY)

              Row() {
                TextInput({ text: this.newName, placeholder: this.tr('gate.namePlaceholder') })
                  .layoutWeight(1)
                  .height(38)
                  .fontSize(13)
                  .backgroundColor(AppTheme.PAGE_BG)
                  .borderRadius(AppTheme.RADIUS_SM)
                  .onChange((value: string) => {
                    this.newName = value;
                    this.nameError = '';
                  })
                Button(this.creating ? this.tr('gate.creating') : this.tr('gate.create'))
                  .height(38)
                  .fontSize(13)
                  .fontColor(Color.White)
                  .backgroundColor(AppTheme.PRIMARY)
                  .margin({ left: 10 })
                  .enabled(!this.creating)
                  .onClick(() => {
                    this.createAndEnter();
                  })
              }
              .width('100%')
              .margin({ top: 14 })
              .alignItems(VerticalAlign.Center)

              if (this.nameError.length > 0) {
                Text(this.nameError)
                  .fontSize(12)
                  .fontColor(AppTheme.DANGER)
                  .margin({ top: 8 })
              }

              Text(this.tr('gate.hint'))
                .fontSize(12)
                .fontColor(AppTheme.TEXT_TERTIARY)
                .margin({ top: 12 })
            }
            .alignItems(HorizontalAlign.Start)
            .width('100%')
            .padding(20)
            .margin({ top: 20 })
            .backgroundColor(AppTheme.SURFACE)
            .borderRadius(AppTheme.RADIUS_LG)
            .border({ width: 1, color: AppTheme.BORDER })

            // 本地工作区放在启动页：它是端侧自足的入口，后端没起来时也必须走得到。
            LocalWorkspaceCard()
              .margin({ top: 20 })

            if (this.loading) {
              Text(this.tr('common.loading'))
                .fontSize(12)
                .fontColor(AppTheme.TEXT_TERTIARY)
                .margin({ top: 14 })
            }
          }
          .alignItems(HorizontalAlign.Start)
          .width('100%')
          .constraintSize({ maxWidth: 720 })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Center)
        .padding({ left: 32, right: 32, top: 44, bottom: 44 })
      }
      .layoutWeight(1)
      .align(Alignment.Top)
      .scrollBar(BarState.Auto)
    }
    .width('100%')
    .height('100%')
    .backgroundColor(AppTheme.PAGE_BG)
  }
}
