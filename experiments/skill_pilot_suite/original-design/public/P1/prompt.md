# 试题 P1：落重抬物

请搭建一个桌面级被动杠杆：橙色 driver 球从空中落到杠杆的一侧，真实接触把放在另一侧的蓝色 payload 抬高。payload 必须是独立刚体，由杠杆承托，不可用关节固定到杠杆。

必需物理根 ID 为 driver、payload、lever、hinge。恰好三个动态刚体 driver / payload / lever；恰好一个启用、无 drive 的 revolute joint hinge，body0=null/world、body1=lever，转轴在世界中水平。lever 用 baked compound，payload 用一个 box 或 sphere；静态支承、挡块和接物边缘可以自定。不得增加绳索、骨牌、柜门、传动链或其他动态体。

正例：driver 从其首次被观察到的位置至少下降 0.08 m，并与 lever 有实际接触；payload 在触发前至少两步有 lever 的真实承托接触。接触触发后，payload 相对实测 t0 上升至少 0.10 m，连续维持至少 30 步，同时 lever 相对 t0 转过至少 8°。这 30 步中 payload 相对 lever 的位置摆幅不超过 0.025 m，且每个连续 6 步窗口内至少一次二者真实接触，证明承托抬升；不能靠弹射到空中冒充承托。所有启用关节的锚点误差始终不超过 0.01 m；不接受起始严重穿透（首秒报告的接触深度不低于 -0.006 m）。

负对照：只把 hinge 的 lower_limit 和 upper_limit 同时设成源场景初始关节角度，锁住杠杆。其余对象和设置不变。必须重新真实运行：driver 仍至少下降 0.08 m，而且仍与 lever 接触；lever 全程转动不超过 2°，payload 上升不超过 0.015 m、三维位移不超过 0.02 m。初始角度锁定允许数值误差 0.0001°；关节仍启用。

共同规则（两臂完全相同）：
- 使用本次冻结的 v43 和所在臂可用工作流；基础 primitive / compound、被动关节、碰撞、重力可以自由设计。不得从联网服务下载资产。不得读取另一臂产物、先前答案或 pilot-private-design 内的 examiner、冻结记录与评分器。只读取本题发给你的 prompt.md 和 public-case.json。
- 时间上限为 30 分钟。首次正例之外最多一次修复后的正例；正例通过后运行一次短负对照。所有运行保留原始 job ID、封存目录及失败产物；勿额外预跑试题。原生仿真每次 720 个物理步（12 秒，dt=1/60，seed=19），一秒后仅 driver 在 spawn_step=60 出现，其余动态物体初始存在。任务期间禁止动力驱动、机器人、输送带、重放位姿、运行时 setter、逐帧力命令及其他脚本动作。
- 每个正例与负例均按 public-case.json 请求 strict_start、逐步位姿和真实 contact_pairs，并将完全相同的 public-case.json 通过 simulation_start(case_path=...) 或 inline case 固定进 run。不得改写 worker、已导出的 USD 或封存证据。除题定干预外，正负场景 objects、observation、presentation 保持完全一致。scene id / revision / request 账本不同允许。
- 正例开始到 driver 出现之前，所有初始动态体在各自实测 t0 附近保持平静：位移不超过 6 mm，转角不超过 3°。所有动态体需碰撞有效、显式正质量 0.01–5 kg；driver 为直径 0.04–0.15 m 的球。对象总数不超过 40；只用 primitive/compound、一个固定机位相机和灯光。动态体必须恰好为题目指定的对象，不得把其他动力源藏到场景中。
- 一台固定 320×240 或 640×360 相机即可。保留能看清触发、运动和终态的原生帧或短视频，无需剪辑、长片或视觉资产。提交匿名运行编号、正例与负例 job ID / 封存路径、失败尝试、耗时、模型用量原始来源和简短结论。验收还会核对锁文件、完整物理时钟、质量、接触、被动约束以及干预是否隔离；退出码或单帧美观不算通过。
- 下面描述的物理数值全部已冻结，也列于 public-case.json。无需寻找目标答案布局，尺寸、位置、质量、摩擦和构型由你设计；没有提供成品配方。
