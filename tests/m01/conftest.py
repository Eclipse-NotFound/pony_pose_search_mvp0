"""
M01 测试 conftest — 共享 fixtures 和工具函数。
"""

import os
import subprocess
import sys
import tempfile
import pytest

# 将 scripts/m01 加入 sys.path 以便直接导入 extract_frames 中的函数
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_SCRIPTS_M01 = os.path.join(_PROJECT_ROOT, "scripts", "m01")
if _SCRIPTS_M01 not in sys.path:
    sys.path.insert(0, _SCRIPTS_M01)


@pytest.fixture
def project_root():
    """返回项目根目录。"""
    return _PROJECT_ROOT


@pytest.fixture
def temp_dir():
    """提供临时目录，测试结束后自动清理。"""
    with tempfile.TemporaryDirectory() as td:
        yield td


def _generate_test_video(output_path: str, duration: float = 5.0, fps: int = 24):
    """
    使用 ffmpeg 生成测试视频（MKV，H.264）。
    返回 True 表示成功，False 表示跳过。
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"color=c=red:size=320x240:rate={fps}:duration={duration}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-f", "matroska",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False
    if not os.path.isfile(output_path) or os.path.getsize(output_path) < 1000:
        return False
    return True


@pytest.fixture
def small_test_video(temp_dir):
    """
    生成测试视频（直接路径，用于直接调用 extract_frames 函数的测试）。
    返回视频文件路径。
    """
    video_path = os.path.join(temp_dir, "test_video.mkv")
    if not _generate_test_video(video_path):
        pytest.skip("ffmpeg not available or failed to generate test video")
    return video_path


@pytest.fixture
def project_with_video(temp_dir):
    """
    创建完整的项目目录结构（含测试视频），用于 subprocess 端到端测试。

    结构：
        {temp_dir}/
            raw_videos/
                s01/
                    s01e15.mkv  (测试视频)
            frames/
                (M01 会在此创建输出)

    返回 (project_root, video_path) 元组。
    """
    # 创建 raw_videos/s01/ 目录
    raw_dir = os.path.join(temp_dir, "raw_videos", "s01")
    os.makedirs(raw_dir, exist_ok=True)

    video_path = os.path.join(raw_dir, "s01e15.mkv")
    if not _generate_test_video(video_path):
        pytest.skip("ffmpeg not available or failed to generate test video")

    # 确保 frames 目录不存在（让 M01 自己创建）
    frames_dir = os.path.join(temp_dir, "frames")
    if os.path.isdir(frames_dir):
        import shutil
        shutil.rmtree(frames_dir)

    return temp_dir, video_path
