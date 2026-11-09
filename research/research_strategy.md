# Research strategy and tool report

## Tools actually available (checked 2026-11-09)
- Web search: yes (US-only, snippets). WebFetch: only allowlisted domains; github.com pages were refused.
- GitHub: `git clone` works; the GitHub **search** API works (30 req/min) and returns issue bodies; the issue-comments and issue-detail REST endpoints returned 403. So I could read issue bodies but **not maintainer comments**.
- gh CLI: token invalid. arXiv API via curl: blocked. No kubectl/kind in the workspace (go, python3, git present).
- NOT available: IEEE Xplore, ACM DL, Springer, ScienceDirect, Google Scholar. Literature coverage is therefore web-search-only. Novelty claims are capped accordingly.

## Not done yet (honest scope)
- Only 3 repos cloned (enhancements, autoscaler, kubernetes sparse). No issue sweep of containerd, etcd, cilium, istio, prometheus, scheduler-plugins.
- Phases 9-11 are designs, not executed. No experiments run; no results exist.
