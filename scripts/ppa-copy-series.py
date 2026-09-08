#!/usr/bin/env python3
"""Copy an already-built PPA source between Ubuntu series, via Launchpad's API.

Replaces the manual "Copy packages" web-UI click in RELEASING.md step 6.

Why this exists as an API call rather than another `dput`: `dput` never authenticates to
Launchpad at all. It is an anonymous upload whose authorization is the GPG signature on the
`.changes` file - Launchpad recognizes the key, not a user. Copying between series modifies an
existing archive, which needs a real authenticated identity, and a GPG signature cannot supply
one. Hence OAuth, and hence the one-time authorization below.

Credentials are kept in a plain file rather than the GNOME keyring, deliberately: the file path
is checkable by a shell test, which is what `/orc-release`'s `**One-time setup:**` marker needs
in order to tell whether setup has already happened without running the setup itself.

The file is an OAuth token. It is chmod 0600 on save. Never cat it, never paste it into a
transcript - see Orclab's `secret-hygiene` skill.
"""

import argparse
import os
import pathlib
import sys

from launchpadlib.launchpad import Launchpad

DEFAULT_CREDENTIALS = pathlib.Path.home() / ".config" / "orcshot" / "launchpad-credentials.txt"
APPLICATION_NAME = "orcshot-release"


def credentials_path(override):
    return pathlib.Path(override) if override else DEFAULT_CREDENTIALS


def has_credentials(path):
    """True when a usable credential already exists - the one-time-setup check."""
    return path.is_file() and path.stat().st_size > 0


def log_in_anonymously():
    """Read-only session. Launchpad serves public PPA data with no credential at all.

    Every precondition check below is a read, so --dry-run needs no authorization: it can
    verify the copy would be valid on a machine that has never been set up.
    """
    return Launchpad.login_anonymously(APPLICATION_NAME, "production", version="devel")


def log_in(path):
    """Log in for writing, authorizing through a browser only if no credential is cached yet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    launchpad = Launchpad.login_with(
        APPLICATION_NAME, "production", version="devel", credentials_file=str(path)
    )
    if path.is_file():
        # launchpadlib does not restrict the mode itself; this is an OAuth token.
        os.chmod(path, 0o600)
    return launchpad


def find_published_source(ppa, source_name, version, series_name):
    """Return the published source in `series_name`, or None.

    This is the precondition that makes the copy safe. Copying a source Launchpad has not
    finished building yet is the mistake this guards against - the copy would carry no binaries,
    silently producing a source-only publication in the target series.
    """
    distro_series = ppa.distribution.getSeries(name_or_version=series_name)
    for source in ppa.getPublishedSources(
        source_name=source_name,
        version=version,
        distro_series=distro_series,
        status="Published",
        exact_match=True,
    ):
        return source
    return None


def built_binaries(source):
    """The binary names already built for a published source, as a sorted list."""
    return sorted({b.binary_package_name for b in source.getPublishedBinaries()})


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ppa-copy-series",
        description="Copy an already-built PPA source from one Ubuntu series to another.",
    )
    parser.add_argument("--owner", default="artificialorctelligence")
    parser.add_argument("--ppa", default="orcshot")
    parser.add_argument("--source", default="orcshot")
    # Not argparse-required: --check is a setup probe that needs no version, and the
    # `**One-time setup:**` block in RELEASING.md has to be a clean one-liner.
    parser.add_argument("--version", help="e.g. 0.3.0-1; required unless --check")
    parser.add_argument("--from-series", default="noble")
    parser.add_argument("--to-series", default="resolute")
    parser.add_argument("--credentials", default=None, help="override the credentials file path")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the one-time Launchpad authorization has been done, and stop",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    creds = credentials_path(args.credentials)

    if args.check:
        if has_credentials(creds):
            print(f"launchpad credentials present: {creds}")
            return 0
        print(f"error: no launchpad credentials at {creds}", file=sys.stderr, flush=True)
        print(
            "  run this script once without --check to authorize; it opens a browser exactly "
            "once per machine",
            file=sys.stderr,
            flush=True,
        )
        return 1

    if not args.version:
        parser.error("--version is required unless --check is given")

    if args.dry_run:
        # Reads only, so no credential and no browser - a dry run works on a fresh machine.
        launchpad = log_in_anonymously()
    else:
        if not has_credentials(creds):
            print(
                f"no cached credential at {creds} - a browser will open once to authorize",
                flush=True,
            )
        launchpad = log_in(creds)
    ppa = launchpad.people[args.owner].getPPAByName(name=args.ppa)

    source = find_published_source(ppa, args.source, args.version, args.from_series)
    if source is None:
        print(
            f"error: {args.source} {args.version} is not Published in {args.from_series} - "
            "nothing to copy. If the upload just happened, Launchpad's build farm has not "
            "finished yet; wait for the build to succeed before copying.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    binaries = built_binaries(source)
    if not binaries:
        print(
            f"error: {args.source} {args.version} is published in {args.from_series} but has no "
            "built binaries yet - copying now would publish a source with nothing installable. "
            "Wait for the build to finish.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    print(f"source:   {args.source} {args.version} ({args.from_series}, Published)", flush=True)
    print(f"binaries: {', '.join(binaries)}", flush=True)
    print(f"copy to:  {args.to_series} (Release pocket, binaries included)", flush=True)

    if args.dry_run:
        print("dry run - nothing copied", flush=True)
        return 0

    ppa.copyPackage(
        from_archive=ppa,
        source_name=args.source,
        version=args.version,
        from_series=args.from_series,
        to_series=args.to_series,
        to_pocket="Release",
        include_binaries=True,
    )
    print(
        f"copy requested: {args.source} {args.version} {args.from_series} -> {args.to_series}.\n"
        "Launchpad copies asynchronously - the source appears in the archive listing right away, "
        "but the files can take up to twenty minutes to show up. Confirm at\n"
        f"  https://launchpad.net/~{args.owner}/+archive/ubuntu/{args.ppa}/+packages",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
