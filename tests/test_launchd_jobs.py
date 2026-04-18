import plistlib
from pathlib import Path

from api import launchd_jobs


class DummyCompleted:
    def __init__(self, returncode=0, stdout='', stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _write_plist(path: Path, data: dict) -> None:
    path.write_bytes(plistlib.dumps(data))


def test_list_launchd_jobs_filters_and_parses(tmp_path, monkeypatch):
    launch_agents = tmp_path / 'Library' / 'LaunchAgents'
    launch_agents.mkdir(parents=True)

    tracked = launch_agents / 'com.banyar.nexus-webui.plist'
    _write_plist(
        tracked,
        {
            'Label': 'com.banyar.nexus-webui',
            'ProgramArguments': ['/usr/bin/python3', '/tmp/server.py'],
            'WorkingDirectory': '/tmp/hermes-webui',
            'RunAtLoad': True,
            'StartInterval': 10800,
            'StandardOutPath': '/tmp/webui.log',
            'StandardErrorPath': '/tmp/webui.err',
        },
    )

    unrelated = launch_agents / 'com.example.other.plist'
    _write_plist(
        unrelated,
        {
            'Label': 'com.example.other',
            'ProgramArguments': ['/bin/echo', 'hello'],
        },
    )

    def fake_run(cmd, timeout=10):
        label = cmd[-1].split('/')[-1]
        if label == 'com.banyar.nexus-webui':
            return DummyCompleted(
                0,
                'state = running\npid = 24733\nlast exit code = (never exited)\n',
                '',
            )
        return DummyCompleted(1, '', 'not found')

    monkeypatch.setattr(launchd_jobs, 'LAUNCH_AGENTS_DIR', launch_agents)
    monkeypatch.setattr(launchd_jobs, '_run', fake_run)

    jobs = launchd_jobs.list_launchd_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job['label'] == 'com.banyar.nexus-webui'
    assert job['status_class'] == 'active'
    assert job['status_label'] == 'running'
    assert job['runtime']['pid'] == 24733
    assert job['schedule_display'] == 'Every 3h'
    assert job['stdout_path'] == '/tmp/webui.log'


def test_list_launchd_jobs_accepts_hint_matched_jobs(tmp_path, monkeypatch):
    launch_agents = tmp_path / 'Library' / 'LaunchAgents'
    launch_agents.mkdir(parents=True)

    hinted = launch_agents / 'custom-watchdog.plist'
    _write_plist(
        hinted,
        {
            'Label': 'custom.watchdog',
            'ProgramArguments': ['/usr/bin/python3', '/Users/test/git-repos/nexus-instance/scripts/service_watchdog.py'],
        },
    )

    monkeypatch.setattr(launchd_jobs, 'LAUNCH_AGENTS_DIR', launch_agents)
    monkeypatch.setattr(launchd_jobs, '_run', lambda cmd, timeout=10: DummyCompleted(1, '', 'not loaded'))

    jobs = launchd_jobs.list_launchd_jobs()
    assert len(jobs) == 1
    assert jobs[0]['label'] == 'custom.watchdog'
    assert jobs[0]['status_class'] == 'disabled'
    assert jobs[0]['status_label'] == 'not loaded'
