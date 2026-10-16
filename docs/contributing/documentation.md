# Build the documentation

The documentation source is Markdown under `docs/`. MkDocs reads
`mkdocs.yml`, validates the configured navigation, and writes the generated
site to `site/`.

## Create the local environment

From the repository root:

```bash
uv sync --locked --only-group docs
```

The documentation group is declared in `pyproject.toml` and resolved in the
repository-wide `uv.lock`. The command creates or updates `.venv` without
installing unrelated runtime or development dependencies.

## Preview changes

Run the development server:

```bash
uv run --locked --no-sync mkdocs serve
```

Open the local address printed by MkDocs. The server watches the Markdown and
configuration files and rebuilds the preview after changes.

## Run the required check

Before committing documentation changes, run:

```bash
uv run --locked --no-sync mkdocs build --strict
```

Strict mode treats warnings as errors. The generated `site/` directory is a
disposable build artifact and must not be committed.

## Navigation and links

- Add published pages to `nav` in `mkdocs.yml`.
- Use relative links between Markdown files.
- Link to a heading only when the target heading is stable enough to serve as
  a public anchor.
- Prefer copyable, bounded examples that do not rely on private cluster names,
  credentials, or hidden files.
- Mark remote commands that submit jobs, install software, or modify state
  clearly.

## CI and deployment

The regular validation workflow performs a strict documentation build for pull
requests and pushes. A separate deployment workflow builds and publishes the
site to GitHub Pages after a push to `main`.

The deployment must be enabled in the repository's GitHub Pages settings with
**GitHub Actions** selected as the source. Pull requests never receive Pages
write permissions from the documentation workflows.
