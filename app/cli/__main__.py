"""surasura-cli's entry (02-contract §1): `python -m app.cli <verb> …` from source, surasura-cli.exe frozen.

Every verb answers with JSON lines on stdout and an exit code (app/cli/contract.py). Verbs come from VERBS below.
"""
import argparse
import os
import sys

from app.cli import contract


class _Parser(argparse.ArgumentParser):
    """A wrong command is an `error` line and exit 2, never argparse's text on stderr (02 §4)."""

    def error(self, message):
        if "invalid choice" in message:
            message = "That isn't a surasura-cli command. Run surasura-cli --help for the list."
        raise contract.CliError("usage", message)


# --------------------------------------------------------------------------- #
# Verbs
# --------------------------------------------------------------------------- #
def _version(args):
    from app import __version__, analyzer, token_index
    return {"app": __version__, "engine": analyzer.ENGINE_REVISION, "schema": token_index.SCHEMA_VERSION,
            "store": None}      # the library store's schema, from 2.5


def _selftest_args(parser):
    parser.add_argument("outcome", choices=("ok", "fail", "raise"))
    parser.add_argument("--echo", default=None, help="text to hand back in the result")


def _selftest(args):
    """Hidden: proves the contract end to end — exit 0 and 1, the events file, no dialog (P1.1's smoke run)."""
    if args.outcome == "raise":
        raise RuntimeError("self-test: an exception, as asked")
    if args.outcome == "fail":
        raise contract.CliError("failed", "Self-test: a failure, as asked.")
    contract.emit_progress("self-test", 1, 1)
    return {"verb": "_selftest", "echo": args.echo}


# name: (add its arguments, run it, shown in --help)
VERBS = {
    "_selftest": (_selftest_args, _selftest, False),
}


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--progress", action="store_true", default=argparse.SUPPRESS,
                        help="also print progress lines before the result")
    common.add_argument("--root", default=argparse.SUPPRESS, help=argparse.SUPPRESS)    # tests only (02 §6)
    parser = _Parser(prog="surasura-cli", parents=[common],
                     description="Surasura's command line: one JSON line on stdout, and an exit code "
                                 "(0 done, 1 failed, 2 wrong command, 3 busy, 4 needs you).")
    parser.add_argument("--version", action="store_true", help="the versions of the app, its engine and its stores")
    shown = [name for name, (_add, _run, public) in VERBS.items() if public]
    verbs = parser.add_subparsers(dest="verb", metavar="<verb>", parser_class=_Parser,
                                  help=", ".join(shown) or argparse.SUPPRESS)
    for name, (add, _run, _public) in VERBS.items():
        add(verbs.add_parser(name, parents=[common]))
    return parser


def _root_option(argv):
    for i, arg in enumerate(argv):
        if arg == "--root" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--root="):
            return arg[len("--root="):]
    return None


def main(argv=None, out=None):
    """Run one call; returns its exit code. `out` replaces stdout (tests)."""
    argv = sys.argv[1:] if argv is None else list(argv)
    contract.open_channel(out)
    saved = sys.stdout, sys.stderr
    try:
        root = _root_option(argv)        # before parsing: a usage error under --root logs into that root too
        if root:
            os.environ["SURASURA_TEST_ROOT"] = os.path.abspath(root)
        try:
            args, usage = _parser().parse_args(argv), None
        except contract.CliError as e:
            args, usage = None, e
        contract.open_log()
        sys.stdout = sys.stderr = contract._ToLog()

        if usage is None and not args.version and not args.verb:
            usage = contract.CliError("usage", "Say what to do: a command, or --version. Run surasura-cli --help.")
        verb = "--version" if usage is None and args.version else (args.verb if usage is None else "?")

        def call():
            if usage is not None:
                raise usage
            contract.check_update()
            if args.version:
                return _version(args)
            contract.check_token_stores()
            return VERBS[args.verb][1](args)

        return contract.run(verb, call, argv, progress=getattr(args, "progress", False))
    finally:
        sys.stdout, sys.stderr = saved
        contract.close_log()


if __name__ == "__main__":
    sys.exit(main())
