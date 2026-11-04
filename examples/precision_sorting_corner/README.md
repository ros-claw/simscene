# 精密制造车间增量配方

`recipe.json` 是对已有兼容三臂工作站的普通 scene operations：12类在线道具、31个导入实例、明确支撑面与活动保留区、灯光和两个原生高清机位。它需要首版兼容的机器人、控制器、动态工件及验收case；不会从空场景凭空创建已适配的三臂物理系统。

先按需取得配方所选资产，再应用到已有场景：

```sh
python3 experiments/acquire_recipe_assets.py examples/precision_sorting_corner/assets.lock.json --cache /simulation-host/cache --catalog-output /tmp/workshop-assets.json
python3 experiments/apply_scene_recipe.py examples/precision_sorting_corner/recipe.json --scene-id YOUR_EXISTING_THREE_ARM_SCENE --asset-catalog /tmp/workshop-assets.json --save-directory /simulation-host/workshop-recipe
```

此配方中的remove/update依赖兼容的源对象ID，适合审阅后复用；已有不同布局时应根据测量结果重新规划，不能直接套坐标。配方保留正式完整验证时的相机路径。最后成片的Panda特写采用额外侧面短运行，以避开计数板遮挡；见 `panda-side-camera.json`。该文件是普通相机操作数据，应用前确认源场景含 `detail` 相机，运行4200步可覆盖第一次Panda循环，录制窗口2820–4200步。它不是新的场景专用工具。

原case只能在控制器、生成顺序、碰撞与物理不变量一致时重绑来源scene哈希。重新组合之后需重新完整验证。完整本地工程和源录像见 [验证范围](../../docs/validation.md)。
