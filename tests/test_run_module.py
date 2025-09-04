import importlib
import runpy
import sys
from types import SimpleNamespace


def test_run_import_sets_debug(monkeypatch):
    def fake_create_app(argv):
        return SimpleNamespace(debug=False), "socket"

    monkeypatch.setattr("app.create_app", fake_create_app)
    monkeypatch.setenv("DEBUG", "True")
    run = importlib.reload(importlib.import_module("run"))
    try:
        assert run.app.debug is True
        assert run.socketio == "socket"
    finally:
        monkeypatch.undo()
        importlib.reload(importlib.import_module("run"))


def test_run_main_executes_server(monkeypatch):
    def fake_create_app(argv):
        return SimpleNamespace(debug=False), "sock"

    monkeypatch.setattr("app.create_app", fake_create_app)
    called = {}

    def fake_server(listener, app):
        called["listener"] = listener
        called["app"] = app

    monkeypatch.setattr("eventlet.wsgi.server", fake_server)
    monkeypatch.setattr("eventlet.listen", lambda addr: ("listener", addr))
    monkeypatch.setenv("PORT", "6000")
    runpy.run_module("run", run_name="__main__")
    try:
        assert called["listener"] == ("listener", ("0.0.0.0", 6000))
        assert called["app"] is not None
    finally:
        monkeypatch.undo()
        importlib.reload(importlib.import_module("run"))
