import AppTheme from '../common/AppTheme';

/**
 * 自绘图标。
 *
 * 全部图形来自 IconPaths 的直线指令，不依赖图片资源，
 * 因此任何分辨率下都不会缺图或模糊。
 */
@Component
export struct AppIcon {
  /** 与坐标系一致的路径指令。 */
  @Prop commands: string = '';
  @Prop color: string = AppTheme.TEXT_PRIMARY;
  /** true 表示填充绘制，false 表示描边绘制。 */
  @Prop filled: boolean = false;
  @Prop iconSize: number = 24;

  build() {
    Stack() {
      Path()
        .width(this.iconSize)
        .height(this.iconSize)
        .commands(this.commands)
        .fill(this.filled ? this.color : Color.Transparent)
        .stroke(this.filled ? Color.Transparent : this.color)
        .strokeWidth(1.5)
    }
    .width(this.iconSize)
    .height(this.iconSize)
  }
}
