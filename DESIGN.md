# Code factory interface

Operator page for connecting GitHub repositories and observing Issue intake. The page uses an indigo ink and cool slate palette, a compact mono treatment for repository and Issue identifiers, and a horizontal validation rail that makes the setup sequence visible. Chinese is the primary locale; English is supported. A single page owns the form and factory list. Validation, label creation, activation, and scanning have separate controls and feedback.

The UI must never imply that Issue intake has completed coding or released a package. Statuses name only observed facts. All mutable operations are owner scoped on the server. Text from GitHub is rendered with `textContent`.
