# Flathub Readiness Design

## Goal

Make Orcshot's Flatpak manifest genuinely ready for real Flathub submission (BACKLOG #194).
This is not a deferred nice-to-have: Flathub distribution was always the actual point of having
a Flatpak channel at all - a `.flatpak` file attached to a GitHub Release isn't how real Flatpak
users find or install software.

This plan produces a CI-verified, Flathub-buildable manifest, a real AppStream metainfo file,
real screenshots, and real OARS content ratings - everything needed to actually open a
submission. It does **not** include opening that submission (the PR against `flathub/flathub`,
their human review process) - that's a separate, later action, deliberately kept out of this
plan's scope.

Also explicitly out of scope: re-testing the narrower `--talk-name=org.gnome.Shell.Extensions`
permission against a future GNOME Shell version. Already tested and confirmed broken against the
current real target (GNOME 46.2, confirmed live during the Flatpak channel's own final review) -
revisit only if a future GNOME version changes that, tracked separately.

## Real groundwork (2026-09-01/02)

Everything below was verified live this session, not assumed:

- **Only Flatpak needs a pip-vendoring fix.** apt and Snap already use real Ubuntu archive
  packages (`python3-numpy`, `python3-shapely`, `python3-xlib` - `debian/control`,
  `snapcraft.yaml` stage-packages), no pip anywhere. Only
  `org.orcshot.Orcshot.yaml`'s `pip3 install --prefix=/app numpy==2.5.2 shapely==2.1.2
  python-xlib==0.33` line does live network access at build time, which Flathub's build policy
  disallows.
- **The real fix**: Flathub's own official `flatpak-pip-generator` tool
  (`flatpak/flatpak-builder-tools`, the Flathub org's own GitHub repo, MIT licensed - not the
  same-named PyPI package, which is an unofficial third-party repackaging). Run for real against
  the exact pinned versions already in the manifest, with `--prefer-wheels` (avoids a much
  heavier from-source build the tool defaults to) and `--runtime org.gnome.Sdk//50` (a required
  flag when using `--prefer-wheels` - the tool refuses to guess wheel compatibility without it).
  This run itself caught that `org.gnome.Sdk`//50's real Python is **3.13** (`cp313` wheel
  tags), not 3.12 as naively assumed from testing on an unrelated host Python - confirming why
  `--runtime` is required, not optional. It also caught a real, previously-unpinned transitive
  dependency: `python-xlib==0.33` depends on `six>=1.10.0`, not declared anywhere in the current
  manifest.
- **Flathub's real, official metainfo requirements** (fetched live from
  `docs.flathub.org/docs/for-app-authors/metainfo-guidelines` - no trailing slash, that 404s).
  Mandatory tags, validated by `flatpak-builder-lint` (`appstreamcli validate` underneath - both
  errors and warnings are build-blocking): `id` (exact app-id match), `metadata_license`,
  `project_license` (real SPDX), `name`, `summary`, `developer` (reverse-DNS `id` + `name`
  child), `description` (real prose), `launchable` (matching the real `.desktop` file),
  `content_rating type="oars-1.1"`, `url type="homepage"` at minimum, `screenshots` (at least
  one, permanently-hosted image), `releases` (real version/date entries, no future dates).
- **The `<developer>` tag's `name` doesn't need to be a real person** - confirmed directly from
  the AppStream specification itself (`freedesktop.org/software/appstream/docs/chap-Metadata.html#tag-developer`):
  "designed to represent the developers **or project**... Values might be for example 'The GNOME
  Foundation' or 'The KDE Community'." A project name is exactly what this field is for.
- **`orcshot.org` was registered by direflail during this brainstorm** (2026-09-01), not yet
  resolving at time of writing. Chosen as the metainfo's `homepage` URL despite not being live
  yet - by the time this is actually reviewed/used, DNS should have propagated. Flathub's own
  domain-ownership "Verified" badge needs a token that's only generated *after* a real
  submission is accepted (shown in Flathub's own Developer Portal) - so that verification step
  is necessarily a later, separate action, not something this plan can set up.
- **Real, live-run OARS questionnaire** (`hughsie.github.io/oars/generate.html`, the standard
  generator tool) - confirmed Orcshot is "an application that can connect to the Internet" (it
  has a real, automatic periodic background update checker,
  `src/orcshot/app.py`'s `_start_periodic_update_checks`/`_periodic_update_check_tick`, polling
  GitHub Releases via `urllib.request` - `src/orcshot/ui/update_check.py`), then every content
  category (violence, drugs, sex, language, money, social) genuinely defaults to and stays
  "none" - a screenshot/annotation tool has none of this content. Real generated output:
  ```xml
  <content_rating type="oars-1.1" />
  ```
- **Flathub's real screenshot quality guidelines** (`docs.flathub.org/docs/for-app-authors/metainfo-guidelines/quality-guidelines`)
  require native window decoration (title bar, shadow, rounded corners - not maximized, which
  removes these) reflecting "the environment's default window decoration layout." Nothing in
  Flathub's actual policy rejects X11-captured screenshots specifically (no such check is even
  possible from a PNG alone) - but Cinnamon's window chrome (this project's own X11 dev host)
  looks genuinely different from GNOME Shell's, and Orcshot's Wayland support has been built and
  tested against GNOME Shell specifically throughout this project. Taking the screenshot on the
  real Ubuntu 26.04 GNOME VM gives a more representative, honest picture of what most Flathub
  users would actually see.

## Scope

Build:
1. A vendored-dependencies module for `org.orcshot.Orcshot.yaml`, replacing the current live
   `pip3 install` line entirely.
2. A real `org.orcshot.Orcshot.metainfo.xml`, installed into the Flatpak build.
3. A real screenshot, taken on the real GNOME VM, committed to the repo.
4. A CI validation step running Flathub's own linter against the real metainfo.

**Explicitly out of scope**: the actual Flathub submission (opening the PR against
`flathub/flathub`); re-testing the narrower `--talk-name` permission (see above).

## Design

### 1. Vendored Python dependencies

Add a new module to `org.orcshot.Orcshot.yaml`'s `modules:` list - the real,
already-verified `flatpak-pip-generator` output (`--prefer-wheels`, `--runtime
org.gnome.Sdk//50`), inlined directly into the manifest (matching how every other module already
lives inline there - `bundled-extensions`, `gnome-shell-schema` - rather than a separate
included file):

```yaml
  - name: python3-numpy
    buildsystem: simple
    build-commands:
      - pip3 install --verbose --exists-action=i --no-index --find-links="file://${PWD}"
        --prefix=${FLATPAK_DEST} "numpy==2.5.2" --no-build-isolation
    sources:
      - &numpy-x86_64
        type: file
        url: https://files.pythonhosted.org/packages/7b/44/59a1eb68e773c4098d107ef34a0dbdeca501d72ffcfbff9a7707343921ce/numpy-2.5.2-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
        sha256: 29b86ff8a6cc556b47ec6b64b194815cc80e6bf5eedcc6cddfd65318cb0b4eee
        only-arches: [x86_64]
      - &numpy-aarch64
        type: file
        url: https://files.pythonhosted.org/packages/29/f1/2a64a307d92c5d98f5255a4014eb43bb6103ee477087b61ecae44a3aa9b9/numpy-2.5.2-cp313-cp313-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl
        sha256: 0aadf13b60048d501e05fa699efaf7734e2494f3498a4c2a5521d822640324f3
        only-arches: [aarch64]
  - name: python3-shapely
    buildsystem: simple
    build-commands:
      - pip3 install --verbose --exists-action=i --no-index --find-links="file://${PWD}"
        --prefix=${FLATPAK_DEST} "shapely==2.1.2" --no-build-isolation
    sources:
      - *numpy-x86_64
      - *numpy-aarch64
      - type: file
        url: https://files.pythonhosted.org/packages/f2/a2/83fc37e2a58090e3d2ff79175a95493c664bcd0b653dd75cb9134645a4e5/shapely-2.1.2-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
        sha256: 7ed1a5bbfb386ee8332713bf7508bc24e32d24b74fc9a7b9f8529a55db9f4ee6
        only-arches: [x86_64]
      - type: file
        url: https://files.pythonhosted.org/packages/2d/5e/7d7f54ba960c13302584c73704d8c4d15404a51024631adb60b126a4ae88/shapely-2.1.2-cp313-cp313-manylinux2014_aarch64.manylinux_2_17_aarch64.whl
        sha256: fe7b77dc63d707c09726b7908f575fc04ff1d1ad0f3fb92aec212396bc6cfe5e
        only-arches: [aarch64]
  - name: python3-python-xlib
    buildsystem: simple
    build-commands:
      - pip3 install --verbose --exists-action=i --no-index --find-links="file://${PWD}"
        --prefix=${FLATPAK_DEST} "python-xlib==0.33" --no-build-isolation
    sources:
      - type: file
        url: https://files.pythonhosted.org/packages/fc/b8/ff33610932e0ee81ae7f1269c890f697d56ff74b9f5b2ee5d9b7fa2c5355/python_xlib-0.33-py2.py3-none-any.whl
        sha256: c3534038d42e0df2f1392a1b30a15a4ff5fdc2b86cfa94f072bf11b10a164398
      - type: file
        url: https://files.pythonhosted.org/packages/b7/ce/149a00dd41f10bc29e5921b496af8b574d8413afcd5e30dfa0ed46c2cc5e/six-1.17.0-py2.py3-none-any.whl
        sha256: 4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274
```

The existing `orcshot` module's own `pip3 install --prefix=/app numpy==2.5.2 shapely==2.1.2
python-xlib==0.33` line and the `build-options: build-args: [--share=network]` block are both
removed - no network access needed anywhere in the build once this lands.

### 2. `org.orcshot.Orcshot.metainfo.xml`

New file at the repo root, installed via a new `install -Dm644
org.orcshot.Orcshot.metainfo.xml /app/share/metainfo/org.orcshot.Orcshot.metainfo.xml` line in
the manifest's `orcshot` module build-commands (matching how the `.desktop` file is already
installed the same way).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.orcshot.Orcshot</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>Orcshot</name>
  <summary>Capture, annotate, and share screenshots</summary>
  <developer id="org.orcshot">
    <name>Orcshot</name>
  </developer>
  <description>
    <p>
      Orcshot is a screenshot capture and annotation tool for Linux, ported from Windows
      Greenshot. Capture a region, a window, or the full screen, then annotate with shapes,
      text, arrows, and effects before saving, copying, or sending the result wherever it
      needs to go.
    </p>
    <ul>
      <li>Region, window, and full-screen capture on both X11 and Wayland</li>
      <li>A full annotation editor: shapes, text, arrows, highlighting, blur and pixelize
      effects</li>
      <li>Configurable global capture hotkeys</li>
      <li>Send captures straight to the clipboard, a file, or an external command</li>
    </ul>
  </description>
  <launchable type="desktop-id">org.orcshot.Orcshot.desktop</launchable>
  <url type="homepage">https://orcshot.org</url>
  <url type="bugtracker">https://github.com/artificialorctelligence/orcshot/issues</url>
  <url type="vcs-browser">https://github.com/artificialorctelligence/orcshot</url>
  <branding>
    <color type="primary" scheme_preference="light">#8aff01</color>
    <color type="primary" scheme_preference="dark">#3d3d3d</color>
  </branding>
  <content_rating type="oars-1.1" />
  <screenshots>
    <screenshot type="default">
      <image>PINNED_COMMIT_URL/metainfo-screenshots/editor-annotated.png</image>
      <caption>Annotate a capture with shapes, text, and effects</caption>
    </screenshot>
  </screenshots>
  <releases>
    <release version="CURRENT_PYPROJECT_VERSION" date="TODAY">
      <description>
        <p>Initial Flathub-ready release.</p>
      </description>
    </release>
  </releases>
</component>
```

`CURRENT_PYPROJECT_VERSION`/`TODAY`/`PINNED_COMMIT_URL` are resolved at implementation time from
the real current `pyproject.toml` version, the real date, and the real commit the screenshot
lands in - not placeholders left in the shipped file.

The `description` prose above is a first draft for implementation-time review, not
locked - matches the project's own real feature set (checked against `debian/control`'s existing
description) but should get a final read before landing.

### 3. Screenshot

Taken on the real Ubuntu 26.04 GNOME VM (native window decoration - see groundwork above):
launch Orcshot, capture a region, annotate it with at least one shape/text/arrow tool in the
editor, screenshot the real editor window (windowed, not maximized, so the shadow/rounded
corners remain per Flathub's own quality guidelines), save as
`metainfo-screenshots/editor-annotated.png`, commit it, then update the metainfo's `<image>` URL
to the real `raw.githubusercontent.com` URL pinned to that exact commit SHA.

### 4. CI validation

New step in `.github/workflows/flatpak.yml`'s `build-flatpak` job, after the existing build
step: install `org.flatpak.Builder` from Flathub, run `flatpak run --command=flatpak-builder-lint
org.flatpak.Builder appstream org.orcshot.Orcshot.metainfo.xml`, fail the job on any lint error
or warning (matching Flathub's own real review bar - both are treated as failures there, so CI
should too).

## Known open items

- **The homepage points at `orcshot.org`, which isn't resolving yet at spec-writing time.**
  Real risk if this plan lands before the domain is live and hosting something: a broken/parked
  homepage link in a real, shipped metainfo file. Should be confirmed live (does it resolve, is
  something real hosted there) before this actually merges, not just before Flathub submission.
- **Flathub's domain-verification badge** needs a token only available after real submission -
  tracked as a genuinely separate, later action, not part of this plan.
- **The description prose is a first draft**, not final-reviewed copy - worth a fresh look at
  implementation time.
