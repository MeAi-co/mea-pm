# Licensing

Two licenses, one repository, drawn along a single boundary.

| Path | License | What it means |
|---|---|---|
| `jpm/` | AGPL-3.0-only | Free software. Read it, run it, patch it, fork it, distribute your changes. |
| everything else | MIT | Do what you like, including in closed products. |

The plugin shell is MIT so it can be dropped into a commercial agent stack
without a second thought. The engine is AGPL so that the memory layer itself
stays inspectable and repairable by the people who run it, and so that anyone
offering it to others as a hosted service has to publish their changes.

## Why the engine is not proprietary

A memory store holds the record an agent reasons from. If the code that reads
and writes it cannot be audited or patched by its operator, the operator is
asked to trust a black box with their own history. That is not a reasonable
thing to ask of the intermediate and advanced users this project targets, and
it is the reason this engine is shipped as free software rather than under a
proprietary license.

## What AGPL means in practice

- Self-hosting, personal use, internal company use: no obligations beyond
  keeping the copyright notices. You can modify it and keep the changes private
  as long as you are not offering it to others as a service.
- Forking, patching, redistributing: allowed, provided the source stays under
  AGPL and your changes are available under the same terms.
- Offering it to other people over a network: allowed, and you must offer those
  users the corresponding source, including your modifications. This is section
  13 of the license and it is the clause that distinguishes AGPL from GPL.
- Embedding the engine in a closed product: not permitted. The plugin shell
  around it is MIT and can be used that way, which is why the boundary is where
  it is.

## Commercial terms

If AGPL does not fit your use, a commercial license for `jpm/` is available.
Contact MeAi-co. Nothing in this file grants rights beyond the two licenses
named above.

## Contributing

Contributions are accepted under the license of the directory they land in:
MIT for the plugin surface, AGPL-3.0-only for `jpm/`. By opening a pull request
you confirm you have the right to submit the work under those terms.

## Trademarks

The names MeAI Vault and MeAI are not covered by either license. Forking the
code is fine; shipping a fork under those names is not.
