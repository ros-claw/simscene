# 独立验收冻结说明

版本：20261103-independent-v1。设计者仅承担试题、验收与只读检查，不参与候选技能/参数模块编写，未读取新增包源码和答案，不运行试题。两题在任何正式结果出现前冻结；正式开题后禁止改题、阈值、评分器、候选能力或允许运行数。

## 分工与信息隔离

构建 Agent 只收到本题 public 目录里的两个文件，不给它评分器、既往轨迹、另一臂结果、坐标或配方。两臂各自在新会话、新场景、相同资产缓存起点执行，默认每臂一个构建 Agent，不允许子 Agent。主试验候选包的作者只能取得类别与能力要求摘要；试题按顺序由操作员释出。parent 的摘要不得包含具体阈值、坐标、评分实现。

先冻结整个新增包、共同 v43、共同通用文档、两臂各自 skill 可见性、同模型/推理档与预算；再在不计分通用台架上确认环境与额度，开题前填定一致 token 或货币上限。运行身份由 freeze_runtime_identity.py 从通用烟测封存目录取得，创建一次后不再改。该身份文件不是改题许可，也不能根据试题结果补充。若烟测失败，仅修环境；若不得不改候选能力或题目，另起版本与新题。

题目 P1 按 A→B，P2 按 B→A。同一 GPU 串行，禁止同时启动 Isaac。每臂 30 分钟、首次正例 + 最多一次修复正例，正例合格后一次负对照；未通过正例不得反复用负例调参。基础设施异常只允许按事前统一规则另记后重测，原始记录和资源不删除。试题内所有机位/几何/物理参数均由构建者设计，不可被验收者临时帮助。

## 冻结契约与只读评分

完整且公开的目标、所有数值容差、预算和对象角色均在 public/P1、public/P2。public-case.json 必须在每次 native run 启动时固定；这是一种自定义本地独立 pilot 契约，不经公共 run_verify 的内置 case dispatch。simulation_start 可以保存此 dict；评分由 examiner/score.py 读取同一固定契约执行。

评分器自带任务逻辑，借用被冻结的 v43 通用锁文件、strict t0、逐步时钟、被动设置和物理接触日志读取函数。generic_readers_sha256 已在 DESIGN-FREEZE.json 锁定，若这些只读函数变化就拒绝验收。任务评分的数值没有从成功运行或 B 模块反推。

运行示例（只读；输出必须放在 run 封存目录外）：

    PYTHONPATH=/code/rosclaw/simscene/src python3 examiner/score.py --task P1 --positive /sealed/positive --identity /private/approved-runtime.json
    PYTHONPATH=/code/rosclaw/simscene/src python3 examiner/score.py --task P1 --positive /sealed/positive --negative /sealed/locked --identity /private/approved-runtime.json

匿名 ID 映射单独保存，评分者不得根据臂身份选择阈值。正例报告只能表明 positive_passed；只有同一正例及唯一干预负例全部合格，physics_suite_passed 才为 true。P1 负例要求 driver 在锁定的 lever 上仍有实际撞击，P2 负例要求 driver 在 ramp 上仍下降/水平运行。因此“下游静止”不能由上游停机冒充。

锁文件、完整采样、严格零速度恢复、实际被动设置、正确接触身份、正负 runtime/seed/时长相同、完整场景仅一个准许干预，均为硬条件。P1 另从原生 body quaternion 重建铰轴角及锚点，P2 用终态全 box 角点检验水平承托；检查器从不改场景、运行物理、切片/补齐样本或修正结果。文件哈希是完整性证据，不是硬件签名。

## 人工只读复核与最终状态

物理评分与操作协议分开。操作员还必须在事前冻结的统一表中核对：原生图像/片段能辨认本题动作及终态；无临时人工参数提示；未读隐藏评分器；模型与工作流可见性/缓存隔离如实记录；首次正例、修复、负对照与所有失败都计量；没有超时或超固定用量上限。物理通过但上述任一不满足，不能记任务通过。

状态只用 passed_first、passed_after_repair、physics_failed、agent_stopped、budget_exceeded、infrastructure_failed、assisted；证据不全附 evidence_incomplete。终点是“首次提交合格正例，且完成规定负对照和检查”。先质量后比较 token/墙钟；若一臂不通过，不报虚构节省率。B 是整个新增包的效果，不解释为纯文字 skill 的因果收益。

## 未执行声明

此交付只包含冻结设计、源码与 CPU 评分逻辑测试。尚未启动 Isaac、尚未进行通用环境烟测、未运行任何正式题目，因而没有任务成功或 A/B 效率结果。预期每次 12 秒、少量动态体、低清固定机位；30 分钟预算的环境可行性仍需不计分烟测确认。
