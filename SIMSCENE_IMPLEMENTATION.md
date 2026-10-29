# SimScene 插件实施与验收说明

日期：2026-10-28  
建议仓库：`ros-claw/simscene`  
建议 Python 分发名：`rosclaw-simscene`；Python 包名：`simscene`；CLI：`simscene`  
交付对象：本地 Codex / 工程开发 Agent

## 0. 任务与当前状态

开发一个面向 Agent 的仿真场景搭建插件，让 Codex、Claude Code、DeepSeek Harness 等客户端能够使用已有资产和基础几何，完成场景创建、空间组合、物理配置、行为绑定、运行观察、局部修改与导出。

首个完整演示是三种机械臂沿连续传送带分拣物料。插件的通用组合能力与示例运行控制分开实现。第一版以 Isaac Sim 为唯一实装后端；通过接口保留扩展空间，不把其他仿真器写为已支持。

本说明记录实施要求和验收目标，并参考官方文档、仓库、资产目录及 Agent 接入规范。本文的性能数字、成功率和时间参数是建议初值或验收目标，不代表已经测得的结果；项目当前实现、实际运行证据和未完成事项以 [validation.md](docs/validation.md) 为准。

### 0.1 开发完成的含义

1. 插件可独立安装，具备 Python SDK、CLI、MCP 入口，三个入口使用同一实现。
2. 至少在一个真实 Agent 客户端中，从空场景以一条自然语言请求完成资产检查、布局、行为绑定、运行与验收。
3. 三台不同型号机械臂均实际完成连续输送中的抓取和正确落箱。
4. 能通过后续自然语言修改分拣规则、料箱位置和带速，修改后重新检查并运行。
5. 保存可重建的场景规格、资产锁文件、控制配置、运行记录和连续视频。
6. Codex、Claude Code、DeepSeek Harness 分别列出已实测或未运行状态；协议兼容不自动等于 Agent 实测成功。

## 1. 用户输入与演示设计

### 1.1 推荐的一句话输入

> 用现成仿真资产搭建一座明亮、精致的智能分拣工作站，让三种不同型号的机械臂沿一条持续运行的传送带错位协作，分别将不断进入的红、绿、蓝三类小件抓取并放入对应料箱，呈现双指夹持和吸盘搬运两种动作，加入补料滑槽、末端漏料回收区、跟随真实设备状态变化的指示灯与分拣计数，以及全景、俯视和抓取特写相机，自动运行并检查结果，保存可继续编辑的场景和一段能够清楚看见真实抓取过程的演示视频。

这句话作为普通使用入口。验收约束由项目固定的测试配置另行提供，不需要每次让用户输入技术细节。

### 1.2 第一版场景

- 一条约 5–6 米的直线输送线；长度是布局初值，按选中资产和机器人工作空间求解。
- 三个沿输送方向分开的抓取工位，工作区尽量不重叠；允许中间机械臂在传送带另一侧，形成清晰的视觉层次。
- 三类测试工件首先使用约 40–60 毫米的彩色刚体方块，质量由测试 profile 明确给定。基础几何是测试工件，不能标成下载的 SimReady 资产。
- 每台机械臂负责一类，料箱置于各自可达范围内；传送带末端设置实体回收盘，用于收集漏抓物体。
- 配置装饰机架、围栏、地面标线和顶灯时，先保证抓取视线与机器人工作空间。
- 起步带速建议 0.05–0.08 m/s，投料间隔建议 3–4 秒；调参阶段可修改，正式验收前锁定。
- 第一版 `perception_mode=oracle_state`：控制器从仿真获取类别、位置和速度。相机用于观察、展示和 Agent 检查；不得宣传为已经完成 RGB-D 视觉识别。
- 增加纸盒、圆柱件、随机朝向或视觉识别时，各自重新验证，不沿用方块测试结论。

### 1.3 外观与动态效果

采用干净的工业实验室风格，物料颜色与目标箱、工位指示灯保持一致。金属、塑料与地面材质有层次，主光清楚照亮接触区域。优先让来料流、追踪抓取、转运放箱和落料碰撞形成动态感。

设置四类视角：固定 3/4 全景、固定俯视、单工位抓取特写、缓慢移动的展示镜头。验收录像使用连续固定机位；宣传片可切镜，所有镜头必须来自真实运行。计数、带速、运行状态从记录的数据生成，禁止硬编码成功数字。离线渲染可以用于高质量视频，但必须区分仿真时间、真实计算时间与视频播放速度。

## 2. 技术路线与版本

### 2.1 推荐支持档

| 项目 | 第一版选择 |
| --- | --- |
| 仿真器 | 新项目默认 Isaac Sim 6.2.0 GA；已有 6.1 环境单列兼容档 |
| 物理 | 实测通过的 standalone PhysX profile；可先用 CPU dynamics，GPU 用于渲染和运动计算 |
| 操作系统 | 首选 Linux x86_64，方便使用完整官方运行环境 |
| 初始 GPU | 建议先在现有 A6000 工作站选一张卡运行，记录显存和实际速度 |
| Agent 接口 | MCP stdio 优先；CLI 作为调试和兼容入口；需要远程时增加 Streamable HTTP |
| 控制方式 | 仿真进程内运行确定性的机械臂控制器和状态机 |
| 依赖管理 | 控制服务与 Isaac worker 独立 Python 环境；锁定支持档与依赖 |

官方 release 列表当前将 6.2.0 标为 GA/latest，7.0.0a1 是预发布。第一版无需依赖 7.0 alpha。6.2 已移除 Cortex，不应复制旧 Cortex palletizing 代码作为新工程主线。[S01][S02]

已有用户场景需要留在原版本时，使用独立安装或容器验证新版本。`doctor` 必须输出实际版本、Python、GPU/驱动、资产根、扩展和客户端版本。GPU tensor、Newton 与其他版本的兼容性必须独立验证，不能由一个 PhysX profile 推导。

### 2.2 已可复用的官方实现

1. Isaac Sim 6.2 的状态机教程已有 Franka 抓放，以及 UR10 从运动传送带取 KLT 箱、按需翻转并码垛的示例。入口 `standalone_examples/tutorials/state_machine/ur10_palletizing_transitions.py`。复用其 observation/controller/command 分工，避免依赖被移除的 Cortex。[S03]
2. 官方 Conveyor Belt Utility 提供接触表面的输送行为与 Python 接口。给真实的 Belt/Rollers 接触 prim 绑定功能，纹理动画仅负责外观。[S04]
3. 官方 Surface Gripper 提供近距离检测和有力限的约束式吸附模型，可用于 UR10 的吸盘工具。[S05]
4. 官方机器人目录提供多种机械臂 USD；新 cuMotion 配置文档内置 Franka、UR10，其他机械臂仍需匹配配置。[S06][S07]
5. UR10e + Robotiq 2F-140 有官方组合资产与新抓放教程，可作为第三机器人适配受阻时的工程备用方案。[S08]

### 2.3 NVIDIA 已有 Agent 能力的复用边界

Isaac Sim 6.2 的源码、pip 与 binary 安装包都随附 Agent skills。官方已经提供 `isaac-sim-orchestrator`、`spatial-reasoning`、`usd-pipeline`、`physics-simulation`、`manipulation-ik` 和远程操作、渲染、检查等工作流程。因此不能将“让 Agent 用自然语言创建 Isaac 场景”描述为本项目首次具备的能力，也不应重复抄写一套基础知识。[S24]

P0 先检查本机随附 skills 与官方示例，复用其与当前版本一致的 API 和已知限制。SimScene 提供一个薄的通用主 skill，把稳定组合操作、资产功能适配、可修改的场景表示、运行会话和验收组织成可安装插件。新增场景主要增加配方数据；新增物理机制才需要新的行为模块。

首版默认连接 NVIDIA 托管的公共 USD Search 服务，支持替换服务地址；搜索时仅获取候选信息、元数据和预览，确定使用后才获取选中资产及其必要依赖。这一补充覆盖原先将 USD Search 列为后续可选的安排。服务仅搜索其已索引的资产，其他社区来源需要继续接入。SimReady Central 负责连接和发现多个贡献者的 Hugging Face 资产数据集，资产本体由各数据集托管；`nvidia/simready-assets` 是其中一个具体资产来源。首版不要求用户预下载完整资产库或自行部署索引。Omniverse `kit-usd-agents` 可作为 USD Agent 参考。[S18][S19][S25]

## 3. 架构与职责

核心路径：Agent 生成和修改场景意图；共享 Python 核心检查资产、求布局并生成场景；Isaac worker 执行场景与控制器；实际画面和结构化状态返回 Agent，由 Agent 决定下一次修改。

| 模块 | 职责 |
| --- | --- |
| `core/schema` | SceneIntent、ResolvedSceneSpec、编辑操作、任务状态、结果结构 |
| `assets` | 资产搜索、属性检查、依赖解析、下载缓存、版本锁定 |
| `compose` | 支撑、对齐、朝向、排列、间距、工位布局、连接与相机布置 |
| `session` | 场景 ID、revision、稳定对象 ID、幂等请求、批次编辑和重建 |
| `backends/isaac` | 仿真进程生命周期、USD 实例化、物理配置、状态读取、渲染和导出 |
| `behaviors` | 传送带、投料流、机械臂追踪抓放、回收与状态机 |
| `verification` | 读取实际场景和运行状态，判断几何、抓取、落箱与接触结果 |
| `mcp` / `cli` / `sdk` | 同一核心的不同入口，不复制业务逻辑 |
| `skills` | 少量通用搭建、观察、修正方法 |
| `recipes` | 具体场景的可修改数据与组合示例 |

主 skill 只教 Agent 检查资产、表达关系、构建、观察、修正和保存。机器人数量、具体型号、类别规则和布局属于配方或场景数据。领域操作可以作为组合宏，但必须展开成通用对象、变换、关系与已支持行为；核心调度器不能依赖“三臂分拣”这个场景名称。

### 3.1 Agent 与实时控制

Agent 负责资产选择、场景布局、控制器选择、参数配置和错误修复。每个物理步的运动计算由已实现的控制器执行，不要求 LLM 实时输出关节角。

插件可以提供受控的 Python 组合扩展入口，用于现有工具未覆盖的新组合。候选脚本仅在暂停的构建/编辑阶段执行，通过允许的组合 API 产生操作，并返回场景 diff 和检查结果。正式验收阶段固定核心、控制器、行为注册表与检查器；运行中不能注入回调、替换控制模块或使用直接位姿写入绕过物理。

Agent 可以修改场景 spec、可调参数和构建阶段的组合脚本；正式验收要求使用独立冻结的用例文件。对象目标、类别映射、阈值、允许接触、超时和 seed 不能因为场景 spec 被修改而同时被放宽。

### 3.2 三个具体边界

- 几何父子层级只描述场景组织，物理固定连接与关节必须显式创建。
- `scene.usd` 保存几何和配置，不保证独立包含 Python 控制器；完整可运行交付还需 runtime 配置、行为模块版本和启动入口。
- 初版承诺保存初始场景并从头重跑；运行中完整断点恢复涉及速度、关节、接触和控制状态，单独实现后才声明支持。

## 4. 资产策略和三机械臂选型

### 4.1 资产来源

首版以 NVIDIA USD Search 的在线检索和按需获取为核心，同时支持仿真端本地 USD 路径及 Hugging Face 数据集资产的发现与获取。经过验证的小型资产与控制适配清单用于测试，不能限制开放搜索范围；其他社区索引按实际接入状态报告。在线查询返回候选后，必须读取实际元数据与文件依赖，不能猜文件名、尺寸或可用关节。远程 GPU 机器运行仿真时，所选 3D 资产与受容量限制的缓存留在仿真端，客户端读取画面和状态；本机运行时仿真器仍需读取实际资产。

资产检索与功能适配分别记录。对于新搜索到但未适配的资产，可以提供视觉摆放能力；需要机械臂控制、主动输送等行为时，检查相应功能 profile 是否已验证。

### 4.2 默认演示配置与备用配置

推荐旗舰组合：Franka Panda + UR10 + Kawasaki RS007L（OnRobot RG2）。它们属于三个厂商，外形清晰不同。实际实施要先验证第三台的控制配置，不能把旧版 Lula 支持名单当作新版 cuMotion 即插即用证明。

| 机器人 | 官方资产相对路径，基于 `/Isaac/Robots/` | 推荐机制 |
| --- | --- | --- |
| Franka Panda | `FrankaRobotics/FrankaPanda/franka.usd` | 双指接触抓取 |
| UR10 | `UniversalRobots/ur10/ur10.usd`，另按官方配置添加吸盘附件 | Surface Gripper 吸附 |
| Kawasaki RS007L | `Kawasaki/RS007L/rs007l_onrobot_rg2.usd` | RG2 接触抓取 |

通过当前安装的资产 resolver 解析资产根，再锁定具体版本与下载内容。不要依赖 `latest` URL。[S06]

第三台如果在当前版本缺少有效控制配置：优先用其实际 URDF、关节定义和 TCP 生成匹配配置，并验证 FK、限位和抓放。可使用官方 UR10e + Robotiq 组合推进三型号工程闭环，但必须另存场景配置并准确报告选型。用户原始要求是三台不同机械臂，UR10/UR10e 是同厂不同型号；三品牌展示配置只有 RS007L 实测通过后才标完成。[S07][S08]

### 4.3 机器人 profile 的最小内容

`asset_uri`、资产版本/内容 hash、root/articulation prim、arm joint names、gripper joint names、末端和工具坐标系、TCP 偏移、控制器族和配置、默认姿态、关节限位、工作区、夹持机制、适用 runtime、最近一次验证报告。

必须比较控制模型 FK 与仿真中实际末端位姿。没有测量确认的 TCP、夹爪开合范围或质量不得由模型编造。

### 4.4 传送带与料箱 profile

传送带记录实际带面 prim、固定机架 prim、局部输送方向、可用表面范围、入口/出口锚点和速度命令接口。料箱记录内部有效容积、底板和侧壁碰撞体、放料候选位姿及容量。

SimReady 中的传送带候选例如 `conveyor_belt_a08` 可用于外观与结构，但需要检查和绑定输送行为。复杂资产允许采用与可见带面吻合的简化物理代理，需在 profile 中声明并提供调试可视化。避免重复碰撞面；所有应用修改写入 override layer，保留源资产。

根文件大小不等于整个资产包大小；按依赖解析后下载，并以实际 package bytes 和缓存命中统计资源开销。

### 4.5 资产锁文件

每个实际使用的资产保存：来源 URL/仓库 revision、根 USD、依赖列表及内容 hash、许可证和署名、单位与 up axis、实例变换、物理适配 profile 和其版本。下载缓存使用内容寻址并检查完整性。搜索服务不可用时返回明确错误或使用已锁定缓存，不把网络失败当作“无此资产”。

## 5. 场景描述与组合操作

### 5.1 两阶段表示

`SceneIntent` 可以表达“选一种已支持的吸盘机械臂”“留出通道”等意图；`ResolvedSceneSpec` 必须包含确定资产、单位、对象 ID、布局、控制 profile 和所有必需参数。未解析要求以结构化错误返回，不能静默丢掉。

核心先支持：实例化、基础几何、支撑面放置、对齐、朝向、行列/路径排列、净空、分组、固定连接、基础关节、机器人控制器绑定、传送带绑定、相机和灯光。

布局实现先用锚点、候选位姿和几何/IK/碰撞筛选，遇到无法满足的关系返回具体原因。无需先开发适用于任意场景的全局约束优化器。

### 5.2 设计示例

以下 YAML 是拟实现的输入形式，必须由 Codex 写出并测试对应 schema；它不是现有 NVIDIA API。

```yaml
schema_version: "0.1"
scene_id: three_arm_sorting
world:
  units: m
  up_axis: Z
  gravity_m_s2: [0, 0, -9.81]
runtime_profile: isaac_6_2_physx_verified
seed: 17
perception_mode: oracle_state

objects:
  belt:
    capability: conveyor
    asset_profile: conveyor_straight_verified
  arm_red:
    capability: manipulator
    asset_profile: franka_panda_contact_verified
  arm_green:
    capability: manipulator
    asset_profile: ur10_suction_verified
  arm_blue:
    capability: manipulator
    asset_profile: rs007l_rg2_contact_verified
  bin_red: {capability: container, asset_profile: sorting_bin_verified}
  bin_green: {capability: container, asset_profile: sorting_bin_verified}
  bin_blue: {capability: container, asset_profile: sorting_bin_verified}

relations:
  - {type: station_along, robot: arm_red, conveyor: belt, fraction: 0.2, side: left}
  - {type: station_along, robot: arm_green, conveyor: belt, fraction: 0.5, side: right}
  - {type: station_along, robot: arm_blue, conveyor: belt, fraction: 0.8, side: left}
  - {type: reachable_bin, robot: arm_red, container: bin_red}
  - {type: reachable_bin, robot: arm_green, container: bin_green}
  - {type: reachable_bin, robot: arm_blue, container: bin_blue}

behaviors:
  - {type: conveyor_surface_velocity, target: belt, speed_m_s: 0.08}
  - type: rigid_object_stream
    target: belt
    interval_s: 4.0
    classes: [red, green, blue]
    count_per_class: 20
    shuffle: true
  - {type: track_pick_place, robot: arm_red, class: red, destination: bin_red}
  - {type: track_pick_place, robot: arm_green, class: green, destination: bin_green}
  - {type: track_pick_place, robot: arm_blue, class: blue, destination: bin_blue}

presentation:
  style: clean_industrial
  cameras: [overview, top, grasp_closeup]
  live_indicators: [belt_speed, sorted_count, missed_count, station_state]
```

`verified` 是注册状态要求；只有 profile 已通过本地检查后才能使用这些别名。组合求解器必须从几何与运动学解算最终位置，不能把 fraction 直接转成硬编码机器人坐标。每个工位需检查预抓取、抓取、抬升、过渡、落箱位姿，完整运动路径也要进行碰撞检查。

`station_along`、`reachable_bin` 是配方层的可复用组合宏，展开结果写入 resolved spec。新增场景优先通过已有原语与行为重新组合；只有缺少新的物理机制或通用操作时才扩展代码，无需每种场景增加一个 skill。

### 5.3 坐标与关系

核心统一用米和明确的旋转约定，例如四元数 `wxyz`；各后端适配时显式转换。机器人不得通过缩放解决可达性问题。记录支撑面与锚点的局部坐标；更换资产后重新求解相关关系。持久对象 ID 与显示名称、prim path 分离。

## 6. MCP 与运行协议

### 6.1 建议工具

| 工具 | 主要输入与返回 |
| --- | --- |
| `environment_probe` | 实际 runtime、资产源、支持 profile、GPU、worker 状态 |
| `asset_search` | 查询与约束；候选、来源、未知/未应用约束 |
| `asset_inspect` | 资产引用；单位、尺寸、部件、关节、依赖、可用能力 |
| `scene_open` | 新建或打开；`scene_id`、revision、worker session |
| `scene_get` | 对象、关系、配置及实时状态摘要 |
| `scene_apply` | 操作批次、base revision、request ID；新 revision 或具体错误 |
| `scene_validate` | 静态/几何/可达性/短时物理检查；结构化问题及证据 |
| `simulation_start` | 固定场景 revision、seed、时长/终止条件；立即返回 `job_id` 与 `run_id` |
| `simulation_control` | pause、resume、reset；必须读回确认实际状态 |
| `scene_observe` | 视角与对象过滤；截图、时间戳、实际状态 |
| `scene_export` | USD、spec、资产锁、启动配置与报告引用 |
| `job_status` / `job_cancel` | 进度、日志尾部、完成/失败原因、取消确认 |

逻辑名保持稳定，共享 skill 不写死宿主添加的 MCP 前缀。大量日志写入文件，仅返回摘要和有界尾部。stdout 只发送 MCP 协议，日志走 stderr 或文件。

### 6.2 进程与长任务

MCP 初始化、工具发现不能自动启动 GPU 仿真。只有显式请求才创建或连接 worker。Isaac 保持一个可复用的会话，不能每次工具调用重新启动。

下载、场景加载、构建与长时仿真返回普通 `job_id`，通过 status/cancel 管理，不将 MCP Tasks 扩展作为必选。DeepSeek Harness 当前 bridge 支持 stdio/Streamable HTTP，默认每次调用超时为 60 秒，并不支持 task-required 工具；stdio 协商也可能启动探测进程。[S11]

每个 job 保存 `QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED`、最近心跳、进度、实际 simulator session、日志路径和失败原因。超时不能只留下“running”；取消必须让 worker 确认暂停/退出。对重复请求返回原结果，避免重复投料和重复实例化。

### 6.3 编辑一致性

`scene_apply` 包含 `scene_id`、`base_revision`、`request_id` 和操作数组。单场景单写入者；UI 外部修改需要重新读取 revision。批次先作用于候选层或候选场景，验证后提交。失败后恢复到可重建的前一编辑状态。

USD 的 `Sdf.ChangeBlock` 只聚合变更通知，不是事务或回滚机制；不能据此承诺原子性。[S16]

改布局原则上在暂停状态进行。若控制器的目标、TCP、碰撞世界受到修改影响，必须重新初始化这些对象。第一版不要承诺对动态接触中场景任意热编辑。

### 6.4 场景包与运行记录

场景包保存可重建的初始场景、spec、资产锁和控制配置。每次执行创建独立 `run_id` 和输出目录，绑定场景 revision、内容 hash、seed、实际 runtime 与冻结验收用例。`job_id` 表示执行任务，`run_id` 表示一次运行的证据集合，两者不能混用。

正式测试不能覆盖已有 run。重跑、改变 seed 或重新模拟均生成新的 run；失败运行同样保留。记录中保存所用场景包的快照或可解析的内容引用，避免后来编辑场景改变旧报告的含义。

## 7. Agent 客户端接入

### 7.1 统一实现与分发

共享 Python wheel、核心工具 schema、skill 正文和配方。针对宿主生成各自 manifest/配置，不复制核心实现。安装后使用 wheel 或插件内自包含启动器；不要依靠开发机器工作目录中的 `../../src`。

发布包使用独立根目录，不把多种发现机制混入同一个安装根：

| 产物 | 内容 |
| --- | --- |
| Portable Agent Plugins 包 | 根 `plugin.json`、根 `mcp.json`、`skills/`；按 portable schema 明确声明 MCP `transport.type` |
| Claude Code 包 | `.claude-plugin/plugin.json`、根 `.mcp.json`、`skills/` |
| DeepSeek Harness 接入 | Cordis 配置 patch；若发布可安装 bundle，另有声明 `dsh.bundle` 的 npm `package.json` |

生成配置、注册 MCP 服务、安装原生插件是三个不同状态。安装器必须报告实际完成哪一步，不能仅写出配置就显示“插件已安装”。[S09][S12][S23]

运行数据、资产缓存、日志和模型凭据放在用户运行目录，不能写到宿主的插件缓存包中。安装程序验证生成的实际绝对路径。MCP 服务调用本地 Isaac worker；普通 MCP 虚拟环境不安装第二套不兼容的 pxr/Isaac 包。

### 7.2 Codex

官方当前推荐 portable Agent Plugins 根 `plugin.json` + `mcp.json` + `skills/`；`.codex-plugin/plugin.json` 是兼容形式。提交源码到 GitHub 和进入官方插件目录是两件事，首版完成本地安装与文档即可。[S09]

CLI 验证的可靠入口是官方 MCP 注册方式；项目实现后生成命令，例如：

```bash
codex mcp add simscene -- /absolute/path/to/venv/bin/simscene mcp
codex mcp list
```

`simscene mcp` 是本项目要实现的命令，实际绝对路径由安装器生成。项目 skill 可以通过 `.agents/skills` 发现，也可以随插件分发。不要假设所有 Codex 表面都接受同一个本地插件安装命令。[S10][S17]

### 7.3 Claude Code

提供 `.claude-plugin/plugin.json`、根 `.mcp.json` 和 `skills/build-scene/SKILL.md`，按官方插件根结构打包。开发时使用 `claude --plugin-dir <插件根目录>`，并执行实际安装版本支持的 manifest 验证命令。引用包内脚本按官方支持的 `${CLAUDE_PLUGIN_ROOT}` 处理。[S12][S22]

与 portable 包使用单一源元数据、分别生成安装目录，避免同一个 server 被重复发现。

### 7.4 DeepSeek Harness

DeepSeek 官方目前将 Harness 标为 developer preview。其原生扩展基于 Cordis，不能直接复用 Claude manifest；但官方 `@deepseek-ai/dsh-mcp-client` 可以连接同一 MCP server。[S11][S13]

按当前版本官方 schema 生成类似配置：

```yaml
- insert:
    - id: simscene-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: simscene
        transport: stdio
        command: /absolute/path/to/venv/bin/simscene
        args: [mcp]
```

主 skill 通过其本地 `.dsh/skills`、`.agents/skills` 或 `customSkillDirs` 接入。需要插件列表中一键启用时再提供薄 bundle；场景代码仍运行在共享 Python 核心。[S14]

若首版交付可安装 DSH bundle，可使用以下最小包装，将上面的 YAML 保存为 `cordis.patch.yml`；按已实测 Harness 版本补全引擎范围和官方 MCP client 的依赖声明。[S23]

```json
{
  "name": "dsh-simscene",
  "version": "0.1.0",
  "type": "module",
  "files": ["cordis.patch.yml"],
  "dsh": {"bundle": {"patch": "./cordis.patch.yml"}}
}
```

该 bundle 只加载官方 MCP client，不再复制一套 TypeScript 场景工具。若只生成配置 patch，支持矩阵写“DSH MCP 接入”，不宣称完成 bundle 安装。

图像能否进入模型上下文取决于实际模型与 Harness 的图片支持，测试中要验证模型真的收到截图；纯文本模型使用结构化几何和状态反馈，并准确报告能力范围。

## 8. 动态分拣实现

### 8.1 传送带物理

优先采用官方 `create_conveyor_belt` / Conveyor 扩展，使带面通过接触摩擦驱动物体。传送带表面可采用其要求的 kinematic 配置；货物保持 dynamic rigid body。

先单独完成落箱输送检查：物体落到带上、发生接触、随带前进；速度设零后其运动响应改变；离开末端后因重力落下。该检查必须在目标 runtime profile 上通过。[S04][S21]

### 8.2 机器人控制状态机

每台机械臂执行：

1. 读取候选目标与当前物体速度。
2. 预占目标，验证其属于本工位可处理类别。
3. 估计到达时间和拦截位置，检查抓取窗口。
4. 进入预抓取位姿，持续更新目标并跟踪下降。
5. 闭合夹爪或启动吸盘，读取实际抓取状态。
6. 抬升并确认物体随真实夹持离开带面。
7. 转运至料箱上方，释放。
8. 由独立检查器确认落箱与稳定，再登记成功。
9. 回到待机；失败或目标离开窗口时记录原因并转向下一物体。

目标预测使用实际仿真位置与速度，不直接把命令带速视为工件速度。静态 PickPlace 的一次性目标不能替代移动目标跟踪。原地停带抓放可作为调试阶段，最终连续分拣不能每次抓取时停带。

控制初值可采用 physics 120 Hz、control 60 Hz、render 30 Hz，按本地接触稳定性校准并锁定。报告真实运行速度，不能把仿真时间等同于墙钟时间。

### 8.3 双指与吸盘分别实现

双指夹爪依赖接触、摩擦和关节驱动；物体不得重挂到末端，不得切成 kinematic 跟随，不加隐形固定约束辅助双指成功。

Surface Gripper 是明确声明的吸盘近似，可以在满足接近条件时建立可断裂吸附约束。记录最大抓取距离、力限、实际抓持对象和释放事件。运行态必须从实时 gripper 接口读取，不能仅依赖可能未写回 USD 的属性。[S05]

### 8.4 多臂协调

使用互不重叠的主要工作区与各自料箱。规划世界包含必要障碍，记录过滤规则；每台机械臂独立使用 RMPflow 不等于具备全局多臂避碰。工位间出现共享区域时增加明确的区域占用和让行机制。

### 8.5 物体生命周期

仅 `spawn/reset` 等明确生命周期操作可以设初始位姿或速度。物体进入正式运行后，不得逐帧写世界位姿或直接线速度来实现输送/搬运。每个物体使用唯一 ID，先记录最终结果才允许归档/回收；禁止通过删除失败物体提高统计成功率。

长期运行设置物体数量与料箱容量上限，容量不足时报告并采用明确的补箱/停止投料策略。不得无限生成物体导致资源耗尽。

## 9. 验收方法

### 9.1 四种结果分开报告

1. **构建成功**：实际场景内对象、资产、关系与用户要求一致。
2. **物理运行成功**：输送、抓取、释放等机制确实按声明运行。
3. **任务成功**：物体进入正确料箱且满足稳定条件。
4. **展示成功**：镜头、光照、动态节奏与信息呈现清楚。

固定脚本运行成功不能单独证明 Agent 会组合场景；漂亮视频也不能单独证明物理抓取。

### 9.2 核心与安装测试

CPU CI 覆盖单位/旋转转换、关系 schema、稳定 ID、重复请求、失败批次恢复、版本冲突、资产依赖锁定和 job 状态。用独立 GPU 测试执行真实后端。模拟 worker 仅用于协议测试，报告中标为 mock。

验证干净安装后可发现工具、调用 probe、创建场景、获取图片/状态并导出。不能只在开发仓库的工作目录里测试。

### 9.3 Agent 组合测试

使用新的 Agent 会话与固定版本插件，初始场景为空。Agent 只得到用户输入、通用 skill、工具和支持资产清单；不得把完整分拣场景预加载后声称从零生成。

至少执行以下输入：

1. 推荐的一句话，生成三臂分拣场景。
2. 交换两台机械臂的分拣类别，保持其他功能合理。
3. 将一个料箱移到该机械臂另一侧，并重新检查可达性与路线。
4. 降低带速并提高投料间隔，验证实际状态发生变化。
5. 一个未提供现成完整配方的组合，例如“单机械臂工作台，两排料盒，相机环绕观测”。

修改的结果由检查器读实际场景与运行配置确认，不能只看 Agent 的回答。保存 prompt、模型/客户端版本、工具轨迹、spec diff、检查结果和截图。无需先建立大型 benchmark；这些测试直接验证本插件的目标。

第 5 个任务在插件代码和通用 skill 冻结后执行。允许 Agent 生成新 spec 或配方，不得为了通过该任务临时修改核心或新增专用 skill。正式用例单独保存，检查器读取用例与实际状态，不能只验证 Agent 自己生成的目标。

### 9.4 三臂正式验收初始目标

下列是建议工程门槛，调试后在正式测试前冻结；不得测试失败后悄悄降低标准。

| 指标 | 建议门槛 |
| --- | --- |
| 机器人 | 三台不同型号，三台都产生真实成功抓取 |
| 连续输送 | 正式抓取阶段带速保持非零；不以停带抓放替代 |
| 并行活动 | 存在三个工位同时处于取放循环的连续时段，并记录起止时间 |
| 样本 | 3 个种子，每个 60 个物体，每类 20 个；总计 180 个 |
| 成功率 | 每次运行总成功率 ≥90%，每台分别 ≥85% |
| 错箱 | 0；漏抓、掉落、超时计入失败 |
| 意外接触 | 无机械臂互撞、穿透工作台等未允许接触；抓取、落料接触单独分类 |
| 结束 | 来料结束后有明确 drain 时限，仍在场景中的物体不能从分母消失 |
| 重置 | 至少 3 次从保存初始场景重新运行，检查控制器与计数复位 |
| 持续运行 | 额外 10 分钟仿真时间的连续运行，记录全程物料账本和资源占用 |

推荐种子为 17、29、43；在调试时可以使用其他种子。固定种子仅用于复现，不承诺跨硬件逐 bit 一致。记录启动失败、模型失败和仿真失败，不只保存成功记录。

### 9.5 成功条件与账本

成功至少满足：正确类别和工位、实际抓取证据、释放后无夹持连接、物体几何处于目标箱有效内部、速度低于约定阈值并稳定保持例如 1 秒。可从线速度 0.05 m/s、角速度 0.5 rad/s 开始校准，正式验收锁定。状态机进入 DONE 不是唯一证据。

每个 object_id 记录互斥的终态：正确归箱、错箱、掉落/拒收、超时/未完成等；避免重复计数。任意时刻满足：

`已生成 = 正确归箱终态数 + 错箱终态数 + 失败终态数 + 尚未进入终态的物体数`

任务状态与物理存在状态分别记录。终态物体继续留在料箱、被归档或被回收，均不改变其原有任务结果，也不重复计数；回收不是另一种任务结果。到达 drain 时限后，剩余未终结物体进入“超时/未完成”失败终态。

单次抓取尝试使用独立 `attempt_id`。失败后重试的次数另行统计；一个物体最后成功仍只计一个成功终态，已经判定不可逆失败终态的物体不能重新计成功。任务成功率以全部已生成物体为分母，同时报告抓取尝试成功率，不能混用两种指标。

### 9.6 三个必要负对照

- 禁用指定机械臂的夹持机制，确认搬运成功数不会继续凭空增加。
- 停止指定机械臂关节驱动，确认物体不会继续沿“预设抓取路线”归箱。
- 将带速置零，确认在惯性和碰撞影响消退后，孤立物体不再持续受到原输送运动。

负对照应触发预期的任务能力下降或失败，并被检查器准确识别；观察到该预期结果时，负对照检查本身为 PASS。不得把测试进程崩溃或随意返回非零退出码当作负对照通过。检查器单独读取物理状态和接触数据，不信任行为模块自报 success。

Claude Code 的官方 plugin eval 当前默认采用 MCP mock，适合验证触发和参数；真实物理验收使用实际 MCP server 与 GPU worker，不能以 mock eval 结果替代。[S15]

## 10. 开发顺序

| 阶段 | 工作 | 必须看到的结果 |
| --- | --- | --- |
| P0 环境与关键风险 | 探测本机与随附 skills；锁定 runtime；运行官方 UR10 例子；检查第三机器人资产/控制配置 | 环境报告、可复用能力、实际运行日志、选型与风险结论 |
| P1 最小纵向链路 | MCP→worker→导入资产→摆放→截图→落带物理→保存 | 一个真实 Agent 可调用，不止静态脚本 |
| P2 通用组合 | schema、关系、编辑、profile、依赖锁定、验证 | 自然语言工作台和输送工位能生成并修改 |
| P3 三机静态抓放 | 分别验证 FK/TCP、接触夹持或吸附、释放、入箱 | 三台各自通过；第三台问题独立处理 |
| P4 连续动态分拣 | 追踪拦截、工作区、目标归属、三机并行、失败回收 | 三臂不停带分拣与独立账本 |
| P5 Agent 与跨宿主 | 空场景生成、后续修改、干净安装；逐宿主实测 | 支持矩阵和真实工具轨迹 |
| P6 展示与开源 | 光照/镜头、连续原片、宣传片、README、release | 可安装、可运行、可核验的开源版本 |

阶段失败就修复其具体原因，不能用更复杂界面或额外 Agent 角色掩盖。第一版不需要新聊天前端、资产网站、分布式调度或 RL 训练框架。

## 11. 建议仓库内容

| 路径 | 内容 |
| --- | --- |
| `src/simscene/` | core、assets、compose、session、MCP、CLI |
| `src/simscene/backends/isaac/` | worker 和固定版本适配 |
| `src/simscene/behaviors/` | 输送、投料、抓放及状态机 |
| `src/simscene/verification/` | 独立检查器和报告 |
| `skills/build-scene/SKILL.md` | 一个通用主 skill |
| `skills/build-scene/references/` | schema、操作和错误处理说明 |
| `profiles/` | 已验证机器人、传送带、料箱及运行档 |
| `recipes/` | 工作台、多米诺、三臂分拣等组合示例 |
| `plugins/` | 打包源元数据和生成宿主安装包的脚本 |
| `integrations/` | Codex、Claude Code、DSH 接入与配置生成器 |
| `tests/unit/` | CPU 逻辑测试 |
| `tests/sim/` | 实际仿真集成测试 |
| `tests/agent/` | 自然语言任务与独立验收配置 |
| `docs/` | 安装、支持矩阵、实现、验收、资产来源 |
| `examples/three_arm_sorting/` | Demo 配方、调参配置、运行说明 |

构建时分别生成 `dist/portable/simscene/`、`dist/claude/simscene/`，以及需要时的 `dist/dsh/dsh-simscene/`。各宿主包包含自己的 manifest、共享 skill 的副本和实际可用启动器，不引用包外开发源码；DSH 若仅支持配置 patch 就明确标注。对外注册只启动轻量 MCP 服务，Isaac 安装独立管理。

建议自有代码使用 Apache-2.0；复用上游代码保留原许可证和署名。资产按各自条款管理，仓库默认提交来源清单、适配配置和下载代码，不把所有资产套用代码许可证重新发布。[S06]

## 12. 预期 CLI 与交付物

以下命令是要实现的产品接口，不表示已经安装存在：

```bash
simscene doctor --json
simscene mcp
simscene assets inspect <asset-reference>
simscene build --spec scene.yaml --output scenes/demo
simscene run --scene scenes/demo --seed 17 --output runs/demo-seed17-001
simscene verify --run runs/demo-seed17-001 --case tests/agent/three_arm_sorting.acceptance.yaml
simscene render --run runs/demo-seed17-001 --camera overview
simscene install --client codex
simscene install --client claude-code
simscene install --client deepseek-harness
```

其中 build/run/verify 均调用与 MCP 相同的核心，不能实现两个不同版本。安装命令生成并展示实际客户端配置，逐项报告生成、注册和安装结果；不要覆盖现有用户设置。示例输出路径不能在正式测试中重复使用。

场景包保存初始 `scene.usd`、应用 layers、`scene.intent.yaml`、`scene.resolved.json`、`assets.lock.json` 和控制配置。每次正式运行的独立目录至少保存：

- `run.json`：唯一 run ID、场景 revision/内容 hash、冻结用例引用、开始/结束状态。
- 所用场景包的快照或锁定内容引用。
- `runtime.lock.json`、`controllers.json`、seed 和时间步。
- `agent_trace.jsonl`、`scene_edits.jsonl`、`events.jsonl`。
- 物体轨迹、关节状态、抓持/接触、落箱结果。
- `verification.json` 与可读报告；含所有失败和未运行项目。
- 连续全景原片、必要的抓取特写；另生成约 60–90 秒展示片。
- 从干净初始状态重建和重跑的实际命令。

优先在该次运行中同步录制视频；离线渲染读取该 run 已保存的状态或帧。若重新模拟，创建新的 run ID，不能把重跑得到的镜头当作原运行的证据。

发布 README 明确：已支持的 runtime、机械臂和夹具、控制方式、oracle/vision 状态、客户端实际测试情况、已知限制。展示页的指标来自对应 release 版本的实际运行。

## 13. 发给本地 Codex 的执行指令

请在 `ros-claw/simscene` 新仓库落实本说明。先检查组织下是否已有同名仓库，避免覆盖；已有时先读取仓库说明与当前实现。使用实际本机环境完成 P0，再按阶段交付。每一阶段提交可审查代码、实际日志和下一阶段所需接口。

优先完成“真实 Agent 调用插件，在 Isaac Sim 中搭建并运行场景”的纵向闭环，然后扩展三臂连续分拣和不同 Agent 客户端。第一版保持一个共享 Python 核心、一套 MCP 工具、少量 skill 和参数化配方。

三种机械臂资产与控制配置分别验证；支持档发生替换时准确记录。输送、抓取与放置必须通过声明的物理机制运行。正式验收前冻结配置与阈值，保存成功与失败。缺少某个客户端、凭据、GPU 或所需控制配置时，完成其他可执行工作并明确报告该项 BLOCKED/NOT RUN；不得把静态检查、mock、旧录像或手写完成回复作为实际仿真结果。

当所有核心验收通过后，完成开源说明、干净安装复现和演示视频，输出最终实施报告，逐项对应第 0.1 节。

## 14. 官方资料

- [S01 Isaac Sim releases](https://github.com/isaac-sim/IsaacSim/releases)
- [S02 Isaac Sim 6.2 release notes](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/overview/release_notes.html)
- [S03 State Machines for Robot Behavior](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/state_machine_tutorials/tutorial_state_machines.html)
- [S04 Conveyor Belt Utility](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/assets/asset_utilities/ext_isaacsim_asset_gen_conveyor.html)
- [S05 Surface Gripper Extension](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/robot_simulation/ext_isaacsim_robot_surface_gripper.html)
- [S06 Manipulator Robot Assets](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/assets/usd_assets_robots_manipulator.html)
- [S07 cuMotion Robot Configuration](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/cumotion/tutorial_robot_configuration.html)
- [S08 Pick and Place Example](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/robot_setup_tutorials/tutorial_pickplace_example.html)
- [S09 OpenAI Package Your Plugin](https://developers.openai.com/plugins/build/plugins)
- [S10 Codex MCP](https://developers.openai.com/codex/mcp)
- [S11 DeepSeek Harness MCP Client](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)
- [S12 Claude Code Plugin Manifest](https://code.claude.com/docs/en/plugins-reference)
- [S13 DeepSeek Agent Integrations](https://api-docs.deepseek.com/quick_start/agent_integrations/)
- [S14 DeepSeek Harness Skills](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/skills)
- [S15 Claude Code Plugin Evals](https://code.claude.com/docs/en/plugin-evals)
- [S16 OpenUSD SdfChangeBlock](https://openusd.org/release/api/class_sdf_change_block.html)
- [S17 Codex Skill Discovery](https://learn.chatgpt.com/docs/build-skills)
- [S18 SimReady Central Library Documentation](https://docs.omniverse.nvidia.com/simready/latest/simready-central.html)
- [S19 NVIDIA USD Search](https://github.com/NVIDIA-Omniverse/usd-search)
- [S20 Scene Synthesizer Object Arrangement](https://scene-synthesizer.github.io/concepts/arranging_objects.html)
- [S21 Conveyor Python API](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/py/source/extensions/isaacsim.asset.gen.conveyor/docs/index.html)
- [S22 Create a Claude Code Plugin](https://code.claude.com/docs/en/plugins/create)
- [S23 Package and Install a DeepSeek Harness Plugin](https://deepseek-harness.github.io/deepseek-harness/en/develop/basic/publish)
- [S24 Isaac Sim Agent Skills](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/development_tools/agent_skills.html)
- [S25 Omniverse Kit USD Agents](https://github.com/NVIDIA-Omniverse/kit-usd-agents)

所有外部组件在实施时固定 release 或 commit；查阅和运行与实际安装一致的文档/API。本文来源核对日期为 2026-10-28。

