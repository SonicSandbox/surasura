"""surasura-cli's entry (02-contract §1): `python -m app.cli <verb> …` from source, surasura-cli.exe frozen.

Every verb answers with JSON lines on stdout and an exit code (app/cli/contract.py). Verbs come from VERBS below.
"""
import argparse
import os
import sys

from app.cli import connect_verbs, contract, verbs


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
    from app import __version__, analyzer, library_store, token_index
    return {"app": __version__, "engine": analyzer.ENGINE_REVISION, "schema": token_index.SCHEMA_VERSION,
            "store": library_store.STORE_SCHEMA}      # the library store's schema (2.5)


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
    "status": (verbs.status_args, verbs.status, True),
    "list": (verbs.list_args, verbs.list_words, True),
    "known": (verbs.known_args, verbs.known, True),
    "known-sync": (verbs.known_sync_args, verbs.known_sync, True),
    "generate": (verbs.generate_args, verbs.generate, True),
    "junban": (verbs.junban_args, verbs.junban, True),
    "resort": (verbs.resort_args, verbs.resort, True),          # P2.2
    "backfill": (verbs.backfill_args, verbs.backfill, True),
    "pick": (verbs.pick_args, verbs.pick, True),
    # P2.1: the library verbs for Connect and hato (app/cli/connect_verbs.py)
    "register": (connect_verbs.register_args, connect_verbs.register, True),
    "place": (connect_verbs.place_args, connect_verbs.place, True),
    "finish": (connect_verbs.finish_args, connect_verbs.finish, True),
    "connect": (connect_verbs.connect_args, connect_verbs.connect, True),
    # P2.3: the setup checks
    "setup": (connect_verbs.setup_args, connect_verbs.setup, True),
}

# The verbs that answer while an update is staged: `status` writes nothing and says so (`update_staged`). Every other
# verb answers `update-staged` (02 §7).
ANSWER_WHILE_UPDATING = {"status"}


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
            if verb not in ANSWER_WHILE_UPDATING:
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
