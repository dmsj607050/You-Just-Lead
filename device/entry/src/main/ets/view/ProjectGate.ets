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
  /** 当前云账号与余额；项目选择页也必须提供退出入口。 */
  @Prop accountUsername: string = '';
  @Prop creditBalance: number = 0;
  onSignOut: () => void = () => {
  };
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
  /** 云端项目是主路径；本地/离线工作区默认收起，但仍可从此处或设置进入。 */
  @State localToolsExpanded: boolean = false;
  /** 窄窗口隐藏较长标语，给语言切换和品牌名留出空间。 */
  @State compactHeader: boolean = false;
  @State tightHeader: boolean = false;

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

  /** 用 key 重建折叠区，避免 ArkUI Builder 保留旧子树。 */
  private localToolsKeys(): string[] {
    return [this.localToolsExpanded ? 'expanded' : 'collapsed'];
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
          AppIcon({ commands: IconPaths.FOLDER, color: AppTheme.PRIMARY, filled: true, iconSize: 22 * AppTheme.UI_SCALE })
        }
        .width(38 * AppTheme.UI_SCALE)
        .height(38 * AppTheme.UI_SCALE)
        .backgroundColor(AppTheme.PRIMARY_SOFT)
        .borderRadius(AppTheme.RADIUS_SM)

        Column() {
          Row() {
            Text(project.name)
              .fontSize(15 * AppTheme.UI_SCALE)
              .fontWeight(FontWeight.Medium)
              .fontColor(AppTheme.TEXT_PRIMARY)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            if (project.current) {
              Text(this.tr('gate.current'))
                .fontSize(11 * AppTheme.UI_SCALE)
                .fontColor(AppTheme.PRIMARY_DARK)
                .backgroundColor(AppTheme.PRIMARY_SOFT)
                .borderRadius(6 * AppTheme.UI_SCALE)
                .padding({ left: 8 * AppTheme.UI_SCALE, right: 8 * AppTheme.UI_SCALE, top: 2 * AppTheme.UI_SCALE, bottom: 2 * AppTheme.UI_SCALE })
                .margin({ left: 8 * AppTheme.UI_SCALE })
            }
          }
          .alignItems(VerticalAlign.Center)

          Text(this.trf('gate.createdAt', [formatTimestamp(project.created_at)]))
            .fontSize(12 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_TERTIARY)
            .margin({ top: 4 * AppTheme.UI_SCALE })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        .margin({ left: 12 * AppTheme.UI_SCALE })

        Text(this.tr('gate.enter'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.PRIMARY)
        AppIcon({ commands: IconPaths.CHEVRON_SMALL, color: AppTheme.PRIMARY, filled: false, iconSize: 14 * AppTheme.UI_SCALE })
          .margin({ left: 4 * AppTheme.UI_SCALE })
      }
      .layoutWeight(1)
      .alignItems(VerticalAlign.Center)
      .onClick(() => {
        this.enter(project);
      })

      if (this.pendingDeleteId === project.id) {
        Text(this.tr('common.cancel'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_SECONDARY)
          .padding({ left: 10 * AppTheme.UI_SCALE, right: 10 * AppTheme.UI_SCALE, top: 6 * AppTheme.UI_SCALE, bottom: 6 * AppTheme.UI_SCALE })
          .onClick(() => {
            this.pendingDeleteId = '';
          })
        Text(this.tr('gate.deleteConfirm'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.DANGER)
          .padding({ left: 10 * AppTheme.UI_SCALE, right: 2 * AppTheme.UI_SCALE, top: 6 * AppTheme.UI_SCALE, bottom: 6 * AppTheme.UI_SCALE })
          .onClick(() => {
            this.remove(project);
          })
      } else {
        Text(this.tr('gate.delete'))
          .fontSize(13 * AppTheme.UI_SCALE)
          .fontColor(AppTheme.TEXT_TERTIARY)
          .padding({ left: 14 * AppTheme.UI_SCALE, right: 2 * AppTheme.UI_SCALE, top: 6 * AppTheme.UI_SCALE, bottom: 6 * AppTheme.UI_SCALE })
          .onClick(() => {
            this.pendingDeleteId = project.id;
          })
      }
    }
    .width('100%')
    .padding({ top: 14 * AppTheme.UI_SCALE, bottom: 14 * AppTheme.UI_SCALE })
    .alignItems(VerticalAlign.Center)
    .border({ width: { bottom: 1 }, color: AppTheme.BORDER_SOFT })
  }

  build() {
    Column() {
      Row() {
        // 品牌标记（无文字版 logo）；标语走 i18n，切换语言时才不会留着中文。
        Image($r('app.media.logo_mark'))
          .width(this.tightHeader ? 24 * AppTheme.UI_SCALE : 30 * AppTheme.UI_SCALE)
          .height(this.tightHeader ? 24 * AppTheme.UI_SCALE : 30 * AppTheme.UI_SCALE)
          .objectFit(ImageFit.Contain)
        Text('You Just Lead')
          .fontSize(this.tightHeader ? 16 * AppTheme.UI_SCALE : (this.compactHeader ? 17 * AppTheme.UI_SCALE : 19 * AppTheme.UI_SCALE))
          .fontWeight(FontWeight.Bold)
          .fontColor(AppTheme.TEXT_PRIMARY)
          .margin({ left: this.tightHeader ? 8 * AppTheme.UI_SCALE : 12 * AppTheme.UI_SCALE })
        if (!this.compactHeader) {
          Divider()
            .vertical(true)
            .height(20 * AppTheme.UI_SCALE)
            .color(AppTheme.BORDER)
            .margin({ left: 16 * AppTheme.UI_SCALE, right: 16 * AppTheme.UI_SCALE })
          Text(this.tr('topbar.tagline'))
            .fontSize(14 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
        }

        Blank()

        // 还没进工作台就没有账户菜单，语言切换留在这里，免得选项目时被语言卡住。
        Row() {
          AppIcon({ commands: IconPaths.GLOBE, color: AppTheme.TEXT_SECONDARY, filled: false, iconSize: this.tightHeader ? 16 : 18 })
          Text(langName(this.lang))
            .fontSize(13 * AppTheme.UI_SCALE)
            .fontColor(AppTheme.TEXT_SECONDARY)
            .margin({ left: this.tightHeader ? 6 * AppTheme.UI_SCALE : 8 * AppTheme.UI_SCALE })
        }
        .height(34 * AppTheme.UI_SCALE)
        .padding({ left: this.tightHeader ? 8 * AppTheme.UI_SCALE : 12 * AppTheme.UI_SCALE, right: this.tightHeader ? 8 * AppTheme.UI_SCALE : 12 * AppTheme.UI_SCALE })
        .borderRadius(AppTheme.RADIUS_SM)
        .alignItems(VerticalAlign.Center)
        .onClick(() => {
          setLang(this.lang === LANG_EN ? LANG_ZH : LANG_EN);
        })
      }
      .width('100%')
      .height(AppTheme.TOPBAR_HEIGHT)
      .padding({ left: this.tightHeader ? 12 * AppTheme.UI_SCALE : (this.compactHeader ? 16 * AppTheme.UI_SCALE : 24 * AppTheme.UI_SCALE), right: this.tightHeader ? 12 * AppTheme.UI_SCALE : (this.compactHeader ? 16 * AppTheme.UI_SCALE : 24 * AppTheme.UI_SCALE) })
      .backgroundColor(AppTheme.SURFACE)
      .alignItems(VerticalAlign.Center)
      .onAreaChange((_oldArea: Area, newArea: Area) => {
        const width = Number(newArea.width);
        const compact = width < 640;
        const tight = width < 400;
        if (this.compactHeader !== compact) {
          this.compactHeader = compact;
        }
        if (this.tightHeader !== tight) {
          this.tightHeader = tight;
        }
      })

      Divider().color(AppTheme.BORDER)

      Scroll() {
        Column() {
          Column() {
            Text(this.tr('gate.title'))
              .fontSize(26 * AppTheme.UI_SCALE)
              .fontWeight(FontWeight.Bold)
              .fontColor(AppTheme.TEXT_PRIMARY)

            Row() {
              Column() {
                Text(this.accountUsername)
                  .fontSize(14 * AppTheme.UI_SCALE)
                  .fontWeight(FontWeight.Medium)
                  .fontColor(AppTheme.TEXT_PRIMARY)
                Text(`${this.tr('auth.balance')}：${this.creditBalance.toFixed(2)}`)
                  .fontSize(12 * AppTheme.UI_SCALE)
                  .fontColor(AppTheme.TEXT_TERTIARY)
                  .margin({ top: 4 * AppTheme.UI_SCALE })
              }
              .alignItems(HorizontalAlign.Start)

              Blank()

              Text(this.tr('auth.signOut'))
                .fontSize(13 * AppTheme.UI_SCALE)
                .fontColor(AppTheme.PRIMARY_DARK)
                .onClick(() => {
                  this.onSignOut();
                })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
            .padding(16 * AppTheme.UI_SCALE)
            .margin({ top: 16 * AppTheme.UI_SCALE })
            .backgroundColor(AppTheme.SURFACE)
            .borderRadius(AppTheme.RADIUS)
            .border({ width: 1, color: AppTheme.BORDER })

            if (this.errorText.length > 0) {
              Column() {
                Text(this.tr('common.connectionFailed'))
                  .fontSize(14 * AppTheme.UI_SCALE)
                  .fontWeight(FontWeight.Medium)
                  .fontColor(AppTheme.DANGER)
                Text(this.errorText)
                  .fontSize(12 * AppTheme.UI_SCALE)
                  .fontColor(AppTheme.DANGER)
                  .margin({ top: 6 * AppTheme.UI_SCALE })
                Text(this.tr('common.retry'))
                  .fontSize(13 * AppTheme.UI_SCALE)
                  .fontColor(AppTheme.PRIMARY)
                  .margin({ top: 10 * AppTheme.UI_SCALE })
                  .onClick(() => {
                    this.load();
                  })
              }
              .alignItems(HorizontalAlign.Start)
              .width('100%')
              .padding(16 * AppTheme.UI_SCALE)
              .backgroundColor(AppTheme.DANGER_SOFT)
              .borderRadius(AppTheme.RADIUS)
              .margin({ top: 22 * AppTheme.UI_SCALE })
            }

            Column() {
              if (this.projects.length === 0 && !this.loading) {
                Text(this.tr('gate.empty'))
                  .fontSize(13 * AppTheme.UI_SCALE)
                  .fontColor(AppTheme.TEXT_TERTIARY)
                  .width('100%')
                  .padding({ top: 4 * AppTheme.UI_SCALE, bottom: 4 * AppTheme.UI_SCALE })
              }
              ForEach(this.projects, (project: ProjectSummary) => {
                this.ProjectRow(project)
              }, (project: ProjectSummary) => project.id)
            }
            .width('100%')
            .margin({ top: 18 * AppTheme.UI_SCALE })
            .padding({ left: 20 * AppTheme.UI_SCALE, right: 20 * AppTheme.UI_SCALE })
            .backgroundColor(AppTheme.SURFACE)
            .borderRadius(AppTheme.RADIUS_LG)
            .border({ width: 1, color: AppTheme.BORDER })

            Column() {
              Text(this.tr('gate.newTitle'))
                .fontSize(15 * AppTheme.UI_SCALE)
                .fontWeight(FontWeight.Medium)
                .fontColor(AppTheme.TEXT_PRIMARY)

              Row() {
                TextInput({ text: this.newName, placeholder: this.tr('gate.namePlaceholder') })
                  .layoutWeight(1)
                  .height(38 * AppTheme.UI_SCALE)
                  .fontSize(13 * AppTheme.UI_SCALE)
                  .backgroundColor(AppTheme.PAGE_BG)
                  .borderRadius(AppTheme.RADIUS_SM)
                  .onChange((value: string) => {
                    this.newName = value;
                    this.nameError = '';
                  })
                Button(this.creating ? this.tr('gate.creating') : this.tr('gate.create'))
                  .height(38 * AppTheme.UI_SCALE)
                  .fontSize(13 * AppTheme.UI_SCALE)
                  .fontColor(Color.White)
                  .backgroundColor(AppTheme.PRIMARY)
                  .margin({ left: 10 * AppTheme.UI_SCALE })
                  .enabled(!this.creating)
                  .onClick(() => {
                    this.createAndEnter();
                  })
              }
              .width('100%')
              .margin({ top: 14 * AppTheme.UI_SCALE })
              .alignItems(VerticalAlign.Center)

              if (this.nameError.length > 0) {
                Text(this.nameError)
                  .fontSize(12 * AppTheme.UI_SCALE)
                  .fontColor(AppTheme.DANGER)
                  .margin({ top: 8 * AppTheme.UI_SCALE })
              }

              Text(this.tr('gate.hint'))
                .fontSize(12 * AppTheme.UI_SCALE)
                .fontColor(AppTheme.TEXT_TERTIARY)
                .margin({ top: 12 * AppTheme.UI_SCALE })
            }
            .alignItems(HorizontalAlign.Start)
            .width('100%')
            .padding(20 * AppTheme.UI_SCALE)
            .margin({ top: 20 * AppTheme.UI_SCALE })
            .backgroundColor(AppTheme.SURFACE)
            .borderRadius(AppTheme.RADIUS_LG)
            .border({ width: 1, color: AppTheme.BORDER })

            // 云端新用户先看到项目主路径；本地/离线工具保留在折叠区，完整能力也在设置页可用。
            Column() {
              Row() {
                Column() {
                  Text(this.tr('gate.localToolsTitle'))
                    .fontSize(14 * AppTheme.UI_SCALE)
                    .fontWeight(FontWeight.Medium)
                    .fontColor(AppTheme.TEXT_SECONDARY)
                  Text(this.tr('gate.localToolsHint'))
                    .fontSize(12 * AppTheme.UI_SCALE)
                    .fontColor(AppTheme.TEXT_TERTIARY)
                    .margin({ top: 4 * AppTheme.UI_SCALE })
                }
                .alignItems(HorizontalAlign.Start)
                .layoutWeight(1)

                Text(this.localToolsExpanded ? this.tr('gate.localToolsCollapse') : this.tr('gate.localToolsExpand'))
                  .fontSize(13 * AppTheme.UI_SCALE)
                  .fontColor(AppTheme.PRIMARY)
                  .margin({ left: 12 * AppTheme.UI_SCALE })
              }
              .width('100%')
              .alignItems(VerticalAlign.Center)
              .padding(16 * AppTheme.UI_SCALE)
              .onClick(() => {
                this.localToolsExpanded = !this.localToolsExpanded;
              })

              ForEach(this.localToolsKeys(), (key: string) => {
                if (key === 'expanded') {
                  LocalWorkspaceCard()
                    .margin({ top: 12 * AppTheme.UI_SCALE })
                }
              }, (key: string) => key)
            }
            .width('100%')
            .margin({ top: 20 * AppTheme.UI_SCALE })
            .backgroundColor(AppTheme.SURFACE)
            .borderRadius(AppTheme.RADIUS_LG)
            .border({ width: 1, color: AppTheme.BORDER })

            if (this.loading) {
              Text(this.tr('common.loading'))
                .fontSize(12 * AppTheme.UI_SCALE)
                .fontColor(AppTheme.TEXT_TERTIARY)
                .margin({ top: 14 * AppTheme.UI_SCALE })
            }
          }
          .alignItems(HorizontalAlign.Start)
          .width('100%')
          .constraintSize({ maxWidth: 720 })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Center)
        .padding({ left: 32 * AppTheme.UI_SCALE, right: 32 * AppTheme.UI_SCALE, top: 44 * AppTheme.UI_SCALE, bottom: 44 * AppTheme.UI_SCALE })
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
