# 影片与逐帧出处

[公众版](../../../docs/media/only-one-sugar-public-55s.mp4)为 55 秒、1080p30：27 秒原始双机位素材、23.5 秒新增机位的原速记录重渲染、2 秒片头定帧和 2.5 秒片尾。不同片段之间省略仿真时间，不能称为 55 秒连续主链。[慢动作版](../../../docs/media/only-one-sugar-details-20s.mp4)是独立 20 秒作品，0.5×、无插帧；不计入物理验收时长。[红绳对照](../../../docs/media/red-rope-causal-comparison-20s.mp4)使用两个独立 reset 的原生记录，12 秒分屏原速、4 秒结果定帧及 4 秒字卡。

`evidence/` 包含每个输出帧的原始 run、物理步、源帧、来源类别、剪辑段及速度。原始记录与新增机位分别保存指纹，路径通过 source ID 索引。完整工作站收据另行保留；原 106 秒导演片和两个 130 秒连续源片均未修改。

## 为已有记录补拍

在宿主安装 `.[replay]`，提供有完整逐步位置和姿态的运行目录。镜头文件为数组，例如：

```json
[{"id":"detail","start_step":2100,"end_step":2340,"stride":2,"playback_fps":30,"camera":{"position":[9.45,1.35,1.65],"target":[10.18,0.22,0.85],"focal_length_mm":38}}]
```

```sh
simscene replay prepare --run /path/to/run --shots /path/to/shots.json --output /path/to/new-replay
simscene replay render --request /path/to/new-replay/request.json --isaac-python /path/to/isaac-sim/python.sh
simscene replay status --request /path/to/new-replay/request.json
```

`render` 后台进入现有 GPU 队列，`status` 将真实进程退出与渲染收据分开检查。`stride:1`、30 fps 对 60 Hz 记录产生 0.5× 慢动作。跟拍相机可将 position/target 换成 `follow_body`、`eye_offset` 和 `target_offset`。所有相机数值都是此作品的构图，不是通用坐标。

## 重新剪辑

`finish_showcase.py` 用原始 MAIN1 双机位和九段 replay 素材生成公众版或慢动作版；`build_rope_comparison.py` 用原对照片的 edit manifest 定位两个原生源文件。脚本的 `--help` 列出源路径参数。它们不重跑物理，输出目录必须全新。原生双机位专用的 `build_public_cut.py` 是早期剪辑入口；最终版采用前两个脚本。

剪辑显式指定恒定 30 fps，逐帧核对 PTS，避免“帧数正确、尾帧时长不正确”。主片杯响为后期拟音，完整 PCM 音轨中的起点映射到原物理第 5858 步首次碰杯；实际 AAC 数字解码检查起点为成片 49.633333 秒，峰值约 −11.89 dBFS。未声称进行过手机扬声器听审或陌生观众静音理解测试。
