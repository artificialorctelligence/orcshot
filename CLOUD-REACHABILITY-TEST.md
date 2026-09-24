# Cloud reachability test: can a consuming project obtain Orclab?

**Verdict.** Yes. A Claude Code cloud session scoped only to `artificialorctelligence/orcshot` can obtain
Orclab and get the CLI to load it, and it does **not** need the account's GitHub credentials to do so.
An anonymous `git clone` of `https://github.com/artificialorctelligence/orclab.git` with the credential
helper explicitly emptied (`-c credential.helper=`) and terminal prompting disabled
(`GIT_TERMINAL_PROMPT=0`) succeeded on the first attempt, exit code 0, 36 skills present,
`plugin.json` v0.25.1 readable. GitHub's own metadata for the repo reports `"private": false` /
`"visibility": "public"`, so the clone needed no identity at all — a stranger with no access to this
account could run the same command. After symlinking the clone into `~/.claude/skills/orclab`,
`claude plugin list` reports it as `orclab@skills-dir`, version 0.25.1, scope user, **status loaded**.
Two caveats, both recorded below: (a) the *running* session's skill list does not pick Orclab up —
skills are enumerated at session start, so `/orc-*` is not invokable in the same session that installs it;
(b) all outbound HTTPS here goes through the session's local agent proxy, and whether that proxy injects
the session's GitHub token on git traffic could not be verified from inside the container (the two
commands that would have shown it were blocked by the permission classifier). That caveat does not
change the verdict, because the repository is public and therefore clonable without credentials by
construction.

Test run: 2026-09-24, cloud session on `orcshot` (`/home/user/orcshot`, branch `main`),
git 2.43.0, `HOME=/root`, user `root`.

---

## 1. Is Orclab in this session's available-skills list?

**No.** Nothing put it there. The session's skill list at start contained only the built-in and
account-level skills (`session-start-hook`, `dataviz`, `artifact-*`, `update-config`, `code-review`,
`simplify`, `loop`, `claude-api`, `run`, `anthropic-skills:*`, `init`, `security-review`, …). No
`orclab`, no `orc-*`, no `/orc-code`, `/orc-version`, `/orc-git`, `/orc-test`.

Confirmed independently against the account's enabled skills:

```
ListSkills(keywords=["orclab","orc"]) -> {"results":[]}
```

The session is scoped to `orcshot` only. Orclab is a separate repository and was not attached, not
installed, and not enabled for the account.

## 2. Is `CLAUDE_CODE_REMOTE` set?

```
$ [ -n "$CLAUDE_CODE_REMOTE" ] && echo "set: $CLAUDE_CODE_REMOTE"
set: true
```

Set, to the literal string `true`.

## 3. The key test — anonymous clone

```
$ rm -rf /tmp/orclab-test
$ GIT_TERMINAL_PROMPT=0 git -c credential.helper= clone --depth 1 \
    https://github.com/artificialorctelligence/orclab.git /tmp/orclab-test
Cloning into '/tmp/orclab-test'...
EXIT CODE: 0
```

**It succeeded.** No error, no credential prompt, no authentication failure. Full output is the two
lines above — git printed nothing else.

Because it did not fail, the "retry without disabling the credential helper" branch was not required,
but it was run anyway for comparison:

```
$ git clone --depth 1 https://github.com/artificialorctelligence/orclab.git /tmp/orclab-test2
Cloning into '/tmp/orclab-test2'...
EXIT CODE: 0
```

**No difference.** Both forms succeed identically. Disabling the credential helper changes nothing,
which is the expected result for a public repository.

### Does this prove a stranger could do it, or only this account?

It proves a stranger could. Two independent lines of evidence:

1. The clone worked with `credential.helper=` emptied and `GIT_TERMINAL_PROMPT=0`, so git had no
   helper to ask and no terminal to prompt on.
2. GitHub's own repository metadata (via the session's GitHub MCP tools) reports the repo as public:

   ```
   full_name:    artificialorctelligence/orclab
   private:      false
   visibility:   public
   default_branch: main
   language:     Python
   pushed_at:    2026-09-24T00:13:47Z
   ```

   A public repository is clonable over anonymous HTTPS by definition.

### Honest limitation on point 1

This container routes outbound HTTPS through a local agent proxy (`HTTPS_PROXY=http://127.0.0.1:34681`,
CA bundle `/root/.ccr/ca-bundle.crt`), and the environment does set `GH_TOKEN` and git config
`url.https://github.com/.insteadOf` rewrites. So in principle the proxy, not git, could be supplying
credentials on the wire, and emptying `credential.helper` would not reveal that. Two attempts to check
this from inside were **denied by the Claude Code auto mode classifier**, and are reported verbatim
rather than worked around:

- `curl -sS "$HTTPS_PROXY/__agentproxy/status"` → denied, reason `[Exfil Scouting]`
- `cat /root/.ccr/README.md | head -120` → denied, reason `[Credential Exploration]`

Given the repository's `visibility: public`, this limitation does not affect the verdict: credentials
are not needed either way. It would only matter for a *private* repo, where the proxy-injection
question would be the whole question.

## 4. Contents of the clone

```
$ ls /tmp/orclab-test/skills | wc -l
36
```

```
$ cat /tmp/orclab-test/.claude-plugin/plugin.json
{
  "name": "orclab",
  "description": "Project-discipline skills distilled from real practice: backlog tracking, release checklists, live-environment registries, currency, verification, and secret-hygiene discipline, a deterministic /orc-code entry point for new-project, existing-project, and refactor work, /orc-version for versioning the current project, and /orc-git for common git/GitHub shortcuts. Every component ships as a skill, so /orc-* works identically in the CLI and Claude Desktop. /orc-publish pushes a project's built artifacts to its own configured distribution channels. /orc-release drives a project's own RELEASING.md end to end. /orc-reload reinstalls the plugin you're developing so a fresh session picks up your changes. /orc-test runs every test suite in a project across its languages, holds coverage to 80% and mutation score to 70%, and repairs weak suites; test-discipline is the background rule set every test is written under, and code-discipline the one for the code itself.",
  "version": "0.25.1",
  "author": {
    "name": "orclab",
    "email": "orc.shot@yahoo.com"
  }
}
```

Repository root and HEAD:

```
$ ls -a /tmp/orclab-test
.  ..  .claude-plugin  .git  .gitignore  BACKLOG.md  CHANGELOG.md  CLAUDE.md
README.md  VERIFICATION.md  docs  hooks  pyproject.toml  skills

$ git -C /tmp/orclab-test log --oneline -1
cff062e BACKLOG #76: owner is upgrading macOS; retry 2026-09-23, and the build-service answer rides on it
```

Skill bodies are intact and readable, not just directory stubs:

```
$ ls /tmp/orclab-test/skills | head -8
backlog-discipline
car-android-auto
car-carplay
code-discipline
currency-discipline
environment-registry
map-openstreetmap
orc

$ head -5 /tmp/orclab-test/skills/backlog-discipline/SKILL.md
---
name: backlog-discipline
description: Use when a real finding, gap, or deferred decision surfaces that won't be fixed right now but is worth tracking — or when resolving, updating, or considering deletion of an existing BACKLOG.md entry. Maintains a single flat BACKLOG.md with permanent, non-reused entry numbers and layered (not overwritten) resolution history.
---
```

## 5. Does the CLI recognise it as a loaded skills-dir plugin?

```
$ mkdir -p ~/.claude/skills && ln -sfn /tmp/orclab-test ~/.claude/skills/orclab
$ ls -la ~/.claude/skills/
total 16
drwxr-xr-x  4 root root 4096 Sep 24 03:31 .
drwxr-xr-x 10 root root 4096 Sep 24 03:29 ..
lrwxrwxrwx  1 root root   16 Sep 24 03:31 orclab -> /tmp/orclab-test
drwxr-xr-x  2 root root 4096 Sep 24 03:29 session-start-hook
drwxr-xr-x  3 root root 4096 Sep 24 03:29 synced

$ claude plugin list
Skills-directory plugins (.claude/skills/*):

  > orclab@skills-dir
    Version: 0.25.1
    Scope: user
    Path: ~/.claude/skills/orclab
    Status: √ loaded
```

**Yes — the CLI recognises it, as `orclab@skills-dir`, status `loaded`, version read correctly from
`plugin.json`.** A symlink is enough; the directory does not need to be copied.

As expected and as flagged in the instructions, the *already-running* session's own skill list still
does not contain Orclab (`ListSkills(["orclab","orc"])` → `{"results":[]}` after the symlink as well).
Skills are enumerated when the session starts, so the practical consequence for a consuming project is:
**install then restart** — a session cannot install Orclab and invoke `/orc-*` in the same session.

## 6. Is plain outbound HTTPS to github.com permitted?

```
$ curl -sS -o /dev/null -w '%{http_code}' https://github.com/artificialorctelligence/orclab
403
```

Headers show where the 403 comes from:

```
$ curl -sS -D - -o /dev/null https://github.com/artificialorctelligence/orclab
HTTP/1.1 200 Connection Established

HTTP/1.1 403 Forbidden
Content-Type: application/json; charset=utf-8
Content-Length: 378
Connection: close
```

The proxy `CONNECT` tunnel to `github.com:443` is established (`200 Connection Established`), and the
subsequent plain `GET` of the repository's HTML page is refused with a **403 whose body is JSON** — the
shape of a policy denial from the agent proxy's inspection layer, not of a GitHub page (GitHub serves
HTML, and a public repo page would be 200). So:

- **Plain web browsing of github.com: denied (403 at the proxy).**
- **Git over HTTPS to github.com: permitted** — clone worked twice, exit 0 both times.

Git traffic is allowed through the proxy while general HTTPS fetches of github.com pages are not. A
consuming project should therefore obtain Orclab with `git clone`, and should not expect `curl`,
`WebFetch`, or a tarball download from `github.com` to work under this network policy. Widening this is
a settings change, not a code change: Network access in the cloud environment's settings (environment
menu in the session title bar → Edit) can raise the access level or add `github.com` to the allowed
domains. Access levels are documented at https://code.claude.com/docs/en/claude-code-on-the-web.

---

## Summary table

| # | Measurement | Result |
|---|---|---|
| 1 | Orclab in session's available-skills list | No (not present at start; `ListSkills` → empty) |
| 2 | `CLAUDE_CODE_REMOTE` | `set: true` |
| 3 | Anonymous clone, credential helper emptied | **Succeeded, exit 0** |
| 3b | Clone with credential helper enabled | Succeeded, exit 0 — no difference |
| 3c | Repo visibility per GitHub API | `private: false`, `visibility: public` |
| 4 | Skills in clone / plugin version | 36 / `orclab` 0.25.1 |
| 5 | `claude plugin list` | `orclab@skills-dir`, scope user, **status loaded** |
| 5b | Running session picks up the skills | No — requires a fresh session |
| 6 | `curl https://github.com/...` | **403** (JSON body, proxy policy denial) |
| 6b | `git clone https://github.com/...` | Works (git allowed through proxy) |

## What this means for a consuming project

1. **Obtainable without credentials.** `git clone --depth 1 https://github.com/artificialorctelligence/orclab.git`
   works from a cloud session scoped to an unrelated repo, with no GitHub token, no credential helper,
   no account access. The repo is public.
2. **Loadable with a symlink or copy** into `~/.claude/skills/orclab` (or a project-level
   `.claude/skills/`); the CLI reads `plugin.json` and reports it loaded.
3. **Not usable in the installing session.** Skills are enumerated at session start, so `/orc-*`
   becomes available only in the next session. A repo that wants Orclab in *every* cloud session should
   do the clone + symlink in a `SessionStart` hook, so it is in place before skills are enumerated —
   though a hook that runs at start-of-session is itself subject to the same enumeration timing and
   should be verified before being relied on.
4. **Use git, not HTTP.** Plain HTTPS to github.com is 403 under this environment's network policy;
   git over HTTPS is permitted.

## Scope note

This test changed nothing in `orcshot` except adding this file. No pull request was opened, nothing was
built or released, and no orcshot code was touched. Artifacts outside the repo: `/tmp/orclab-test`
(the clone) and the symlink `~/.claude/skills/orclab`, both inside this ephemeral container.
