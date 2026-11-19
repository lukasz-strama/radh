"""Regresja etykiet SELinux bez roota i bez zmiany polityki hosta."""
from pathlib import Path
import subprocess

import pytest

from deploy import init_secrets


def test_label_only_three_files_with_shared_context(tmp_path, monkeypatch):
    marker = tmp_path / 'selinux-enforce'
    marker.touch()
    monkeypatch.setattr(init_secrets, 'SELINUX_ENFORCE', marker)
    calls = []
    monkeypatch.setattr(init_secrets.subprocess, 'run', lambda args, **kw: calls.append((args, kw)))
    directory = tmp_path / 'secrets'
    init_secrets.label_secrets(directory)
    assert calls == [([
        'chcon', '--type=container_file_t', '--range=s0', '--',
        str(directory / 'alice'), str(directory / 'bob'), str(directory / 'mallory'),
    ], {'check': True, 'capture_output': True})]
    assert not directory.exists()


def test_no_relabel_without_selinux(tmp_path, monkeypatch):
    monkeypatch.setattr(init_secrets, 'SELINUX_ENFORCE', tmp_path / 'absent')
    def unexpected(*args, **kwargs):
        pytest.fail('Nie należy uruchamiać chcon bez SELinux.')
    monkeypatch.setattr(init_secrets.subprocess, 'run', unexpected)
    init_secrets.label_secrets(tmp_path)


@pytest.mark.parametrize('error', [FileNotFoundError(), subprocess.CalledProcessError(1, 'chcon', stderr=b'private')])
def test_relabel_failure_is_controlled(tmp_path, monkeypatch, error):
    marker = tmp_path / 'enforce'
    marker.touch()
    monkeypatch.setattr(init_secrets, 'SELINUX_ENFORCE', marker)
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(init_secrets.subprocess, 'run', fail)
    with pytest.raises(ValueError, match='SELinux') as caught:
        init_secrets.label_secrets(tmp_path)
    assert 'private' not in str(caught.value)


def test_requires_root_before_creating_any_files(tmp_path, monkeypatch):
    monkeypatch.setattr(init_secrets.os, 'geteuid', lambda: 1000)
    with pytest.raises(ValueError, match='sudo'):
        init_secrets.initialize(tmp_path / 'secrets')
    assert not (tmp_path / 'secrets').exists()
