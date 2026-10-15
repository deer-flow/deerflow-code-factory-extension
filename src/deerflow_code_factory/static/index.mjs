const copy = {
  zh: { title: "代码工厂", intro: "连接仓库，验证后轮询带 factory:ready 标签的 Issue。", owner: "组织或用户", repo: "仓库名", validate: "验证仓库", create: "建立代码工厂", labels: "缺少的标签", confirm: "创建缺少的标签", factories: "已连接的仓库", empty: "尚未连接仓库。先填写仓库信息并验证。", loading: "正在加载…", disabled: "未启用", enabled: "已启用", enable: "启用", disable: "停用", scan: "立即扫描", jobs: "需求工单", noJobs: "尚未发现符合条件的 Issue。", error: "操作失败，请检查 gh 登录状态和仓库权限。", validated: "仓库验证通过", invalid: "仓库尚不能启用", created: "代码工厂已建立", scanned: "扫描完成，新发现 {count} 个工单。", cursor: "上次扫描游标", noCursor: "尚未扫描" },
  en: { title: "Code factory", intro: "Connect a repository, then poll Issues labeled factory:ready after validation.", owner: "Owner", repo: "Repository", validate: "Validate repository", create: "Create factory", labels: "Missing labels", confirm: "Create missing labels", factories: "Connected repositories", empty: "No repositories connected. Enter a repository and validate it.", loading: "Loading…", disabled: "Disabled", enabled: "Enabled", enable: "Enable", disable: "Disable", scan: "Scan now", jobs: "Requirement tickets", noJobs: "No eligible Issues found yet.", error: "Action failed. Check gh authentication and repository permissions.", validated: "Repository validated", invalid: "Repository cannot be enabled yet", created: "Factory created", scanned: "Scan complete. {count} new tickets found.", cursor: "Last scan cursor", noCursor: "Not scanned" },
};

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

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
  const ownerLabel = el("label", t.owner);
  const ownerInput = el("input"); ownerInput.required = true; ownerInput.maxLength = 100; ownerInput.autocomplete = "off";
  const repoLabel = el("label", t.repo);
  const repoInput = el("input"); repoInput.required = true; repoInput.maxLength = 100; repoInput.autocomplete = "off";
  ownerLabel.append(ownerInput); repoLabel.append(repoInput);
  const validate = el("button", t.validate, "primary"); validate.type = "submit";
  const setupResult = el("div", undefined, "setup-result");
  const message = el("p", "", "message"); message.setAttribute("role", "status");
  const error = el("p", "", "error"); error.setAttribute("role", "alert");
  const section = el("section", undefined, "factory-list");
  section.append(el("h2", t.factories));
  const cards = el("div"); section.append(cards);
  form.append(ownerLabel, repoLabel, validate);
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
  async function refresh() {
    const current = ++sequence;
    cards.replaceChildren(el("p", t.loading));
    try {
      const factories = await context.callBackend("list_factories", {});
      if (!active() || current !== sequence) return;
      cards.replaceChildren();
      if (!factories.length) cards.append(el("p", t.empty, "empty"));
      for (const factory of factories) {
        const card = el("article", undefined, "factory-card");
        const top = el("div", undefined, "card-top");
        top.append(el("h3", `${factory.owner}/${factory.repo}`), el("span", factory.enabled ? t.enabled : t.disabled, factory.enabled ? "status on" : "status"));
        const meta = el("p", `${t.cursor}: ${factory.poll_cursor || t.noCursor}`, "meta");
        const actions = el("div", undefined, "card-actions");
        const toggle = el("button", factory.enabled ? t.disable : t.enable);
        toggle.type = "button";
        toggle.addEventListener("click", () => void action(toggle, async () => {
          await context.callBackend("set_factory_enabled", { factory_id: factory.id, enabled: !factory.enabled }); await refresh();
        }), { signal: context.signal });
        const scan = el("button", t.scan); scan.type = "button"; scan.disabled = !factory.enabled;
        scan.addEventListener("click", () => void action(scan, async () => {
          const result = await context.callBackend("scan_factory", { factory_id: factory.id });
          if (active()) message.textContent = t.scanned.replace("{count}", result.created);
          await refresh();
        }), { signal: context.signal });
        actions.append(toggle, scan);
        const jobsTitle = el("h4", t.jobs);
        const jobsList = el("ul", undefined, "jobs");
        card.append(top, meta, actions, jobsTitle, jobsList); cards.append(card);
        context.callBackend("list_jobs", { factory_id: factory.id }).then((jobs) => {
          if (!active() || current !== sequence) return;
          jobsList.replaceChildren();
          if (!jobs.length) jobsList.append(el("li", t.noJobs));
          for (const job of jobs) jobsList.append(el("li", `#${job.issue_number} · ${job.phase}`));
        }).catch(() => { if (active() && current === sequence) jobsList.replaceChildren(el("li", t.error)); });
      }
    } catch (cause) { if (active() && current === sequence) { cards.replaceChildren(); error.textContent = cause?.message || t.error; } }
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void action(validate, async () => {
      const owner = ownerInput.value.trim(); const repo = repoInput.value.trim();
      const report = await context.callBackend("validate_repository", { owner, repo });
      if (!active()) return;
      setupResult.replaceChildren();
      setupResult.append(el("p", report.ready ? t.validated : `${t.invalid}: ${report.problems.join(", ")}`));
      if (!report.ready) return;
      if (report.missing_labels.length) setupResult.append(el("p", `${t.labels}: ${report.missing_labels.join(", ")}`, "meta"));
      const check = el("label", undefined, "confirm");
      const checkbox = el("input"); checkbox.type = "checkbox"; checkbox.checked = !report.missing_labels.length;
      if (report.missing_labels.length) { check.append(checkbox, el("span", t.confirm)); setupResult.append(check); }
      const create = el("button", t.create, "primary"); create.type = "button";
      create.addEventListener("click", () => void action(create, async () => {
        if (report.missing_labels.length && !checkbox.checked) { error.textContent = t.confirm; return; }
        await context.callBackend("create_factory", { owner, repo, create_labels: checkbox.checked });
        if (!active()) return;
        setupResult.replaceChildren(); message.textContent = t.created; await refresh();
      }), { signal: context.signal });
      setupResult.append(create);
    });
  }, { signal: context.signal });
  void refresh();
  return { dispose() { disposed = true; sequence += 1; root.replaceChildren(); } };
}

export default { apiVersion: 1, module: "code-factory.v1", surfaces: [{ id: "factories", slot: "page", title: "Code factory", navigation: { label: "Code factory", labelZh: "代码工厂", icon: "code" }, mount }] };
