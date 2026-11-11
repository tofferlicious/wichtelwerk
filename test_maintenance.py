"""Maintenance retries and cadence, without waiting or launching child processes."""
import subprocess
from scripts.maintenance import run_due


def test_initial_tick_runs_mail_and_cleanup_then_daily_only(monkeypatch):
    calls=[]
    def run(command, **kwargs):
        calls.append(command[-1])
        return subprocess.CompletedProcess(command,0)
    monkeypatch.setattr(subprocess,'run',run)
    last=run_due(100,None)
    assert calls==['send-draw-mail','cleanup'] and last==100
    calls.clear()
    assert run_due(160,last)==100
    assert calls==['send-draw-mail']
    calls.clear()
    assert run_due(86500,last)==86500
    assert calls==['send-draw-mail','cleanup']


def test_cleanup_failure_retries_next_tick_and_mail_failure_does_not_skip_cleanup(monkeypatch,capsys):
    calls=[]
    def run(command, **kwargs):
        calls.append(command[-1])
        return subprocess.CompletedProcess(command,1)
    monkeypatch.setattr(subprocess,'run',run)
    assert run_due(100,None) is None
    assert run_due(160,None) is None
    assert calls==['send-draw-mail','cleanup','send-draw-mail','cleanup']
    assert 'failed' in capsys.readouterr().err.lower()
