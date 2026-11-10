# SPDX-License-Identifier: GPL-3.0-or-later
"""P3.3's planted-bug pass (research/mutants JUDGED-P3.3): `auto.decide_actions`' gap the change's own tests missed —
your 順 actions run automatically only when `junban_auto_actions` is exactly True.

What a wrong answer would cost: an install that never answered the onboarding's question (the key unset) or a
settings.json hand-edited to "yes" would have Connect tag, flag and suspend cards on its own (HY-6: only after you
said yes).
"""
import pytest

from modules.junban import auto, connect

ACTIONS = {"junban_later_tag": True, "junban_later_flag": True, "junban_later_suspend": True,
           "junban_tag": "Surasura::順", "junban_write_frequency": True}


@pytest.mark.parametrize("answer", [None, "yes", 1])
@pytest.mark.parametrize("connect_on", [False, True])
def test_your_actions_run_automatically_only_when_you_said_exactly_yes(monkeypatch, answer, connect_on):
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", False)     # the suspend setting's own say isn't asked here
    settings = dict(ACTIONS, connect_enabled=connect_on)
    if answer is not None:
        settings["junban_auto_actions"] = answer
    out = auto.decide_actions(settings)
    assert out["junban_later_tag"] is False and out["junban_later_flag"] is False
    assert out["junban_later_suspend"] is False and out["junban_tag"] == "" and out["junban_write_frequency"] is False
    said_yes = auto.decide_actions(dict(ACTIONS, connect_enabled=connect_on, junban_auto_actions=True))
    assert said_yes["junban_later_tag"] is True and said_yes["junban_tag"] == "Surasura::順"
