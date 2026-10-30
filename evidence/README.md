# Public validation records

This directory contains selected validation summaries and JSON observations
needed by the CPU regression tests. The full local evidence archive, including
downloaded geometry and native recordings, is intentionally not distributed in Git.

No raw agent transcripts, credentials, robot model geometry, textures, cache
directories or installed vendor packages are included. Paths inside historical
records identify their original simulation-host locations; they are not an
instruction to create those paths on another machine.

## Validation summaries

- [Frozen physical suite](isaac-6.2-v29-formal-suite/formal-suite-verification.json)
- [Three paired negative controls](isaac-6.2-v29-formal-suite/negative-suite-result.json)
- [Fresh workbench case](agent-v30d-suite/workbench/verification.json)
- [Fresh online discovery case](agent-v30d-suite/online/verification.json)
- [Fresh three-arm composition](agent-v30e-suite/three_arm/verification.json)
- [Route swap](agent-v30e-suite/swap/verification.json)
- [Original strict retime failure](agent-v30e-suite/retime/verification.json)
- [Original relocation failure](agent-v30e-suite/relocate/verification.json)
- [Separately frozen retime repair](agent-v30-edit-repairs/retime_repair/verification.json)
- [Fresh relocation repair](agent-v30-edit-repairs/relocate_repair/verification.json)
- [Relocated project replay](agent-v30-delivery-replay/run/project-verification.json)
- [Replay integrity summary](agent-v30-delivery-replay/integrity.json)
- [Installed MCP smoke test](local-install-v30/runtime-smoke.json)

Summaries alone cannot reproduce the original hash checks without their full
run snapshots. The implementation report preserves that distinction.

## Regression recordings

The top-level domino, repeated-grasp, parallel-grasp and short-stream JSON
recordings are historical observations used to test the independent verifiers.
Their presence is not a claim that CPU CI re-executes those physical scenarios.

# 20261030 视觉升级

精选摘要见 [visual-upgrade-v31](visual-upgrade-v31/README.md)：原生采集对照、完整9/9物理验证、空场景工作台3/3落料、核心冻结检查及本次测试记录。完整录像、第三方模型与原始工具过程仍在本工作站忽略目录，不整体进入Git。原有证据及失败结论保持原样。

