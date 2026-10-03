"""Fail fast if a CLI subprocess attempts any socket connection."""

import socket


def _blocked(*args, **kwargs):
    raise AssertionError("offline CLI attempted a network connection")


socket.create_connection = _blocked
socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
