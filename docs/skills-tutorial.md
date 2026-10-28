# Skills tutorial

This page covers using the project skills in pyrmit. The full walkthrough, with the principles, diagrams and a worked example, lives with the skills themselves:

[Tutorial](https://maxastrand04.github.io/Custom-skills/)

The source is the [Custom-skills repo](https://github.com/Maxastrand04/Custom-skills).

## Setup

`.claude/settings.json` adds the `custom-skills` marketplace from its `release` branch and enables the `max` plugin. Open Claude Code in the repo root and trust the folder. Claude Code then offers to install the plugin. Accept it.

If the offer never shows up, install it by hand:

```
/plugin marketplace add Maxastrand04/Custom-skills#release
/plugin install max@custom-skills
/reload-plugins
```

The ticket skills publish issues and PRs through the GitHub CLI, so run `gh auth status` once and log in if it complains.

Every command carries the plugin name, for example `/max:new-ticket`. Type `/max:` to list them.

## Where to start

| You want to                                       | Run                    |
| ------------------------------------------------- | ---------------------- |
| Test a raw idea before it becomes work            | `/max:brainstorming`   |
| Break a large feature into tickets                | `/max:map-epic`        |
| File one standalone ticket                        | `/max:new-ticket`      |
| Settle a term or decision in the docs             | `/max:grill-docs`      |
| Change a project convention in `docs/pcr/`        | `/max:challenge-pcr`   |
| Review a branch that did not go through the board | `/max:review-diff`     |

## Working a ticket

`new-ticket` and `map-epic` give every task ticket an `effort:` label. The label picks the route.

- `effort:trivial`. Open an ordinary session with the issue, make the change, and check by hand what no test covers.
- `effort:minor`. `/max:execute-ticket <issue number>` runs red, green and refactor in one session and opens the PR.
- `effort:medium` and `effort:major`. One skill per session, in this order:
  1. `/max:architect-ticket <issue number>` writes the stubs and failing acceptance tests. You approve the diff.
  2. `/max:implement-ticket` fills in the code until the acceptance tests pass.
  3. `/max:refactor-ticket` checks the code against the ticket and cleans it up.
  4. `/max:unit-test-ticket` moves the acceptance tests into the unit suite.
  5. `/max:pr-ticket` pushes the branch and opens the PR.

The hosted tutorial sends `medium` tickets through `/kanban-ci:launch`, which runs steps 2 to 4 in GitHub Actions. This repo does not enable the `kanban-ci` plugin, so run `medium` tickets the same way as `major`.

Run `/clear` between steps. The branch and the issue carry everything the next step needs. `/compact` keeps a summary of the old session that the next step will read, so don't use it between steps.

## What the skills rely on in this repo

- `CONTEXT.md` holds the domain terms. `grill-docs` writes new terms there.
- `docs/pcr/` holds conventions that bind the whole repo. Only `/max:challenge-pcr` edits them.
- `docs/adr/` holds decisions scoped to one part of the code. `grill-docs` writes new ones.
- `architect-ticket` puts acceptance tests in `backend/tests/test_acceptance.py` or `frontend/tests/acceptance.test.ts`. CI fails if one is still there at merge, so `unit-test-ticket` has to fold it into the unit suite first.
- Unit tests follow the layout in `AGENTS.md`. Backend tests make no real database or model calls (PCR-0011). Frontend tests fake the backend with MSW (PCR-0008).
- PRs merge only when all six CI checks pass (PCR-0010). `pr-ticket` does not get around that.

## Behaviour skills

The plugin also ships skills that change how Claude writes and explains: `unslop`, `gloss-me`, `grilling`, `talk-to-middleschooler` and `talk-to-highschooler`. Claude loads them on its own when they fit. You can call `/max:eli5` or `/max:eli10` to ask for a simpler explanation. `gloss-me` keeps your personal list of known terms in `~/.claude/glossary.md`, shared across every project.

## Keep the skills up to date

`.claude/settings.json` sets `"autoUpdate": true` for `custom-skills`, so Claude Code pulls the `release` branch in the background at startup. Check once that it worked. Open `/plugin`, go to **Marketplaces**, select `custom-skills`, and look for **Disable auto-update**. If it offers **Enable auto-update** instead, select that.

To pull the latest right now, run `/plugin marketplace update custom-skills`, then `/reload-plugins`. In a shell, run `claude plugin update max@custom-skills`.

A new copy only arrives when the plugin's `version` changes. Custom-skills pins it in `plugins/max/plugin.json` and `.claude-plugin/marketplace.json`, so every release has to bump both.

## Changing a skill

The skills are not in this repo. Change them in Custom-skills, merge to `release` with a version bump, then update as above.
