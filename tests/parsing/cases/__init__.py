"""Every case of the suite. Each cases_<area>.py beside this file holds `CASES = [Case(...), ...]`; its area is the
file's name (ja_tokens, ja_text, ja_consumers, zh — a new file is a new area, picked up here with no other change).
Ids and groups: docs/agent instructions/Parsing_Suite.md."""
import dataclasses
import importlib
import pkgutil


def _collect():
    cases = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda info: info.name):
        if info.name.startswith("cases_"):
            module = importlib.import_module(f"{__name__}.{info.name}")
            area = info.name[len("cases_"):]
            cases.extend(dataclasses.replace(case, area=area) for case in module.CASES)
    return cases


CASES = _collect()
