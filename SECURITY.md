# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | yes |
| 0.1.x | no |

## Reporting a vulnerability

Use GitHub's private vulnerability reporting on this repository: the Security tab,
then "Report a vulnerability". Do not open a public issue for anything that exposes
credentials, allows arbitrary SQL to run outside the intended tool surface, or lets
one profile read another profile's memory.

Please include the plugin version, the Hermes version, the Postgres version, the
relevant log lines with credentials removed, and the smallest reproduction you can
build. Reports are handled on a best effort basis; there is no paid support tier and
no guaranteed response time.

## What is in scope

- The plugin package in this repository, including the engine under `jpm/`.
- The tool surface: `vault`, `messages`, `sessions`, `skills`, plus the side loops
  that are enabled by default.
- Credential handling, profile isolation, and the destructive statement guard.

## What is not in scope

- Bugs in Hermes core. Report those upstream.
- A deployment that has given the agent database rights beyond the documented setup.
- Postgres configuration, including network exposure and backup policy, which belong
  to the operator.

## Handling credentials

The plugin reads `JPM_PG_HOST`, `JPM_PG_PORT`, `JPM_PG_USER`, `JPM_PG_PASSWORD` and
`JPM_PG_DB` from the profile environment. It never writes them to the database, to
logs, or to tool output. If you find a path that prints them, that is a security bug
and should be reported privately.
