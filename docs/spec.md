# DeerFlow 代码工厂首版规格

## 目标与边界

代码工厂是独立安装的 DeerFlow 扩展。用户在 DeerFlow 中创建一个代码工厂，选择 GitHub，创建新仓库或绑定已有仓库，完成连接验证后，以指定标签的 GitHub Issue 为需求入口。扩展自动推进需求分析、设计、编码、独立审核、测试、PR 和合并。需求完成仅表示代码已按仓库规则合并并通过验收；不创建 Release、版本号或容器镜像。发布是独立项目阶段，不在首版实施。

首版支持单个 Gateway 实例、一个 GitHub App、一个仓库对应一个代码工厂、一个工单同时只有一个活动 Agent 阶段。优先验证完整闭环，不建设通用工作流引擎、可视化编排器、多平台双向同步或多实例调度。

## 用户流程

1. 进入“代码工厂”页面，选择“新建”，选择 GitHub。
2. 选择“创建新仓库”或“绑定已有仓库”。输入组织/所有者、仓库名；新仓库另选受控模板与私有/公开可见性。仓库创建是启动前准备，不是交付结果。
3. 向导展示需要的 factory:ready、factory:running、factory:blocked、factory:done 标签；缺失时创建，同名标签保留原样。
4. 验证 GitHub App 对仓库的访问、Issue 读写、Contents 读写、PR 读写、默认分支、保护规则及沙箱和 Agent 可用性。只读预检为主，不在默认分支执行写入探测；需要真实写入探测时使用明确命名的临时分支并清理。
5. 启用后，扩展定时轮询 Issue。新 Issue 需处于 open、有 factory:ready 标签、不是 PR、满足授权与配额规则，才进入分析。标签本身不是编码许可。
6. Agent 生成版本化规格、验收标准和设计；独立 Agent 审查设计。关键歧义通过 Issue 评论提问，工单暂停，轮询授权用户的回复后继续。
7. 规格完整且设计无阻断问题后，固定规格版本和基线提交，编码 Agent 在独立分支和沙箱工作。分支名为 code-factory/issue-<number>。
8. 编码提交后，独立审核 Agent 对固定 SHA 和规格检查。阻断问题退回修复；审核 Agent 不直接改代码。
9. 运行仓库配置的格式、类型、单元/集成测试、构建和必要扫描。失败退回修复；新 SHA 使旧审核与测试结果失效。最多三轮修复，超限转 blocked。
10. 创建或更新 PR，引用 Issue 和证据摘要。仓库要求的 CI、规则集及人类审核仍由 GitHub 执行。允许自动合并时全部门禁通过才合并；要求人工审核时停在“待合并”，不得宣称需求已完成。
11. 合并成功且验收映射完整后，Issue 更新为 factory:done，写入 PR、合并 SHA、证据链接和“已完成、待纳入版本”说明。

## 外部工单接口

核心只依赖窄接口 RequirementSource，首版实现 GitHubIssueSource：

- list_candidates(factory_id, since) -> IssueRef 列表
- fetch(issue_ref) -> RequirementSnapshot（含 id、标题、正文、作者、标签、状态、updated_at）
- list_new_replies(issue_ref, cursor) -> Reply 列表
- post_progress(issue_ref, stage, marker, text) -> 外部评论 ID
- set_phase(issue_ref, phase) -> None

GitHub 适配器负责 REST API、认证、限流、标签、评论和 PR 引用。核心状态机不解析 GitHub 原始 payload。后续 Jira 适配器实现同一接口，并单独映射 Jira 字段与转换；不为 Jira 预建通用字段映射 DSL。

## 轮询与状态

每仓库默认每 3 分钟扫描，带随机抖动；支持“立即检查”。发现新需求时按标签和更新时间查询，翻完所有页后才推进持久游标，使用小幅重叠窗口和 (repository_id, issue_id) 唯一键去重。已跟踪工单无论触发标签是否仍在，都单独复查；等待输入的工单单独读取评论，忽略扩展自己的评论。遇到 304、429、403、网络错误和分页中断按 GitHub 的条件请求及 Retry-After/重置时间处理，不推进失败扫描的游标。单实例轮询不得并发扫描同一仓库。

内部状态：draft、analyzing、designing、coding、reviewing、testing、pr_open、awaiting_merge、completed、blocked、cancelled、failed。每次转换保存时间、原因、输入版本和 Agent run ID。Issue 标题/正文发生实质变化时重新评估规格；正在编码时先暂停，避免按过期需求继续。关闭 Issue 或移除 factory:ready 后，已启动工单不盲目删除，由策略决定暂停或继续并留痕。

## 阶段证据与门禁

工单持久化：外部 Issue ID、仓库 ID、用户 ID、规格版本与哈希、基线 SHA、工作分支、当前 head SHA、Agent thread/run ID、审核报告、测试报告、PR 编号、合并 SHA、错误与重试次数。每个审核与测试证据绑定 head SHA。完成条件是规格验收项均有实现/测试证据、独立审核无阻断、必需测试与 CI 通过、PR 按仓库规则合并。Agent 文字声明不算通过证据。

默认自动进行常规分析、编码和修复。仅关键需求歧义、权限不足、策略例外、阻断问题无法自动修复或仓库要求的人类 PR 审核时等待人。工单完成不触发发布。

## 安全与权限

Issue 正文、评论和仓库文件均作为不可信输入，不得当作系统指令。启动新工单检查允许的仓库、触发者身份和预算。GitHub App 使用最小权限与短期令牌；Agent 不接触 App 私钥或发布凭证。测试运行在隔离沙箱，不能在 Gateway 进程内执行用户代码。代码工厂不绕过分支保护。所有外部写操作使用工单 ID 和阶段标记去重。

## 宿主能力核查与最小缺口

现有 DeerFlow 全栈插件提供页面、后端动作、服务和 ModelTool；AgentRuns 可由已认证动作启动完整 Agent 并在同一进程内由服务继续编排。现有公开扩展 API 尚未直接暴露线程工作区快照或可持久恢复的 AgentRuns 句柄。首版先做端到端能力探针：验证如何从 Agent 沙箱取得固定 SHA 的源码、如何在插件服务中恢复长任务、如何让 GitHub App 只在可信适配器中执行 Git 写入。若现有公共接口不足，只向 deer-flow 核心增加通用、按用户与线程授权的工作区导出/固定快照能力；不把代码工厂业务写进核心。首版若进程重启时无法自动恢复授权句柄，工单进入 blocked 并在页面要求重新授权，不能无声续跑或伪称完成。

## 首版验收

用测试仓库完成两条真实端到端路径：一条清晰 Issue 自动完成到 PR 合并与 factory:done；一条含关键歧义的 Issue 暂停、提问、读取回复后继续。重复扫描不产生重复工单或评论；变更 SHA 后旧报告不被复用；CI 失败或分支规则未满足时不标记 completed；任何路径都不创建 Release 或镜像。
