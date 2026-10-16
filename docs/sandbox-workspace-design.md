# 每工单隔离工作区设计（首版）

## 目标

将现有“GitHub API 读取少量文件 → Agent 返回整文件 JSON → 直接创建远程提交”改为“完整工作副本 → 本地修改和验证 → 审核 → 推送 PR”。一个工单的测试必须在提交 PR 前真正执行；测试失败不得推送。发布仍是独立流程。

## 已核对的宿主边界

- 当前 DeerFlow 验证实例使用 `LocalSandboxProvider`，`allow_host_bash: false`。该 provider 的本地路径约束不是可运行不可信仓库命令的安全隔离。
- `deerflow-extension-api` 的 `AgentRuns` 只负责创建、等待和读取 Agent run；没有向其工作区写入 Git 仓库或执行测试的公共能力。首版不依赖宿主私有沙箱 API，也不改变 DeerFlow 核心。
- 本机 Docker daemon 可用。扩展以 Docker 容器隔离仓库命令；Gateway 主机的 `gh` 登录态只用于 GitHub 读写，不传入容器或 Agent 提示词。

## 单工单流程

1. 在扩展存储根目录下为 `(repository_id, issue_id)` 分配独立、不可复用的工作目录。只允许一个活跃运行持有该目录；记录基线 commit SHA、Issue 更新时间和运行代数。
2. Gateway 使用 `gh` CLI 认证，在该目录 clone 目标仓库，检出默认分支的固定 SHA，再创建 `code-factory/issue-<number>` 本地分支。远程 clone/push 命令的参数由已验证的 owner/repo 和工单号构造，不接受 Issue 文本作为 shell 命令。
3. 规划 Agent 获得工作副本的受限文件清单、相关源码和 Issue 正文及评论，产出规格与相关路径；编码 Agent 基于同一基线产出文件修改。扩展检查路径、大小与禁改范围后将修改写入工作副本。Agent 不接触 GitHub 凭据。
4. 对工作副本运行配置的检查命令。每个命令在短生命周期 Docker 容器中运行，挂载该工单目录为 `/workspace`。容器禁用网络、移除 Linux capabilities、禁止提权、限制 CPU/内存/PID/执行时间；只给 `/workspace` 可写挂载及临时目录。镜像和命令由运营配置控制，Issue 和 Agent 回复不能修改。
5. 测试失败时把退出码和有界日志交给编码 Agent 修复，同一工作副本最多三轮；超过上限转为失败并保留证据，绝不推送。测试通过后，独立审核 Agent 审核规格、`git diff` 和测试证据；审核阻断问题同样回到修复与重测。
6. 在推送前重新读取 Issue 与默认分支 SHA。Issue 变更或基线漂移时停止并提示重新规划；不能静默覆盖。通过后由 Gateway 在工作副本提交并用 `gh`/`git` 推送工单分支，创建 PR。现有 GitHub CI 和合并规则继续执行，只有全部通过才合并；发布仍单独处理。

## 首版限制与配置

- 首版只验证 Python 仓库：运行镜像固定为运营方指定的 Python 镜像，检查命令默认为 `python -m unittest discover -s tests`。后续按受控模板增加 Node 等技术栈，不根据 Issue 自动生成命令。
- 不运行仓库安装脚本，不给测试容器网络或 GitHub token；需要依赖时由运营方提供预建镜像。Docker 不可用时启动开发前报明确错误，不回退到 Gateway 主机执行测试。
- 现有已创建 PR 的工单继续走旧的 CI/合并追踪；新启动的 `draft`、`blocked`、`failed` 工单使用新工作区流程。已有工单目录/远程分支冲突时停止并显示恢复指引，不强制覆盖。
- 实现保持在独立扩展内：工作区管理、Docker 检查器、Git 交付各一个小模块；扩展配置增加工作目录根路径、镜像、检查命令和资源限额。不得把这些选项暴露给 GitHub Issue 作者。

## 验收

使用现有私有验收仓库的新 Issue：修改 `counter.py` 和测试文件；记录本地 unittest 成功输出、固定基线、审查结果、PR head SHA、GitHub CI 与合并结果。另用故意失败的测试证明扩展不会推送 PR。验证服务重启后不会自动重复编码或覆盖远程分支。
