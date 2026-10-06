# Configuration overrides

Most explanations live beside their configuration. This page covers strict JSON
and command options shared by several invocations. Follow the
[development-environment specification](../../openspec/specs/development-environment/spec.md)
when changing them; recheck the selected tool version and the invocation's inherited settings.

## npm quality commands

`package.json` selects Prettier 3.9.9 and markdownlint-cli2 0.23.3.
Sources: [Prettier CLI options](https://prettier.io/docs/cli) and
[markdownlint-cli2 options](https://github.com/DavidAnson/markdownlint-cli2/tree/v0.23.3#command-line).

- `private: true`: The default is false. We override it because this npm project
  supplies development tools and must not be published as a package.
- `scripts.format`'s `prettier --write`: The default is writing formatted content
  to standard output. We override it because this command repairs tracked files.
- `scripts.format:check`'s `prettier --check`: The default is formatting content
  to standard output. We override it because validation must fail on unformatted files.
- Both scripts' `prettier --cache`: The default is false. We override it because
  unchanged files should reuse formatting results during repeated quality runs.
- `scripts.format`'s `prettier --log-level warn`: The default is log. We override
  it because successful per-file formatting messages obscure actionable diagnostics.
- `scripts.format`'s `markdownlint-cli2 --fix`: The default is false. We override
  it because the formatting command should apply supported Markdown repairs.

## Taplo catalog failure

The `taplo-lint` hook intentionally replaces its inherited arguments; its rationale
is in `.pre-commit-config.yaml`. On 2026-10-06, the pinned ComPWA v0.9.3 hook
failed to decode `SchemaCatalog` with its inherited `--default-schema-catalogs`
argument. The same failure occurred with local Taplo 0.10.0:

```sh
taplo lint --default-schema-catalogs pyproject.toml
```

[Taplo issue 463](https://github.com/tamasfe/taplo/issues/463) records this catalog
decoding failure. The configured hook still checks TOML syntax; it does not load
the remote schema catalog.
