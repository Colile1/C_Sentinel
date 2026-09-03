# libs/

Code shared by every service. Nothing here may import a service; the dependency direction is
services depend on `libs`, never the reverse, and `libs` never imports `soc`, `kg` or `rag`.

`libs/common/` is currently the only package. If a second appears, it needs its own folder and its
own README.

At container build time each service copies `libs/` in and installs it, so the shared code is
versioned once and deployed with every service — the services stay independently deployable because
each carries its own copy of the library at its own build.

## Subfolders

| Folder | Purpose |
|--------|---------|
| `common/` | Config, errors, security events, structured logging, registry client, resilient HTTP client |
