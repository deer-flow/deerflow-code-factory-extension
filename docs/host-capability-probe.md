# Host capability probe — 2026-10-15

Inspected `deerflow_extension_api.AgentRuns`, `ExtensionRuntimeDeps`, and the Gateway artifacts router in the current DeerFlow checkout.

- `AgentRuns` can create, start, wait for, inspect and cancel full Agent runs. The action-bound handle can be retained by a service during the current Gateway process, but is not serializable across restart.
- `ExtensionRuntimeDeps` exposes run evidence and optional model invocation, not a thread workspace or output-file reader.
- The host artifacts HTTP router serves thread output files to authenticated requests. It is not a service-held extension capability, and it does not export the whole `/mnt/user-data/workspace` tree.
- The existing GitHub App token path is internal to Gateway GitHub-triggered runs. A factory extension cannot safely inject that token through public `AgentRuns.start` context.

Therefore the MVP can implement factory setup and Issue intake using current public contracts, but a complete code/PR loop needs one narrow host capability: a principal-bound reader for a bounded archive written by an Agent under `/mnt/user-data/outputs`, or a similarly scoped workspace snapshot reader. The factory would unpack/validate that archive outside the Agent, then commit and push through its trusted GitHub adapter. This avoids handing App credentials to the Agent. The host change requires targeted authorization, path-confinement, size-limit and remote-sandbox tests before it is implemented.

Current branch implements the extension's durable store and GitHub Issue discovery only. No Agent execution or GitHub mutation is wired yet.
