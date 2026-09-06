"""`tokenmaxxr` CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from tokenmaxxr import __version__
from tokenmaxxr import cookies as _cookies
from tokenmaxxr import fetch_all
from tokenmaxxr.cookies import discover_sources
from tokenmaxxr.providers import get_provider, known_slugs
from tokenmaxxr.schema import dumps


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return _cmd_doctor(args)
    if args.command == "serve":
        return _cmd_serve(args)

    overrides = _parse_cookie_overrides(getattr(args, "cookie_file", []) or [])
    try:
        doc = fetch_all(
            providers=getattr(args, "provider", None),
            cookie_overrides=overrides or None,
            refresh=getattr(args, "refresh", False),
        )
    except FileNotFoundError as e:
        sys.stderr.write(f"tokenmaxxr: {e}\n")
        return 2

    if args.json:
        sys.stdout.write(dumps(doc) + "\n")
        return 0

    _print_table(doc)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tokenmaxxr",
        description="Aggregate AI subscription quota usage.",
    )
    p.add_argument(
        "--version", action="version", version=f"tokenmaxxr {__version__}"
    )
    p.add_argument(
        "--json", action="store_true", help="emit one JSON document on stdout"
    )
    p.add_argument(
        "--provider",
        action="append",
        default=None,
        help="limit to provider slug (repeatable)",
    )
    p.add_argument(
        "--refresh",
        action="store_true",
        help="ignore the cache and re-fetch live",
    )
    p.add_argument(
        "--cookie-file",
        action="append",
        default=[],
        metavar="SLUG=PATH",
        help="override cookie store path (repeatable)",
    )
    sub = p.add_subparsers(dest="command", required=False)

    sub.add_parser("doctor", help="show which cookie stores could be used per provider")

    serve = sub.add_parser("serve", help="run the local web dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    return p


def _parse_cookie_overrides(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"--cookie-file expects SLUG=PATH, got: {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _print_table(doc: dict) -> None:
    rows: list[tuple[str, str, str, str, str]] = []
    for prov in doc.get("providers", []):
        name = prov.get("name") or prov.get("id") or "?"
        status = prov.get("status", "?")
        windows = prov.get("windows") or []
        if windows:
            label = ", ".join(
                f"{w.get('label','?')}:{w.get('pct_used',0)}%" for w in windows
            )
        else:
            label = "(no windows)"
        reset = ""
        if windows:
            # Pick the first window that actually has a reset time. The
            # "primary" window may legitimately be None (e.g. 5h on
            # ClinePass has no resetsAt), so fall through to the next
            # window instead of always taking the first.
            for w in windows:
                ts = w.get("reset_at")
                if ts:
                    reset = ts
                    break
        rows.append((name, status, label, reset, prov.get("error") or ""))
    widths = [max(len(str(r[i])) for r in rows + [("",)*5]) for i in range(5)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format("PROVIDER", "STATUS", "USAGE", "RESET", "ERROR"))
    for r in rows:
        print(fmt.format(*r))


def _cmd_doctor(args: argparse.Namespace) -> int:
    # Use the module reference so monkeypatching `cookies.discover_sources` is
    # picked up here (it would be missed if we imported the name directly).
    lines: list[str] = []
    for slug in known_slugs():
        prov = get_provider(slug)
        if not prov.cookie_domain:
            lines.append(f"# {prov.name} ({slug}) — token file")
            lines.append(f"  {prov.auth_hint()}")
            lines.append("")
            continue
        sources = _cookies.discover_sources(prov.cookie_domain)
        lines.append(f"# {prov.name} ({slug}) — domain: {prov.cookie_domain}")
        if not sources:
            lines.append("  no cookie stores discovered")
            lines.append(
                f"  remediation: log in to {prov.cookie_domain} in your browser, "
                "or pass --cookie-file SLUG=/path/to/cookies.sqlite"
            )
        else:
            for s in sources:
                lines.append(f"  - {s.kind}: {s.detail}")
        lines.append("")
    sys.stdout.write("\n".join(lines))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        from tokenmaxxr.serve import run
    except ImportError as e:
        sys.stderr.write(
            "serve requires the [serve] extra: pip install 'tokenmaxxr[serve]'\n"
            f"  ({e})"
        )
        return 2
    run(host=getattr(args, "host", "127.0.0.1"), port=getattr(args, "port", 8765))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
