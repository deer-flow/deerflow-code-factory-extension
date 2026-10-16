const copy = {
  zh: { title: "代码工厂", intro: "连接仓库，验证后轮询带 factory:ready 标签的 Issue。", provider: "代码平台", repoUrl: "仓库地址", join: "加入", urlHint: "请输入 GitHub 仓库地址，例如 https://github.com/owner/repo", labels: "缺少的标签", confirm: "创建缺少的标签", factories: "已连接的仓库", selectRepo: "选择仓库", ticketId: "工单号", issueId: "Issue 号", issueTitle: "标题", phase: "状态", prId: "PR 号", updated: "最后更新时间", actions: "操作", noTitle: "标题尚未同步", refresh: "刷新状态", empty: "尚未连接仓库。输入仓库地址后点击加入。", loading: "正在加载…", disabled: "未启用", enabled: "已启用", enable: "启用", disable: "停用", scan: "立即扫描", jobs: "需求工单", noJobs: "尚未发现符合条件的 Issue。", start: "开始开发", started: "开发任务已启动", error: "操作失败，请检查 gh 登录状态和仓库权限。", validated: "仓库验证通过", invalid: "仓库尚不能启用", created: "仓库已加入代码工厂", scanned: "扫描完成，新发现 {count} 个工单。", cursor: "上次扫描游标", noCursor: "尚未扫描" },
  en: { title: "Code factory", intro: "Connect a repository, then poll Issues labeled factory:ready after validation.", provider: "Platform", repoUrl: "Repository URL", join: "Add", urlHint: "Enter a GitHub repository URL, such as https://github.com/owner/repo", labels: "Missing labels", confirm: "Create missing labels", factories: "Connected repositories", selectRepo: "Select repository", ticketId: "Ticket", issueId: "Issue", issueTitle: "Title", phase: "Status", prId: "PR", updated: "Last updated", actions: "Actions", noTitle: "Title not synced yet", refresh: "Refresh status", empty: "No repositories connected. Enter a repository URL and select Add.", loading: "Loading…", disabled: "Disabled", enabled: "Enabled", enable: "Enable", disable: "Disable", scan: "Scan now", jobs: "Requirement tickets", noJobs: "No eligible Issues found yet.", start: "Start development", started: "Development job started", error: "Action failed. Check gh authentication and repository permissions.", validated: "Repository validated", invalid: "Repository cannot be enabled yet", created: "Repository added to code factory", scanned: "Scan complete. {count} new tickets found.", cursor: "Last scan cursor", noCursor: "Not scanned" },
};

export function parseRepositoryUrl(provider, value) {
  if (provider !== "github") throw new Error("This platform is not supported yet.");
  let url;
  try { url = new URL(value.trim()); } catch { throw new Error("Invalid GitHub repository URL."); }
  const parts = url.pathname.split("/").filter(Boolean);
  if (url.protocol !== "https:" || url.hostname !== "github.com" || url.port || url.username || url.password || url.search || url.hash || parts.length !== 2) {
    throw new Error("Invalid GitHub repository URL.");
  }
  const owner = parts[0];
  const repo = parts[1].replace(/\.git$/, "");
  if (!/^[A-Za-z0-9][A-Za-z0-9-]*$/.test(owner) || !/^[A-Za-z0-9._-]+$/.test(repo) || repo === "." || repo === "..") {
    throw new Error("Invalid GitHub repository URL.");
  }
  return { owner, repo };
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

const phaseZh = { draft: "待启动", planning: "分析中", coding: "编码中", reviewing: "审核中", blocked: "待补充", awaiting_checks: "等待 CI", failed_checks: "CI 失败", awaiting_merge: "等待合并", done: "已完成", failed: "失败", stale_head: "代码已更新", closed: "PR 已关闭" };

function mount(root, context) {
  const t = context.locale?.startsWith("zh") ? copy.zh : copy.en;
  const style = el("link");
  style.rel = "stylesheet";
  style.crossOrigin = "use-credentials";
  style.href = new URL("./styles.css", import.meta.url).href;
  const shell = el("main", undefined, "factory-shell");
  const header = el("header", undefined, "factory-header");
  header.append(el("p", "DEERFLOW / FACTORY", "eyebrow"), el("h1", t.title), el("p", t.intro, "intro"));
  const form = el("form", undefined, "factory-form");
  const providerLabel = el("label", t.provider);
  const providerSelect = el("select");
  const githubOption = el("option", "GitHub"); githubOption.value = "github";
  const gitlabOption = el("option", "GitLab（即将支持）"); gitlabOption.value = "gitlab"; gitlabOption.disabled = true;
  providerSelect.append(githubOption, gitlabOption); providerLabel.append(providerSelect);
  const repoLabel = el("label", t.repoUrl);
  const repoInput = el("input"); repoInput.type = "url"; repoInput.required = true; repoInput.maxLength = 300; repoInput.autocomplete = "url"; repoInput.placeholder = "https://github.com/owner/repo";
  repoLabel.append(repoInput);
  const join = el("button", t.join, "primary"); join.type = "submit";
  const setupResult = el("div", undefined, "setup-result");
  const message = el("p", "", "message"); message.setAttribute("role", "status");
  const error = el("p", "", "error"); error.setAttribute("role", "alert");
  const section = el("section", undefined, "factory-list");
  const sectionHeader = el("div", undefined, "section-header");
  const refreshButton = el("button", t.refresh); refreshButton.type = "button";
  sectionHeader.append(el("h2", t.factories), refreshButton); section.append(sectionHeader);
  const cards = el("div"); section.append(cards);
  form.append(providerLabel, repoLabel, join);
  shell.append(header, form, setupResult, message, error, section);
  root.append(style, shell);
  let disposed = false;
  let sequence = 0;
  const active = () => !disposed && !context.signal.aborted;
  async function action(button, fn) {
    button.disabled = true; error.textContent = ""; message.textContent = "";
    try { await fn(); }
    catch (cause) { if (active()) error.textContent = cause?.message || t.error; }
    finally { if (active()) button.disabled = false; }
  }
  let selectedFactoryId = null;
  const dateFormat = new Intl.DateTimeFormat(context.locale?.startsWith("zh") ? "zh-CN" : "en-US", { dateStyle: "medium", timeStyle: "short" });
  async function refresh() {
    const current = ++sequence;
    cards.replaceChildren(el("p", t.loading));
    try {
      const factories = await context.callBackend("list_factories", {});
      if (!active() || current !== sequence) return;
      if (!factories.length) { selectedFactoryId = null; cards.replaceChildren(el("p", t.empty, "empty")); return; }
      if (!factories.some((factory) => factory.id === selectedFactoryId)) selectedFactoryId = factories[0].id;
      const factory = factories.find((item) => item.id === selectedFactoryId);
      const picker = el("label", t.selectRepo, "repository-picker");
      const select = el("select");
      for (const item of factories) {
        const option = el("option", `https://github.com/${item.owner}/${item.repo}`);
        option.value = item.id;
        select.append(option);
      }
      select.value = selectedFactoryId;
      select.addEventListener("change", () => { selectedFactoryId = select.value; void refresh(); }, { signal: context.signal });
      picker.append(select);
      const panel = el("div", undefined, "repository-panel");
      const status = el("span", factory.enabled ? t.enabled : t.disabled, factory.enabled ? "status on" : "status");
      const meta = el("p", `${t.cursor}: ${factory.poll_cursor || t.noCursor}`, "meta");
      const actions = el("div", undefined, "card-actions");
      const toggle = el("button", factory.enabled ? t.disable : t.enable); toggle.type = "button";
      toggle.addEventListener("click", () => void action(toggle, async () => {
        await context.callBackend("set_factory_enabled", { factory_id: factory.id, enabled: !factory.enabled }); await refresh();
      }), { signal: context.signal });
      const scan = el("button", t.scan); scan.type = "button"; scan.disabled = !factory.enabled;
      scan.addEventListener("click", () => void action(scan, async () => {
        const result = await context.callBackend("scan_factory", { factory_id: factory.id });
        if (active()) message.textContent = t.scanned.replace("{count}", result.created);
        await refresh();
      }), { signal: context.signal });
      actions.append(toggle, scan); panel.append(status, meta, actions);
      const heading = el("h3", t.jobs);
      const tableWrap = el("div", undefined, "ticket-table-wrap");
      const table = el("table", undefined, "ticket-table");
      const head = el("thead"); const headRow = el("tr");
      for (const label of [t.ticketId, t.issueId, t.issueTitle, t.phase, t.prId, t.updated, t.actions]) headRow.append(el("th", label));
      head.append(headRow); table.append(head);
      const body = el("tbody"); table.append(body); tableWrap.append(table);
      cards.replaceChildren(picker, panel, heading, tableWrap);
      const jobs = await context.callBackend("list_jobs", { factory_id: factory.id });
      if (!active() || current !== sequence) return;
      if (!jobs.length) { tableWrap.replaceChildren(el("p", t.noJobs, "empty")); return; }
      for (const job of jobs) {
        const row = el("tr");
        const ticketCell = el("td", `CF-${job.id.slice(0, 8)}`, "ticket-id"); ticketCell.title = job.id;
        const issueCell = el("td");
        const issueLink = el("a", `#${job.issue_number}`);
        issueLink.href = job.issue_url; issueLink.target = "_blank"; issueLink.rel = "noopener noreferrer"; issueCell.append(issueLink);
        const titleCell = el("td", job.issue_title || t.noTitle, "issue-title");
        if (job.detail) titleCell.append(el("small", job.detail, "job-detail"));
        const phaseCell = el("td"); phaseCell.append(el("span", context.locale?.startsWith("zh") ? (phaseZh[job.phase] || job.phase) : job.phase, "phase-pill"));
        const prCell = el("td", "—");
        if (Number.isInteger(job.pr_number) && typeof job.pr_url === "string" && job.pr_url.startsWith(`https://github.com/${factory.owner}/${factory.repo}/pull/`)) {
          const prLink = el("a", `#${job.pr_number}`); prLink.href = job.pr_url; prLink.target = "_blank"; prLink.rel = "noopener noreferrer";
          prCell.replaceChildren(prLink);
        }
        const updatedAt = job.last_updated_at ? new Date(job.last_updated_at) : null;
        const updatedCell = el("td", updatedAt && !Number.isNaN(updatedAt.getTime()) ? dateFormat.format(updatedAt) : "—", "updated-at");
        const actionCell = el("td");
        if (["draft", "blocked", "failed"].includes(job.phase)) {
          const start = el("button", t.start); start.type = "button";
          start.addEventListener("click", () => void action(start, async () => {
            await context.callBackend("start_job", { job_id: job.id });
            if (active()) message.textContent = t.started;
            await refresh();
          }), { signal: context.signal });
          actionCell.append(start);
        }
        row.append(ticketCell, issueCell, titleCell, phaseCell, prCell, updatedCell, actionCell);
        body.append(row);
      }
    } catch (cause) { if (active() && current === sequence) { cards.replaceChildren(); error.textContent = cause?.message || t.error; } }
  }
  refreshButton.addEventListener("click", () => void action(refreshButton, refresh), { signal: context.signal });
  let setupSequence = 0;
  const resetSetup = () => { setupSequence += 1; setupResult.replaceChildren(); };
  repoInput.addEventListener("input", resetSetup, { signal: context.signal });
  providerSelect.addEventListener("change", resetSetup, { signal: context.signal });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void action(join, async () => {
      resetSetup();
      let coordinates;
      try { coordinates = parseRepositoryUrl(providerSelect.value, repoInput.value); }
      catch { error.textContent = t.urlHint; return; }
      const { owner, repo } = coordinates;
      const current = setupSequence;
      const report = await context.callBackend("validate_repository", { owner, repo });
      if (!active() || current !== setupSequence) return;
      setupResult.replaceChildren();
      setupResult.append(el("p", report.ready ? t.validated : `${t.invalid}: ${report.problems.join(", ")}`));
      if (!report.ready) return;
      if (!report.missing_labels.length) {
        await context.callBackend("create_factory", { owner, repo, create_labels: false });
        if (!active() || current !== setupSequence) return;
        setupResult.replaceChildren(); message.textContent = t.created; await refresh();
        return;
      }
      setupResult.append(el("p", `${t.labels}: ${report.missing_labels.join(", ")}`, "meta"));
      const check = el("label", undefined, "confirm");
      const checkbox = el("input"); checkbox.type = "checkbox";
      check.append(checkbox, el("span", t.confirm)); setupResult.append(check);
      const create = el("button", t.join, "primary"); create.type = "button";
      create.addEventListener("click", () => void action(create, async () => {
        if (!checkbox.checked) { error.textContent = t.confirm; return; }
        await context.callBackend("create_factory", { owner, repo, create_labels: true });
        if (!active() || current !== setupSequence) return;
        setupResult.replaceChildren(); message.textContent = t.created; await refresh();
      }), { signal: context.signal });
      setupResult.append(create);
    });
  }, { signal: context.signal });
  void refresh();
  return { dispose() { disposed = true; sequence += 1; root.replaceChildren(); } };
}

export default { apiVersion: 1, module: "code-factory.v1", surfaces: [{ id: "factories", slot: "page", title: "Code factory", navigation: { label: "Code factory", labelZh: "代码工厂", icon: "code" }, mount }] };
