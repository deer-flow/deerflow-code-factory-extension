# DeerFlow Code Factory Extension

DeerFlow 的独立代码工厂扩展。它以 GitHub Issue 为需求工单，把需求分析、编码、独立审核、本地测试、PR 审核意见修复、CI 检查和合并串成一个可观察的流程。**完成需求不会发布软件包、Release 或镜像**；发布属于独立流程。

当前版本面向已有 GitHub 仓库，使用 Gateway 主机的 `gh` CLI 登录态，每 180 秒轮询一次。GitLab 等来源保留界面入口，但尚未实现。代码工厂管理页位于 DeerFlow 的“工作区 → 代码工厂”。

## 工作流程

1. 在管理页选择 GitHub，输入现有仓库的 HTTPS 地址并加入。扩展验证仓库及权限，并创建缺失的 `factory:*` 标签。
2. 给待处理的 Issue 加上 `factory:ready`。轮询发现后，工单出现在所选仓库列表中；操作员点击该工单的“开始开发”。
3. Agent 分析 Issue、最近评论和仓库上下文，在独立的仓库 clone 中编码。每轮改动在无网络的 Docker 容器中测试，失败后最多修复三轮；另一个 Agent 审核通过后创建 PR。
4. 扩展在 PR 中发布本地测试与独立审核摘要。新的外部审核意见会触发同一 PR 分支上的修复、重新测试和复审，并回复对应讨论；外部审核讨论须由审核者确认解决。
5. 后台持续检查当前 PR 提交的 CI、审核请求、未解决讨论和配置的真人批准。门槛全部满足才尝试 squash 合并。检测到 GitHub 上的手工合并时，工单显示“已手工合并”。合并确认后，Issue 添加 `factory:done` 并移除 `factory:ready`。

界面在开发中每 10 秒查询所选仓库的工单状态，在等待 CI/审核/合并时每 30 秒查询；完成或页面隐藏时停止。这只是界面状态更新，独立于 Gateway 的 180 秒 GitHub 轮询。

## 安装

前提：DeerFlow Gateway 主机安装并登录 `gh`，Docker daemon 可用，检查镜像已预先准备好。建议使用专用 GitHub 自动化账号；它需要目标仓库的读写权限及 Issues、PR 权限。运行 `gh auth status` 和 `docker info` 可检查本机环境。仅将 `operator_user_ids` 配置为可信的 DeerFlow 用户，因为 `gh` 登录态由 Gateway 进程共享。

从可信的本地源码目录安装：

```bash
make extension-install SOURCE=/absolute/path/to/deerflow-code-factory-extension
```

然后在 DeerFlow 根目录的 `config.yaml` 中配置已安装的插件记录（保留安装命令写入的 `name` 和 `package` 字段）：

```yaml
plugins:
  - name: code-factory
    package: deerflow-code-factory-extension
    use: deerflow_code_factory:install
    enabled: true
    host_access:
      model_invocation:
        roles:
          repair: your-configured-model-name
          review: your-configured-model-name
    config:
      enabled: true
      storage_path: /absolute/path/to/code-factory.sqlite
      workspace_root: /absolute/path/to/code-factory-workspaces
      operator_user_ids: ["your-deerflow-user-id"]
      poll_interval_seconds: 180
      check_image: python:3.12-slim
      check_command: python -m unittest discover -s tests
      required_checks: [unit]
      approver_logins: [human-reviewer]
      automation_login: factory-bot
```

`repair` 和 `review` 模型角色用于 PR 审核意见后的修复与复审。`required_checks` 是必须出现且成功的 CI 名称；建议明确配置。`approver_logins` 应列出可最终批准的真人账号，不能使用 PR 作者或自动化账号；未配置时自动合并始终等待人工批准。重启 Gateway 后扩展才会加载新配置。升级扩展使用 `make extension-upgrade SOURCE=/absolute/path/to/deerflow-code-factory-extension`，随后同样重启 Gateway。

`workspace_root` 应是 Gateway 可写的专用目录。工作副本会保留以便排查，运营方需定期清理。此版本只支持单个 Gateway 实例；多实例轮询协调尚未实现。

## 状态与限制

PR 创建后，工单可依次显示“等待检查”“等待审核”“处理审核意见”“审核受阻”“等待人工批准”“等待合并”，最终显示“已自动合并”或“已手工合并”。CI 失败显示为 `failed_checks`，需要人工处理。GitHub 数据读取不完整或门槛不满足时不会自动合并。

每轮编码最多修改 50 个 UTF-8 文本文件，总量不超过 256 KiB；Agent 不能修改 `.github` 工作流。默认检查命令适用于 Python 项目；其他技术栈需提供预建检查镜像和对应命令。服务重启会中止运行中的 Agent 阶段，需要在界面重新启动；已创建的分支或 PR 不会自动覆盖。私有验收仓库的旧版 Issue → PR → CI → 合并路径已做真实验收，见[验收记录](docs/acceptance.md)；**新增的真人批准与审核意见修复门槛目前由自动化测试覆盖，尚未用两个 GitHub 身份完成真实端到端验收**。

设计与实现记录：[规格](docs/spec.md) · [实施计划](docs/implementation-plan.md) · [PR 审核及合并门槛](docs/superpowers/specs/2026-10-16-pr-review-and-merge-gates-design.md) · [进度](docs/progress.md)。

## 许可证

本项目采用 [MIT 许可证](LICENSE)。
