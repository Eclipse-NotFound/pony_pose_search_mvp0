"""Read-only adapters. Frame ordinals are decoded before any sampling or scaling."""
from functools import lru_cache
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib

from PIL import Image, ImageOps, __version__ as PILLOW_VERSION
from multispecies.catalog import DataError, require

VIDEO = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
IMAGE = {".png", ".jpg", ".jpeg", ".webp"}
_context = threading.local()


class Cancelled(Exception):
    pass


def checkpoint():
    stop = getattr(_context, 'stop', None)
    if stop and stop.is_set():
        raise Cancelled('工作台已关闭，任务留待下次接续')


def kind_of(path):
    if path.is_dir():
        return "xfl" if (path / "DOMDocument.xml").is_file() else "directory"
    suffix = path.suffix.lower()
    return "video" if suffix in VIDEO else "image" if suffix in IMAGE else "fla" if suffix == ".fla" else "swf" if suffix == ".swf" else "unknown"


def within(path, root):
    resolved = Path(path).resolve()
    require(resolved.is_relative_to(Path(root).resolve()), "路径已离开登记的素材根目录")
    return resolved


def members(path):
    """Composite XFL identity covers every member, without following links."""
    for directory, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory)/d).is_symlink())
        for name in sorted(files):
            item = Path(directory)/name
            require(not item.is_symlink(), "XFL 复合素材包含链接，请使用实际文件")
            yield within(item, path)


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            checkpoint()
            digest.update(block)
    return digest.hexdigest()


def identity(path):
    if path.is_file():
        return sha_file(path)
    digest = hashlib.sha256()
    for p in members(path):
        digest.update(json.dumps([p.relative_to(path).as_posix(), p.stat().st_size, sha_file(p)], ensure_ascii=False).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def signature(path):
    if path.is_dir():
        items = list(members(path))
        return {"bytes": sum(p.stat().st_size for p in items), "mtime_ns": max((p.stat().st_mtime_ns for p in items), default=path.stat().st_mtime_ns)}
    stat = path.stat()
    return {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


@lru_cache(maxsize=2)
def binary(name):
    configured = os.environ.get("PONY_"+name.upper())
    if configured:
        require(Path(configured).is_file(), f"配置的 {name} 不存在")
        return str(Path(configured).resolve())
    found = shutil.which(name)
    if found:
        return found
    packages = Path(os.environ.get("LOCALAPPDATA", ""))/"Microsoft/WinGet/Packages"
    for candidate in sorted(packages.glob(f"Gyan.FFmpeg_*/ffmpeg*/bin/{name}.exe"), reverse=True):
        return str(candidate)
    raise DataError("视频读取需要 FFmpeg / ffprobe；可加入 PATH，或设置 PONY_FFMPEG、PONY_FFPROBE")


def run(name, args, timeout=180):
    checkpoint()
    process = subprocess.Popen([binary(name), *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    deadline = time.monotonic()+timeout
    try:
        while True:
            checkpoint()
            require(time.monotonic() < deadline, "媒体读取超时；可以单独重试这个文件")
            try:
                stdout, stderr = process.communicate(timeout=.25)
                break
            except subprocess.TimeoutExpired:
                continue
        require(process.returncode == 0, "媒体读取失败："+stderr.decode("utf-8", "replace")[-1400:])
        return stdout
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


@lru_cache(maxsize=1)
def decoder_version():
    return {name: run(name, ["-version"], 15).decode("utf-8", "replace").splitlines()[0] for name in ("ffmpeg", "ffprobe")}


def _xml(raw):
    require(len(raw) <= 64*1024*1024, "工程主文档过大，当前仅保留文件信息")
    declarations = raw.replace(b'\x00', b'').upper()  # Also reject declarations in UTF-16/32 XML.
    require(b"<!DOCTYPE" not in declarations and b"<!ENTITY" not in declarations, "不读取含外部声明的工程 XML")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DataError("工程主文档 XML 无法解析") from exc
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    require(root.tag == "DOMDocument", "未找到有效的 DOMDocument")
    scenes = []
    for i, scene in enumerate(root.findall("./timelines/DOMTimeline")):
        layers, end = [], 0
        for li, layer in enumerate(scene.findall("./layers/DOMLayer")):
            keys = []
            for frame in layer.findall("./frames/DOMFrame"):
                start, duration = int(frame.get("index", 0)), int(frame.get("duration", 1))
                require(start >= 0 and duration > 0, "工程关键帧范围无效")
                end = max(end, start+duration)
                keys.append({"index0": start, "duration": duration})
            layers.append({"index0": li, "name": layer.get("name"), "type": layer.get("layerType", "normal"), "stored_keys": keys})
        scenes.append({"index0": i, "name": scene.get("name"), "frames": end, "layers": layers})
    return {"width": root.get("width"), "height": root.get("height"), "frame_rate": root.get("frameRate"),
            "scenes": scenes, "library_items": len(root.findall("./symbols/Include")),
            "note": "已读存储结构；未渲染、未核对视频帧、角色实例或方向"}


def fla_document(path):
    """Read a bounded DOM member, including Adobe's nonstandard ZIP directory.

    Local records are size/CRC checked. No members are extracted or executed;
    reading one valid member does not certify the whole FLA.
    """
    bound = 64*1024*1024
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo('DOMDocument.xml')
            require(info.file_size <= bound, 'FLA 主文档过大')
            return archive.read(info), 'zip_xml'
    except zipfile.BadZipFile:
        pass
    size = path.stat().st_size
    with path.open('rb') as stream:
        for _ in range(200000):
            checkpoint()
            if stream.read(4) != b'PK\x03\x04':
                break
            header = stream.read(26)
            require(len(header) == 26, 'FLA 本地记录头不完整')
            _, flags, method, _, _, crc, packed_size, raw_size, nl, xl = struct.unpack('<HHHHHIIIHH', header)
            require(not flags & 9, 'FLA 本地记录含加密或未支持的数据描述符')
            require(stream.tell()+nl+xl+packed_size <= size, 'FLA 本地记录超出文件范围')
            name = stream.read(nl).decode('utf-8' if flags & 0x800 else 'cp437').replace('\\','/')
            stream.seek(xl, 1)
            if name != 'DOMDocument.xml':
                stream.seek(packed_size, 1)
                continue
            require(packed_size <= bound and raw_size <= bound, 'FLA 主文档过大')
            packed = stream.read(packed_size)
            require(method in {0,8}, 'FLA 主文档压缩方式暂不支持')
            if method == 8:
                decoder = zlib.decompressobj(-15)
                try:
                    raw = decoder.decompress(packed, bound+1)
                except zlib.error as exc:
                    raise DataError('FLA 主文档解压失败') from exc
                require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail, 'FLA 主文档压缩记录不完整或过大')
            else:
                raw = packed
            require(len(raw) == raw_size and zlib.crc32(raw) == crc, 'FLA 主文档大小或 CRC 不匹配')
            return raw, 'zip_local_records'
    raise DataError('FLA 中没有可核验的 DOMDocument.xml')


def inspect(path, kind, thumbnail):
    """Metadata/thumbnail only. Exact video indexes are built on demand."""
    if kind == "image":
        with Image.open(path) as source:
            source.load()
            if getattr(source, "is_animated", False):
                return {"capabilities": ["file"], "note": "动画图片已编目；暂未支持序列帧定位"}
            orientation = source.getexif().get(274, 1)
            im = ImageOps.exif_transpose(source)
            meta = {"width": im.width, "height": im.height, "raw_size": list(source.size), "exif_orientation": orientation,
                    "coordinates": "exif_oriented_image", "actual_format": source.format, "capabilities": ["file", "image", "pose_input"]}
            im.convert("RGB").resize(_thumb_size(im.size)).save(thumbnail, "JPEG", quality=84)
            return meta
    if kind == "video":
        probe = json.loads(run("ffprobe", ["-v", "error", "-show_streams", "-show_format", "-of", "json", path]))
        streams = [{k: v for k, v in s.items() if k in {"index", "codec_name", "codec_type", "width", "height", "time_base", "start_pts", "start_time", "duration", "nb_frames", "avg_frame_rate", "disposition"}}
                   for s in probe.get("streams", []) if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
        require(streams, "文件没有可读取的视频流")
        selected = streams[0]
        run("ffmpeg", ["-v", "error", "-y", "-noautorotate", "-i", path, "-map", f"0:{selected['index']}", "-vf", "scale=640:-2", "-frames:v", "1", thumbnail])
        return {"streams": streams, "default_stream": selected["index"], "duration": probe.get("format", {}).get("duration"),
                "width": selected.get("width"), "height": selected.get("height"), "capabilities": ["file", "video", "pose_input"],
                "coordinates": "encoded_frame_noautorotate", "decoder": decoder_version()}
    if kind in {"fla", "xfl"}:
        if kind == "xfl":
            with (path/"DOMDocument.xml").open('rb') as f:
                meta = _xml(f.read(64*1024*1024+1))
            meta.update(container="xfl", capabilities=["file", "structure"])
            return meta
        with path.open("rb") as f:
            magic = f.read(8)
        if magic == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            return {"container": "ole", "capabilities": ["file"], "note": "旧版 FLA：已编目，结构及渲染需要原生程序"}
        raw, container = fla_document(path)
        meta = _xml(raw)
        meta.update(container=container, capabilities=["file", "structure"])
        return meta
    if kind == "swf":
        with path.open("rb") as f:
            header = f.read(8)
        require(len(header) == 8 and header[:3] in (b"FWS", b"CWS", b"ZWS"), "SWF 头信息无效")
        return {"signature": header[:3].decode(), "swf_version": header[3], "declared_bytes": struct.unpack("<I", header[4:])[0],
                "capabilities": ["file"], "note": "仅读取文件头，不运行 SWF 内容"}
    return {"capabilities": ["file"], "note": "此格式目前只登记原文件"}


def _thumb_size(size):
    scale = min(1, 640/max(size))
    return tuple(max(1, round(x*scale)) for x in size)


def frame_index(path, stream, meta):
    selected = next((s for s in meta["streams"] if s["index"] == stream), None)
    require(selected is not None, "该视频流未登记")
    probe = json.loads(run("ffprobe", ["-v", "error", "-select_streams", str(stream), "-show_frames", "-show_entries",
                                      "frame=pts,best_effort_timestamp", "-of", "json", path], timeout=600))
    frames = probe.get("frames", [])
    require(frames, "没有可解码的视频帧")
    timebase = Fraction(selected["time_base"])
    require(timebase > 0, "视频时间单位无效")
    start = selected.get("start_pts")
    if start is None:
        start = next((f.get("pts", f.get("best_effort_timestamp")) for f in frames if f.get("pts", f.get("best_effort_timestamp")) is not None), None)
    return {"stream_index": stream, "time_base": [timebase.numerator, timebase.denominator], "start_pts": start,
            "decoder": decoder_version(), "frame_count": len(frames),
            "frames": [{"ordinal0": n, "pts": f.get("pts", f.get("best_effort_timestamp")),
                        "timestamp_basis": "pts" if "pts" in f else "best_effort" if "best_effort_timestamp" in f else "missing"}
                       for n, f in enumerate(frames)]}


def frame_position(index, ordinal):
    require(isinstance(ordinal, int) and not isinstance(ordinal, bool) and 0 <= ordinal < index["frame_count"], "帧号超出范围（内部从0开始）")
    frame = index["frames"][ordinal]
    pts, start = frame["pts"], index["start_pts"]
    elapsed = None if pts is None or start is None else Fraction(pts-start)*Fraction(*index["time_base"])
    return {"kind": "video_frame", "precision": "frame_exact", "stream_index": index["stream_index"],
            "presentation_ordinal0": ordinal, "pts": pts, "time_base": index["time_base"], "start_pts": start,
            "timestamp_basis": frame["timestamp_basis"], "seconds": float(elapsed) if elapsed is not None else None,
            "frame_count": index["frame_count"], "decoder": index["decoder"], "method": "decode_full_stream_select_ordinal_noautorotate"}


def extract(path, kind, position, output):
    if kind == "image":
        with Image.open(path) as im:
            require(not getattr(im, "is_animated", False), "动画图片暂不能建立静态位置")
            ImageOps.exif_transpose(im).convert("RGBA").save(output, "PNG")
    else:
        run("ffmpeg", ["-v", "error", "-y", "-noautorotate", "-i", path, "-map", f"0:{position['stream_index']}",
                       "-vf", f"select=eq(n\\,{position['presentation_ordinal0']})", "-frames:v", "1", "-fps_mode", "passthrough", output], timeout=600)
    require(output.is_file() and output.stat().st_size > 0, "未能生成所请求的画面")
    with Image.open(output) as im:
        im.load()
        return list(im.size)


def proxy(path, stream, output):
    run("ffmpeg", ["-v", "error", "-y", "-noautorotate", "-i", path, "-map", f"0:{stream}", "-an", "-vf", "scale=960:-2:force_original_aspect_ratio=decrease,setpts=PTS-STARTPTS", "-fps_mode", "vfr",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", output], timeout=1800)
    require(output.is_file(), "播放代理生成失败")
