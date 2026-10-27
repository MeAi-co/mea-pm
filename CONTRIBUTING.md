# Contributing

## Before you start

This plugin talks to a live Postgres store. A change that touches schema, migrations
or the destructive statement guard needs a working store to test against, and a
backup taken before you run it.

Read `README.md` for the architecture and `MIGRATION.md` for the upgrade path.

## Setting up

```bash
git clone git@github.com:MeAi-co/mea-pm.git
cd mea-pm
pip install -r requirements.txt
```

Point the environment at a test database, not the one your agent uses. The five
variables are listed in `SECURITY.md`.

## Checks that must pass

```bash
python3 -m py_compile $(git ls-files '*.py')
hermes plugins validate mea_pm
```

If you change a tool's arguments or return shape, say so in `CHANGELOG.md` and in the
relevant section of `README.md`.

## Database changes

Migrations are ordered files, applied by the engine on start. A new migration:

- is additive where possible, and never drops a column the shipped schema still reads
- carries a name that sorts after the existing ones
- is tested against a fresh install and against an existing store

Do not edit an applied migration. Add a new one.

## Bench changes

`bench/` is evidence, not marketing. A change there must not soften a result. If a
report contradicts a transcript, the transcript wins and the report is corrected in
the open, with the correction stated rather than the old line quietly deleted.

Reports keep the same shape: criteria, question by question findings, the difference
in that run, and the evidence index.

## Licensing of contributions

`jpm/` is AGPL-3.0-only and the rest of the repository is MIT. A pull request is
taken as agreement to contribute under the license of the directory it touches.
Do not paste in code you cannot license that way. See `LICENSING.md`.

## Commit messages

One imperative line, no body. `Fix profile home resolution`, not a paragraph
explaining why. One change per commit; if two things changed, that is two commits.

## Documentation

Plain sentences, concrete numbers, no em dashes or en dashes. If you cannot point at
the transcript or the line of code behind a claim, cut the claim.
