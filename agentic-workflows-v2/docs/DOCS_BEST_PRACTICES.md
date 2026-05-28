# Documentation Best Practices Baseline

This file captures the research baseline used to upgrade this repository's docs.

## Primary Reference: GitHub Docs

We aligned this repository with GitHub Docs guidance in these areas:

1. README quality and purpose
- Source: "About READMEs" and "Adding a README to your repository"
- Applied here: expanded `README.md` with setup, run paths, config, and docs index

2. Contributor guidance
- Source: "Setting guidelines for repository contributors"
- Applied here: expanded `CONTRIBUTING.md` with required checks and docs policy

3. Community standards files
- Source: "Best practices for repositories" and "About community profiles for public repositories"
- Applied here: added `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`, issue templates, and PR template

4. Issue/PR templates
- Source: "About issue and pull request templates"
- Applied here: `.github/ISSUE_TEMPLATE/*.yml`, `.github/PULL_REQUEST_TEMPLATE.md`

## High-Quality Documentation Design Benchmarks

Beyond GitHub Docs, we reviewed high-quality documentation ecosystems:

1. GitHub Docs repository (`github/docs`)
- Pattern used: docs-as-code + explicit contribution workflow and quality gates

2. Kubernetes documentation style guide
- Pattern used: task-oriented structure, audience clarity, and concise technical language

3. Django documentation writing guide
- Pattern used: distinct doc types (tutorial/how-to/reference/explanation) and consistency

## Documentation Structure Used In This Repo

To mirror those patterns, docs are organized as:
- Entrypoint: `README.md`
- Contribution and governance: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`
- Technical reference: `docs/API_REFERENCE.md`, `docs/ARCHITECTURE.md`, `docs/WORKFLOWS.md`
- Task-focused guides: `docs/tutorials/*.md`, `docs/DEVELOPMENT.md`
- Discoverability map: `docs/README.md`, `docs/REPO_MAP.md`

## Ongoing Checklist

Use this checklist for every PR that changes behavior:
- [ ] User-facing behavior changes are documented
- [ ] New env vars are documented in `README.md`
- [ ] New endpoints are documented in `docs/API_REFERENCE.md`
- [ ] New workflows are documented in `docs/WORKFLOWS.md`
- [ ] Docs links pass `python scripts/check_docs_refs.py`

## Sources

- https://docs.github.com/en/repositories/creating-and-managing-repositories/best-practices-for-repositories
- https://docs.github.com/en/get-started/exploring-projects-on-github/contributing-to-open-source
- https://docs.github.com/en/get-started/start-your-journey/setting-guidelines-for-repository-contributors
- https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/adding-a-readme-to-your-repository
- https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-readmes
- https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories
- https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/adding-a-code-of-conduct-to-your-project
- https://docs.github.com/en/code-security/getting-started/adding-a-security-policy-to-your-repository
- https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/about-issue-and-pull-request-templates
- https://github.com/github/docs
- https://kubernetes.io/docs/contribute/style/style-guide/
- https://docs.djangoproject.com/en/5.2/internals/contributing/writing-documentation/
