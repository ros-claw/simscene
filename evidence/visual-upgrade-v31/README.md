# 原生高清与组合复用验证

本次源代码及技能冻结后，执行了实际三臂完整运行和空场景维修工作台组合。公开目录保存精选摘要；本工作站还有 `archives/` 下的源运行、case、原帧、逐帧清单、过程记录与完整工具返回，含第三方模型，不进入Git。

- [三臂物理/输入/输出检查](precision-verification.json)：9/9、3件/臂、完整离散碰撞审计。
- [原case与物理不变量比较](case-origin.json)：只重绑来源scene哈希。
- [工作台冻结条件检查](maintenance-verification.json)：空场景、两排料盘、在线来源绑定、三个真实落料和原生录像。
- [冻结时文件SHA](frozen-implementation.json)、[最终复核](freeze-final-verification.json)：核心与两个技能未因第二个场景变化。其后独立修复便携包的Pillow版本选择。
- [10秒同动作对照](comparison.json)：640×480/6、1080p30、Quality和DLAA。实际生效的参数有读回；不是隔离的性能基准。
- [Panda侧机位短运行](panda-side-verification.json)：完整性通过，动作无遮挡；不是完整九件验收。
- [公开交付摘要](delivery-summary.json)：最终视频与测试结果。

工作台测试由同一活动Agent使用真实MCP执行，不称为独立新Agent评测。动态工件是已有box，在线工业零件是陈列道具。CPU PhysX、A6000和Isaac 6.2 RC环境如实记录，未做第二台机器或4K验证。完整性锁不能代替物理检查。

首个曝光运行、首次红色错误材质、一次选错候选、打包Pillow动态库失败和第一次剪辑遮挡均保留在本地记录。报告见 [本轮实施与回顾](../../SIMSCENE_视觉升级实施报告_20261030.md)。
