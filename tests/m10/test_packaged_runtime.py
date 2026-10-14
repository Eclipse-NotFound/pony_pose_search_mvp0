"""Data must survive replacing an application folder; AI must not respawn the GUI."""
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/common'))
import app_runtime
from workflow.models import ModelWorkflow


def test_source_library_stays_in_project(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    assert app_runtime.default_library(tmp_path) == tmp_path/'data/pose_library_v2'
    app_runtime.remember_library(tmp_path)
    assert not (tmp_path/'settings.json').exists()


def test_bundle_upgrade_preserves_library_and_runtime_state(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setenv('PONY_POSE_HOME', str(tmp_path/'用户 数据'))
    old, new = tmp_path/'v1', tmp_path/'v2'
    assert app_runtime.default_library(old) == tmp_path/'用户 数据/library'
    chosen = tmp_path/'D盘资料库'; chosen.mkdir()
    app_runtime.remember_library(chosen)
    assert app_runtime.default_library(new) == chosen
    from workflow.character_fla import AnimateRenderer
    assert AnimateRenderer(new).state_root.is_relative_to(tmp_path/'用户 数据')
    chosen.rmdir()
    with pytest.raises(FileNotFoundError, match='找不到'):
        app_runtime.default_library(new)


def test_packaged_ai_requires_separate_runtime(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from multispecies.catalog import DataError
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.delenv('POSE_AI_PYTHON', raising=False)
    model = ModelWorkflow.__new__(ModelWorkflow)
    model.context = SimpleNamespace(project=tmp_path)
    assert model.runtimes() == []
    with pytest.raises(DataError, match='可选功能'):
        model.select_runtime()
    with pytest.raises(DataError, match='不能把 M10'):
        model.select_runtime(sys.executable)


def test_video_uses_bundled_tools_before_system_path(tmp_path, monkeypatch):
    from source_catalog import media
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.delenv('PONY_FFMPEG', raising=False)
    tool = tmp_path/'vendor/ffmpeg/ffmpeg.exe'; tool.parent.mkdir(parents=True); tool.touch()
    media.binary.cache_clear()
    try:
        assert media.binary('ffmpeg') == str(tool)
    finally:
        media.binary.cache_clear()
