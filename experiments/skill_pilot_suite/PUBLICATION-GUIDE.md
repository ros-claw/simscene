**可公开为一次已结束的可复现 pilot 示例；不要继续把这两道公开题当新的陌生盲测题。**

[PUBLICATION-FILE-LIST.json](PUBLICATION-FILE-LIST.json)列出精确源文件、建议相对路径及 SHA256；没有执行复制、上传或发布。建议包结构为 `original-design/`、`supplementary-v2/`、`historical/`、`results/`。

原设计可以逐字节带出 DESIGN-FREEZE.json 中列出的全部 11 文件，加 DESIGN-FREEZE.json 本身：两题 prompt/case、原 score.py、原 identity freezer、原抽象 CPU 测试、通用 smoke ops、验收/README/设计期 CPU 记录。保留原字节和哈希，不能用已修复文件覆盖原版。设计期“尚未运行”的声明描述当时状态，不把它改写成后来结果。

补充 v2 单独带出 score_v2.py、test_interfaces_cpu.py、README.md、CHANGE-RECORD.json、原版到 v2 的 diff、CPU-REGRESSION-RESULT.json 及单独的 SUPPLEMENTARY-FREEZE.json。它是事后版本，只修 collision 与空 joints 接口；所有物理数值谓词和公开 case 字节未变。原结果与补充结果要并列，保留本轮正式 0/4，而不是把 P1 的事后物理通过改成预算内任务通过。

操作协议和候选包清单本身只含身份/路径/哈希，可保留精确原协议 JSON 及其哈希；它们引用本机绝对路径，是历史证据而不是别的主机可直接执行的配置。可另写 wrapper/示例配置来定位本地原设计、冻结 v43、Isaac、独立 state 和 cache，使用新实验 ID；不要编辑原协议来假装字节未变。原 score.py 通过所在目录相对寻找设计文件；v2 通过 `--design-root` 显式指定。例：

```bash
PYTHONPATH=/local/pinned-v43/src python3 original-design/examiner/score.py --task P1 --positive /local/sealed/positive --negative /local/sealed/control --identity /local/approved-runtime.json
PYTHONPATH=/local/pinned-v43/src python3 supplementary-v2/score_v2.py --design-root /local/example/original-design --task P1 --positive /local/sealed/positive --negative /local/sealed/control --identity /local/approved-runtime.json
PILOT_ORIGINAL_DESIGN=/local/example/original-design PYTHONPATH=/local/pinned-v43/src python3 supplementary-v2/test_interfaces_cpu.py
```

原检查器会核对被冻结的通用 reader 字节；新主机需要可取得的匹配 v43 依赖，不能删除/放宽 guard 来获得“可移植”。无需重复打包整个 A/B toolkit，更不要分发 proprietary Isaac 安装。依赖安装位置由 wrapper 指定，精确软件身份由已有清单给出。新增 native 运行应在新主机使用同一公开契约原文件 case_path pin，并从自己的非试题烟测生成一个新的独立 runtime identity；这属于新的复现实验，不能冒充原历史 run。

原历史 evidence-lock/run-lock 包含绝对资源和 launcher 路径，换机单纯复制日志未必能通过全部保管检查。历史评分报告、输入/输出哈希及原 artifact 位置可供审查；不要改历史路径再重新封存来声称原签收。若另发 native 示例证据，保留原始文件与原路径含义，说明依赖范围；不必重复附每个 run 的完整 worker/toolkit 副本。

公开数值可用 usage-summary-public.csv、REVIEW-SUMMARY.json、REVIEW.md、recorded-token-costs.svg 和原/补充分臂评分报告。不要带出 raw-session.jsonl、未脱敏 events/tool envelopes、账户/用户/会话元数据、response IDs、私有请求 usage 原始行或整个 pilot-independent-review/records 目录。已公开汇总刻意不含这些内容。

后续研究必须另起协议，先冻结补充 v2、真正生效的缓存变量和请求边界预算执行方式，再选新的陌生题；本次不追加 trial、不改四臂结果、不提供有效节省率估计。
