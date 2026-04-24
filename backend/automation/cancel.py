from __future__ import annotations

import threading

_MSG = "Run cancelled by user."
_stop_all_suite = threading.Event()
_stop_one_spike = threading.Event()


def request_stop_all_suite() -> None:
    _stop_all_suite.set()


def request_stop_one_spike() -> None:
    _stop_one_spike.set()


def is_stop_all_suite() -> bool:
    return _stop_all_suite.is_set()


def is_stop_one_spike() -> bool:
    return _stop_one_spike.is_set()


def clear_for_new_suite() -> None:
    _stop_all_suite.clear()
    from . import suite_state

    suite_state.clear_running_case()


def clear_for_isolated_spike_run() -> None:
    _stop_all_suite.clear()
    _stop_one_spike.clear()


def clear_stop_one_spike() -> None:
    _stop_one_spike.clear()


def cancel_message() -> str:
    return _MSG
