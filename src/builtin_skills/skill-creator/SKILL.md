---
name: Skill Creator
description: Build a safe, reusable Agent Skill package and publish it with skills_create.
---

# Skill Creator

Create a reusable package only when the workflow is likely to be useful again.

1. Read the request and identify the reusable procedure.
2. Fetch external material with existing tools when required. Do not ask `skills_create` to fetch anything.
3. Search with `skills_search` to avoid duplicate skills.
4. Write one focused `SKILL.md` with valid `name` and `description` frontmatter.
5. Add only useful UTF-8 reference or script files. Scripts are stored, never executed by `skills_create`.
6. Call `skills_create` with the final package.
7. Verify publication with `skills_read`.
8. Correct the package only when validation or verification reports a concrete problem.

Do not include secrets, credentials, personal data, generated binaries, downloads, or generic filesystem mutations.
