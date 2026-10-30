# 从空场景重建维修工作台

这是冻结通用工具后实际MCP组合测试归档的普通场景数据，不需要场景专用runtime。`prompt.txt` 是原始输入，`criteria.json` 是构建前冻结的接收条件；`physical-verification.json` 为实际30秒源运行的检查结果。此次由同一活动Agent执行，不称为独立新Agent评测。

安装仓库与FFmpeg、配置兼容Isaac 6.2后，在仓库根目录执行：

```sh
export SIMSCENE_HOME="$PWD/state/workbench-reproduction"
python3 experiments/acquire_recipe_assets.py examples/maintenance_workbench/assets.lock.json --cache "$SIMSCENE_HOME/cache" --catalog-output /tmp/workbench-assets.json
python3 experiments/apply_scene_recipe.py examples/maintenance_workbench/recipe.json --scene-id maintenance_example --asset-catalog /tmp/workbench-assets.json --save-directory "$SIMSCENE_HOME/recipe"
simscene run --scene maintenance_example --steps 1800 --seed 42
```

下载只获取锁中八类所选来源；缓存默认4GiB。锁检查逐文件内容，包生成时间造成的ZIP哈希变化不会被误当成模型变化。上游内容不同或必要依赖缺失时停止。

实际运行后，可将包含原始criteria、checker和MCP过程记录的本地完整实验目录传给 `experiments/verify_visual_workbench.py`；该实验检查器不是 `simscene run` 的通用物理判定。公开精简配方不带原始本地绝对路径与完整工具trace，也不承诺直接套用原始验收目录。重新生成的run应重新核对三件箱体的下落、接触、落入区域与稳定状态。原始条件和本次测量保留在相邻JSON，不能将旧通过结果视为新运行结果。

录像通过 `video_export` / `video_inspect` 交付，接口见 [视频文档](../../docs/视频交付.md)。完整本机交付还含可直接运行的相对引用工程与连续源录像。
