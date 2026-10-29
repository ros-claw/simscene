# 本机 NVIDIA 参考资料与使用边界

用户提供的参考目录包括 `/data/omniverse/isaac-sim-6.2.0`、
`/data/omniverse/usd-search` 和 `/data/omniverse/usd-content-agents`。
本机 Isaac `VERSION` 标识为 `6.2.0-rc.14+release.52805.02189a84.gl`；
这与已经完成的一些 6.0.1 测试是两个独立的运行环境。

- USD Search 的 `skills/search` 和 `skills/inspect-asset` 描述了简短查询、
  候选匹配判断、缩略图、结构与依赖检查。插件默认使用托管网关，
  查询不要求下载全库；选择后再获取，依赖不完整时应明确报告。
  本机实测选取 6.2 的 Kawasaki、Franka 和 UR10 后，索引打包最初只
  返回根文件；插件按各 USD 层的路径补取同源依赖，包括相邻的夹爪
  资产。三者在配置 6.2 运行时后均报告 `resolved_with_runtime`，
  依赖清单与先前失败记录见
  [usd-search-62-dependency-repair](../evidence/usd-search-62-dependency-repair/)。
  其中系统 MDL 由 Isaac 运行时提供，并不表示包完全独立。
- Isaac 的 `skills/manipulation-ik`、`skills/motion-generation` 和
  `skills/physics-simulation` 强调实际物体的抓取、抬升、释放、碰撞
  与轨迹证据。插件提供实验性的 cuMotion 绑定和独立采样检查；
  可达或无报告接触不代表连续扫掠路径或真实机器人安全。
- Isaac 的 `skills/isaac-sim-rendering` 建议显式环境光与主光、观察
  实际画面并校准曝光。插件支持穹顶、方向、球形和矩形灯；最终
  画面必须在实际运行中检查。
- USD Content Agents 的 `content-workflow-physics` 和
  `content-workflow-validation` 提供原始资产保留、衍生层与证据驱动
  审核的参考。该目录是独立参考实现，并非本插件的必需运行时；
  本机尚未安装其 `content-workflow-cli`，不能声称已执行其工作流。
  如需接入，应先按其根目录说明完成依赖、认证与渲染后端检查，
  并保留该工作流自己的证据和版本信息。

这些内容是对本机官方材料的参考与适配，不表示本插件已经调用或
完整实现了所有官方技能。实际运行、未通过的试验和当前限制见
[validation.md](validation.md)。
