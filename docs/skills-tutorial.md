# Skills tutorial

The tutorial for the project skills lives with the skills themselves:

https://maxastrand04.github.io/Custom-skills/

It covers the kanban board, the git flow and the prompt for each skill. The source is the [Custom-skills repo](https://github.com/Maxastrand04/Custom-skills).

## Setup

`.claude/settings.json` enables the `max` plugin from the `custom-skills` marketplace. Claude Code offers to install it when you trust this repo. Commands carry the plugin name, for example `/max:new-ticket`.

## Keep the skills up to date

Third-party marketplaces do not auto-update by default. `.claude/settings.json` sets `"autoUpdate": true` for `custom-skills`, so Claude Code refreshes it in the background at startup. Check that it took effect once. In Claude Code, open `/plugin`, go to **Marketplaces**, select `custom-skills`, and look for **Disable auto-update**. If it offers **Enable auto-update** instead, select that.

To pull the latest right now, run `/plugin marketplace update custom-skills`. In a shell, run `claude plugin update max@custom-skills`.

A new copy only arrives when the plugin's version changes. Custom-skills pins `version` in `plugins/max/plugin.json` (currently 0.1.6), so the maintainer has to bump it on every release, or remove the field so each commit counts as a new version.
