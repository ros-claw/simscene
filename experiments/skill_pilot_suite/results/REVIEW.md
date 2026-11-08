**两题四臂独立审计：正式任务通过 0/4，没有有效节省率估计。**

原冻结 v1 判定全部保留。两道 P1 都超出固定 token 上限且没有 submission；两道 P2 虽提交了完整失败说明，但正例均失败、没有合格负例前提。没有追加试题、模型尝试或 native 仿真来替换这些失败。本审计保存全部 10 次 native 尝试、所有失败工具记录和原始模型计量。

审计入口：[机器汇总](REVIEW-SUMMARY.json)、[逐臂计量 CSV](usage-summary-public.csv)、[完整私有审计](independent-audit.json)、[时钟/预算/隔离核对](timing-and-boundaries.json)。原协议 SHA256 为 `11fda2ac4fc1bf69e56eb35a18a483e16bff6db02bf3d98c2ac6f9ca47a0d587`；候选包为 `54485c9b29acf56d7d0f7dede16da7ddf20cd56aac79b1a2339cb45b1871036a`；原设计冻结为 `a0d4b4a39b9e5742d0165c537bb360d06d6a258f8a027edd84129680952da379`。

| 匿名臂 | 原 v1 首次正例 | 原 v1 修复/成套物理 | 补充 v2 首次正例 | 补充 v2 修复/成套物理 | 正式状态 |
|---|---|---|---|---|---|
| trial01 · P1/A | 接口拒收 | 接口拒收 / 不通过 | 失败：未持续承托抬升 | 通过 / 通过，仅事后工程结果 | budget_exceeded；无 submission |
| trial02 · P1/B | 失败：未持续承托抬升 | 通过 / 通过，仅事后工程结果 | 同 v1 | 同 v1 | budget_exceeded；无 submission |
| trial03 · P2/B | 接口及静态碰撞失败 | 接口拒收 / 无负例 | 静态支承无碰撞，失败 | 滑出 deck 后下落，失败 / 无负例 | physics_failed；已提交 |
| trial04 · P2/A | 接口及静态碰撞失败 | 空关节接口拒收 / 无负例 | 静态支承无碰撞，失败 | 滑出 deck 后下落，失败 / 无负例 | physics_failed；已提交 |

这里“事后”没有重新择优：按原生 run-lock.created_at_utc 排序，前两次非锁定 P1 源场景分别是首次和修复，随后唯一锁定场景是负例；全部尝试逐一报告。P2 同样按顺序检查两个正例。trial03 提名了已明确失败的 repair；trial04 没有提名成功正例。未提名、未提交的目录不会被审计者补成一份预算内 submission。

原版结果位于 [scores](scores/)，每次命令、退出码和选择规则在 [原评分调用记录](records/frozen-scorer-invocations.json)。补充版、针对性回归及同记录结果位于 [supplementary-v2](supplementary-v2/README.md)。

原检查器的两项接口问题由本独立设计者负责披露：v1 把“动态体实际有碰撞”收窄成必须显式写 `collision:true`，而 v43 对 dynamic primitive/compound 会自动编译碰撞；v1 还将无关节场景省略的空 `joints` 样本键误判为非被动。**P2/B 的修复被第一个问题阻挡；P2/A 的修复被第二个问题阻挡。** 两者首次尝试还确实缺少静态 ramp/deck 碰撞，不是只被检查器误拒收。

补充 v2 是全部四臂结束后才建立的另一个版本，仅修这两个接口。它检查封存 USD 的实际启用 collider/动态 rigid body；对初始 USD 中尚不存在的定时生成体，用匹配原 worker 字节的导出器做隔离的 CPU 等价编译，并明确标注这不是 native spawn-stage 回读。无关节豁免仅接受省略键或空字典，不接受 None 或额外关节。原数值运动、接触、稳定性、因果干预函数 AST 完全相同，两份公开契约字节不变；[完整差异](supplementary-v2/original-to-supplementary.diff)和[变更记录](supplementary-v2/CHANGE-RECORD.json)可检查。15 项针对真实 USD 编译/读回和空关节编码的 CPU 回归通过；初版 15 项抽象数值测试没有覆盖这两种接口，故不能替代这些回归。没有运行新物理。补充 v2 不能追认本轮正式通过。

| P1 真实记录 | 首次最大升高 / 持续窗口 | 修复最大升高 / 合格窗口 | 负例 driver 仍下降 | 负例 payload 最大三维位移 |
|---|---|---|---|---|
| trial01 A | 0.373249 m / 无 | 0.130433 m / step 85–114 | 0.125209 m，仍撞击 lever | 0.0000410 m |
| trial02 B | 0.341002 m / 无 | 0.119725 m / step 79–108 | 0.127309 m，仍撞击 lever | 0.00000427 m |

两组 P1 修复后的承托接触、持续窗口以及隔离锁定干预都满足原数值谓词；不是靠“下游不动”而上游也停机形成的假负例。首次大幅上升均没有形成规定持续承托窗口。两组正负例 objects 只有指定 hinge limits 干预，其余输入和共同运行身份一致。trial02 的负例 result 在 builder 被 token 限额终止后约 3.19 秒才写出，exit 文件约晚 4.26 秒；即使物理证据最终完整，也不存在预算内已完成提交的终点。

P2 首次两臂均无 ramp/deck 实际接触，物体直接落下。修复后两臂均有真实 ramp、driver–payload 和 deck 接触，球也实际转动；payload 随后滑出支承并下落。trial03 修复终态为 `[8.13754, 0.00184, -376.08008] m`，trial04 为 `[11.80267, 0.00479, -416.19275] m`。v2 均明确失败于停稳、高度/倾斜及终态完整承托三个条件。没有合格正例，故两臂不运行负例是正确的；不能以 native EXIT0 当任务通过。每次详细轨迹与检查结果在 records 下逐 run 的 descriptive JSON 及 v2 报告中。

| 匿名臂 | I 输入 | C 缓存输入子集 | O 输出 | I+O | 已完成模型响应 | 墙钟 s | sleep 等待墙钟并集 s |
|---|---:|---:|---:|---:|---:|---:|---:|
| trial01 P1/A | 1,600,992 | 1,553,408 | 6,525 | 1,607,517 | 36 | 228.96 | 114.42 |
| trial02 P1/B | 1,510,704 | 1,437,696 | 6,498 | 1,517,202 | 40 | 168.74 | 60.36 |
| trial03 P2/B | 1,181,959 | 1,136,768 | 5,897 | 1,187,856 | 32 | 170.66 | 69.71 |
| trial04 P2/A | 1,116,367 | 1,080,576 | 5,544 | 1,121,911 | 32 | 174.65 | 79.71 |

总计 I=5,410,022，C=5,208,448，O=24,464，I+O=5,434,486；未缓存输入为 201,574。推理输出 3,959 已包含在 O，不再相加。140 条已完成模型响应有 140 个唯一 response_id；逐条 last usage、累计计数增量、独立 token_usage_record 三路相符，P2 另与 CLI turn.completed 完全相符。逐响应 CSV/JSON 在 records 中。没有服务端 request_id；P1 被终止而缺 terminal CLI 总量，未报告的在途用量/重试与账单仍 unknown，不用本地行号冒充服务端请求 ID。一次性准备成本也未假定为零。

固定额度为每臂 1,800 秒、I+O 1,500,000。P1/A 超 107,517 token，P1/B 超 17,202 token。A 首次越界计数 1,549,683 后，owner 的两秒轮询还来不及阻止下一次已完成响应，另产生 57,834 token；全部已计入，属于限额执行缺口。B 首次越界后没有新的已完成模型响应。四臂都没有触发墙钟上限。sleep 并集不是全部 idle 或模型等待：B 的多次 sleep 有重叠，不能把请求等待秒数简单相加。原生进程从 queue 开始到 exit 文件的区间合计 289.86 秒，queue 前等待合计约 0.38 秒，10 次之间无进程区间重叠；这些不是 GPU busy seconds。

可观测工具粒度为 135 次 functions.exec 外层调用；CLI 记录 191 项操作，其中 104 次 MCP、76 次 shell、11 次成功文件变更，另保留 B 的一次 apply_patch router 校验失败。这些不同层级不叠加成一个虚构调用总数。MCP 启动物理次数分别为 3/3/2/2，job_status 为 5/9/3/3。保留的失败还包括两次内置 run_verify 不支持自定义契约、三次 light 字段校验失败、一次缺文件读取和一次 python 命令不存在；没有 native 启动/进程基础设施失败，未排除任何已分配臂。

306 个协议冻结输入哈希全部一致，各臂 .agents 技能副本也匹配对应候选包。四个 CLI 命令和实际 turn_context 都是 gpt-6.1-terra / medium，单 builder、同一 installed v43 MCP；10 个 native worker 快照、Isaac/runtime、seed、时长、完整逐步时钟和严格初态全部通过。这里可核对的是模型别名/effort，提供方未给出额外部署构建版本。每臂 state 在 owner 开题时新建，公开提示和 case 哈希相同；全部 case_path pin 保留原字节，开题前的 inline 接口澄清对四臂一致。

**受控原始日志中没有专家辅导或开题后的外部任务提示。** 每个会话只有自动环境消息和同一开题消息；没有子 Agent、第二模型、联网资产或跨臂/隐藏评分器/开发仓库访问。ROOT 的开题前盲态由协议与操作员声明保留，未从结果倒推为额外“物理证明”。

缓存不能称等价冷启动：owner 使用了不受 installed settings 识别的 `SIMSCENE_CACHE_DIRECTORY`，实际接口是 `SIMSCENE_CACHE`，因此不能证明预想的独立资产缓存覆盖生效；本题完全没有 asset/acquisition，所以没有实际资产载入差异。shader/kernel 和提供方缓存未隔离，C 已如实计入额度。

B 两臂确实读取新增 passive-production 工作流材料；未发现调用骨牌/门桥编译、首断点诊断、机器等待或回放新增 helper。B 仍使用普通 sleep 和 job_status。因而本轮只观察到了整个可见新增包下的行为，不能宣称验证了这些模块真正调用后的收益。之后 ROOT 的模块台架/安装烟测是另项证据，不混进本轮。

已目视检查 10 张 native 终态图与 3 张原视频解码运动帧：[原生接触表](visuals/native-contact-sheet.png)。P2 运动帧可辨球/滑块，终态已离开；P1 杠杆动作可见，但修复场景的高侧壁遮挡 payload，B 也缺动作视频，故没有据单帧签发完整视觉通过。物理数值通过不代替视觉证据质量。

A、B 各自总体通过数都是 0/2；单位通过成本不定义，没有百分比节省、普遍成功率或显著性结论。该轮的有效产物是可追溯的四臂失败、两项评分接口缺陷及经同记录验证的补充 v2。公开交付范围见 [可移植文件清单](PUBLICATION-FILE-LIST.json)与[发布说明](PUBLICATION-GUIDE.md)。
