# Code factory interface

Operator page for connecting GitHub repositories and observing Issue intake. The page uses an indigo ink and cool slate palette, a compact mono treatment for repository and Issue identifiers, and a horizontal platform, repository URL, and Add form. Chinese is the primary locale; English is supported. A single page owns the form and factory list. GitHub is selectable; GitLab remains visible but disabled until its adapter exists. Adding validates and connects a repository when all labels exist. Missing-label creation requires a separate confirmation. Activation and scanning have separate controls and feedback.

The UI must never imply that Issue intake has completed coding or released a package. Statuses name only observed facts. All mutable operations are owner scoped on the server. Text from GitHub is rendered with `textContent`.

The repository and job list refreshes on initial load, after a user action, or when the operator selects Refresh status. The page does not poll its own UI; the Gateway Issue poll remains independent.
