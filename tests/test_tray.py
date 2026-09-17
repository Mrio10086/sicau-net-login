from sicau_net.tray import COLORS, make_icon
from sicau_net.worker import State


def test_make_icon_size_and_mode():
    image = make_icon(State.ONLINE)
    assert image.size == (64, 64)
    assert image.mode == "RGBA"


def test_every_state_has_a_colour():
    for state in State:
        assert state in COLORS


def test_unknown_state_falls_back():
    assert make_icon("nonsense").size == (64, 64)


def test_states_have_distinct_colours_for_online_and_offline():
    assert COLORS[State.ONLINE] != COLORS[State.OFFLINE]
