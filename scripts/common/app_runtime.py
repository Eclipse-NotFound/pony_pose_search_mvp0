"""Separate bundled read-only resources from the user's durable working data."""
import json
import os
from pathlib import Path
import sys


def bundled():
    return bool(getattr(sys, 'frozen', False))


def resource_root():
    return Path(sys._MEIPASS) if bundled() else Path(__file__).resolve().parents[2]


def user_home():
    override = os.environ.get('PONY_POSE_HOME')
    return Path(override).resolve() if override else Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'PonyPoseSearch'


def default_library(project):
    if not bundled():
        return Path(project)/'data/pose_library_v2'
    settings = user_home()/'settings.json'
    if settings.is_file():
        # Invalid settings are reported by the launcher, never silently discarded.
        saved = json.loads(settings.read_text(encoding='utf-8')).get('library')
        if saved:
            path = Path(saved)
            if not path.is_dir():
                raise FileNotFoundError('上次使用的资料库找不到了：'+str(path)+
                    '\n请连接原磁盘，或用 --library 指定资料库。设置文件：'+str(settings))
            return path
    return user_home()/'library'


def remember_library(path):
    if not bundled():
        return
    from multispecies.library import _atomic_json
    _atomic_json(user_home()/'settings.json', {'library': str(Path(path).resolve())})


def working_root(project):
    return user_home() if bundled() else Path(project)
