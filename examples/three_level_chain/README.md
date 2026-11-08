# 三层被动机械连锁

64个动态体：4个球、60块轻质立片。唯一的起球在第60物理步释放；其余运动由重力和接触传递。三个高度为1.65、1.25、0.85米，末段为36块蓝/青/橙立片组成的半圆波浪。

这是独立Agent完成构建和验证后导出的复现数据，没有作为答案提供给该Agent。三个固定在线来源共302,696,259字节所选文件：HF固定版本货架、工作台，以及NVIDIA蓝色零件盘；重复料盘共享资产。模型和贴图不进Git。

先安装仓库及USD绑定、配置Isaac 6.2与启用zscale的FFmpeg，再从仓库根目录执行：

```sh
export SIMSCENE_HOME="$PWD/state/chain-reproduction"
python3 experiments/acquire_recipe_assets.py examples/three_level_chain/assets.lock.json --cache "$SIMSCENE_HOME/cache" --catalog-output /tmp/chain-assets.json
python3 experiments/apply_scene_recipe.py examples/three_level_chain/recipe.json --scene-id chain_example --asset-catalog /tmp/chain-assets.json --save-directory "$SIMSCENE_HOME/recipe"
simscene run --scene chain_example --steps 1500 --seed 42 --case examples/three_level_chain/case.json
```

使用上一步返回的真实run目录检查：

```sh
python3 experiments/passive_chain_check.py /absolute/path/to/run examples/three_level_chain/case.json --output /tmp/chain-check.json
```

该独立检查器在仓库实验工具中；当前stock `run_verify` 尚不分发这个新case类型，worker退出成功也不等于连锁通过。检查器核对case快照、输入输出锁、唯一触发、初始安静、逐边接触顺序、末态倾倒与最后两秒的容纳/稳定。

`edit-operations.json` 应用到上述原场景，将中台抬高15厘米、接收盘右移20厘米，并调整相邻支撑/轨道/摄影；其余动态体ID和接触网络保留。之后以 `case-edited.json` 冻结新run再检查。`verify_chain_suite.py` 接收多个真实run的manifest，检查同配置三次干净重复、只删除一个体的无触发/断链负对照以及修改恢复。

本机已用全新缓存重新取得全部所选文件并核对指纹，配方从空状态通过schema/USD导出；这不是第二台机器的完整运行验证。完整源场景的三次重复、负对照与修改恢复，以及相对引用交付工程重跑，见[验证范围](../../docs/validation.md#three-level-passive-chain)。

物理近似明确保留：金属球用球体碰撞包络和指定轻量空壳质量，转动惯量仍采用primitive默认；立片为76.5kg/m³的轻质泡沫聚合物近似。在线道具为保留原材质的视觉资产，接触由对齐可见表面的静态分块代理承担。
