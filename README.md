# DeerFlow Code Factory Extension

独立的 DeerFlow 扩展项目。首版以 GitHub Issue 轮询为需求入口，验证从需求分析、设计、编码、独立审核、测试到 PR 合并的完整开发流程。需求完成后标记为“已完成、待纳入版本”；发布是后续独立流程。

- [产品与技术规格](docs/spec.md)
- [首版实施计划](docs/implementation-plan.md)
- [真实端到端验收记录](docs/acceptance.md)

当前已实现代码工厂管理页：选择 GitHub、输入已有仓库的 HTTPS 地址并点击‘加入’，验证后确认创建缺失标签、启停、手动扫描、查看工单，并可对每个工单显式点击“开始开发”。GitLab 暂时不可选，留待后续适配。后台每 180 秒通过 Gateway 进程的 `gh` CLI 登录态轮询已启用的仓库。进入轮询的 Issue 必须带 `factory:ready` 标签；PR 会被排除。启动后，DeerFlow Agent 分别完成规格分析、编码和独立审核。审核通过的文件通过 GitHub Git Data API 提交到 `code-factory/issue-<number>` 分支并创建 PR。后台按 PR head SHA 检查 CI；至少有一项检查且全部通过后，尝试按 GitHub 仓库规则 squash 合并。若需要人工审批，保持 `awaiting_merge`；合并成功后给原 Issue 添加 `factory:done` 标签。发布仍是独立流程。

当前限制：仅支持已有且有默认分支的仓库；代码 Agent 每轮最多修改 50 个 UTF-8 文本文件、总量 256 KiB，不允许修改 `.github` 工作流；最多三轮审核。CI 失败会进入 `failed_checks`，暂未自动修复。服务重启会中止运行中的 Agent 阶段，需在界面重新启动；已创建的分支或 PR 不会自动覆盖。已在隔离私有仓库完成一次 Issue 到合并验收，详见[验收记录](docs/acceptance.md)。

## 运行前提

Gateway 主机安装 `gh` 并先以专用 GitHub 身份运行 `gh auth login`。该身份需要目标仓库的推送权限；创建标签还需要 Issues 写权限。`gh` 登录态是 Gateway 进程级共享资源，必须把扩展的 `operator_user_ids` 限制为可信的 DeerFlow 用户。首次安装的扩展配置示例：

```yaml
plugins:
  - use: deerflow_code_factory:install
    enabled: true
    config:
      enabled: true
      storage_path: /absolute/path/to/code-factory.sqlite
      operator_user_ids: ["your-deerflow-user-id"]
      poll_interval_seconds: 180
```

先用 `make extension-install SOURCE=/Users/zhfeng/works/deerflow-code-factory-extension` 安装包，再在 `config.yaml` 的相应 `plugins` 记录设置上述配置。外层 `enabled` 控制包加载，内层 `config.enabled` 控制界面贡献。该扩展应安装在单个 Gateway 进程上；多实例轮询协调尚未实现。重启 Gateway 后，从工作区侧栏打开“代码工厂”。

进度和宿主接口缺口见 [实施进度](docs/progress.md) 与 [宿主能力探针](docs/host-capability-probe.md)。目标宿主是 `/Users/zhfeng/works/deer-flow`。
