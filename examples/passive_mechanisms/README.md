# 被动家居机构样机

四份可编辑场景来自 Isaac Sim 6.2 RC 的实际十秒运行：轮盘拨闩后柜门成桥、真实分节绳拉开抽屉、断开抽屉端的匹配对照，以及茶匙倒糖。它们是 P1 桌面样机，不代表全屋挑战已经完成。来源运行与冻结条件的指纹见 [provenance.json](provenance.json)。没有下载资产依赖。

安装本仓库开发版、USD Python 绑定，配置 Isaac `python.sh`。从仓库根目录运行，例如：

```sh
export SIMSCENE_HOME="$PWD/state/passive-examples"
simscene configure --isaac-python /absolute/path/to/isaac-sim/python.sh
simscene import-scene --spec examples/passive_mechanisms/spoon_sugar.json --scene spoon_example
simscene run --scene spoon_example --steps 600 --seed 42 --case examples/passive_mechanisms/spoon-sugar-v1.json
simscene verify --run /absolute/path/to/returned/run
```

将文件换成 `wheel_door_bridge.json` 和 `wheel-door-bridge-v1.json` 可重跑柜门样机。绳索样机使用 `rope_drawer.json`、`rope_disconnected.json`，两次运行均绑定 `rope-drawer-v1.json`。先验证正例，再验证断绳对照：

```sh
simscene verify --run /absolute/path/to/rope-positive
simscene verify --run /absolute/path/to/rope-disconnected --mode detached_drawer --reference-run /absolute/path/to/rope-positive
```

正例单独通过不能证明绳子必要。检查器读取每步物理记录、关节、轮槽接触、抽屉行程、杯内八角点与稳定保持；它不控制机构。验收条件在正式运行前冻结，并非按照成功结果回填。

所有机构以简单分块几何近似，关节没有主动驱动。绳为有质量的胶囊段与球关节，过滤绳段之间的自碰撞，保留外部碰撞；线性和角阻尼均为 5。P2 后续试验采用了不同阻尼，不能称为这些 P1 场景的同物理配置。柜门承托、释放凸耳、抽屉和茶匙均由真实接触及被动约束工作。记录采用严格初态恢复和 60 Hz 逐步观测；原片为原生 1080p30。详情见 [通用机构接口](../../skills/build-scene/references/passive-mechanisms.md)。
