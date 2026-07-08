"""Unit tests for the rolling-aware i+1 cost metric (analyzer-03).

The metric ranks a candidate example sentence by how many of its OTHER unknown words are
*rarer* than the target word. More-common co-words are learned first, so they'll already be
known when the learner reaches the target and shouldn't make the sentence look "hard". This is
what lets the fixed-size candidate buffer keep the sentences that actually become clean i+1
examples — with no extra passes and no bigger buffer.
"""
from app.analyzer import rolling_context_cost


def test_counts_only_co_words_rarer_than_target():
    # Target is the rarest unknown -> every co-word is more common (learned first) -> cost 0.
    assert rolling_context_cost(1, [1, 5, 9]) == 0
    # Co-words with freq 1 and 2 are rarer than the target (freq 5) -> they stay unknown -> 2.
    assert rolling_context_cost(5, [1, 2, 5, 9]) == 2
    # The most common word -> all the others are rarer -> highest cost.
    assert rolling_context_cost(9, [1, 2, 5, 9]) == 3
    # A single rarer co-word.
    assert rolling_context_cost(10, [3, 10]) == 1


def test_ignores_ties_and_the_target_itself():
    # Co-words with the SAME frequency as the target are not counted (nor is the target itself).
    assert rolling_context_cost(5, [5, 5, 5]) == 0
    # Only the strictly-rarer co-word counts.
    assert rolling_context_cost(5, [2, 5, 5, 8]) == 1
