"""A small local library: immutable files, optimistic revisions and a process lock."""
from contextlib import contextmanager
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import threading

from PIL import Image

from .catalog import Catalog, DataError, fingerprint, load_json, require
from .records import new_id, now, revise, validate_observation


class ConflictError(DataError):
    pass


def _safe_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", value), "无效记录编号")
    return value


def _atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n"
    temp = path.with_name(path.name+"."+new_id("tmp"))
    try:
        with temp.open("x", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


class Library:
    def __init__(self, directory, *, default_catalog=None):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._mutex = threading.RLock()
        if not (self.root/"catalog.json").exists():
            require(default_catalog is not None, "新库需要身体目录")
            catalog = default_catalog if isinstance(default_catalog, Catalog) else Catalog.read(default_catalog)
            with self._locked():
                if not (self.root/"catalog.json").exists():
                    _atomic_json(self.root/"catalog.json", catalog.data)
        self.catalog  # Fail immediately if a persisted catalog is invalid.

    @property
    def catalog(self):
        return Catalog.read(self.root/"catalog.json")

    @contextmanager
    def _locked(self):
        """OS releases the lock on process exit; a crash cannot leave a stale lease."""
        with self._mutex:
            lock = (self.root/".write.lock").open("a+b")
            lock.seek(0, 2)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                lock.close()
                raise ConflictError("另一个程序正在写入此库，请稍后重试") from exc
            try:
                yield
            finally:
                lock.seek(0)
                if os.name == "nt":
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                lock.close()

    def extend_catalog(self, additions):
        with self._locked():
            new = self.catalog.extended(additions)
            _atomic_json(self.root/"catalog.json", new.data)
        return new

    def add_character(self, label, *, species_ref, profile_ref, form_label=None, character_ref=None):
        require(isinstance(label, str) and 0 < len(label.strip()) <= 100, "角色名称需为1至100字")
        cat = self.catalog
        cat.get("profiles", profile_ref)
        cat.get("species", species_ref)
        if character_ref:
            cat.get("characters", character_ref)
        character_id = character_ref or new_id("character")
        form = {"id": new_id("form")+"@1", "label": form_label or label.strip()+"的形态",
                "character_ref": character_id, "species_ref": species_ref, "profile_ref": profile_ref,
                "expected_presence": {}, "status": "user_defined"}
        additions = {"forms": [form]}
        if not character_ref:
            additions["characters"] = [{"id": character_id, "label": label.strip()}]
        self.extend_catalog(additions)
        return form

    @property
    def assets(self):
        directory = self.root/"assets"
        return {p.stem: load_json(p) for p in directory.glob("*.json")} if directory.exists() else {}

    def register_image(self, path, *, allow_missing=False, expected_size=None):
        path = Path(path).resolve()
        exists = path.is_file()
        require(exists or allow_missing, "图片文件不存在")
        size, digest, kind, issues = expected_size, None, None, []
        if exists:
            raw = path.read_bytes()
            require(len(raw) <= 50*1024*1024, "图片超过50MB")
            try:
                with Image.open(io.BytesIO(raw)) as im:
                    require(im.format in {"PNG", "JPEG", "WEBP"}, "仅支持PNG、JPEG、WebP图片")
                    im.load()
                    size, kind = list(im.size), im.format
                    if all(low == high for low, high in im.convert("RGB").getextrema()):
                        issues.append("constant_color_image")
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                raise DataError("图片无法解码") from exc
            digest = hashlib.sha256(raw).hexdigest()
        else:
            issues.append("missing_image")
        image_id = "image_" + (digest or hashlib.sha256(str(path).encode()).hexdigest())
        asset = {"id": image_id, "path": str(path), "sha256": digest, "size": size,
                 "format": kind, "issues": issues, "registered_at": now()}
        target = self.root/"assets"/(image_id+".json")
        with self._locked():
            if not target.exists():
                _atomic_json(target, asset)
        return load_json(target)

    def upload_image(self, raw):
        require(isinstance(raw, bytes) and 0 < len(raw) <= 25*1024*1024, "上传图片需为1字节至25MB")
        try:
            with Image.open(io.BytesIO(raw)) as im:
                require(im.format in {"PNG", "JPEG", "WEBP"}, "不支持此图片格式")
                suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[im.format]
                im.verify()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise DataError("图片无法解码") from exc
        target = self.root/"images"/(hashlib.sha256(raw).hexdigest()+suffix)
        with self._locked():
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                with target.open("xb") as f:
                    f.write(raw)
        return self.register_image(target)

    def image_bytes(self, image_id):
        _safe_id(image_id)
        asset_path = self.root/"assets"/(image_id+".json")
        require(asset_path.exists(), "图片资产未登记")
        asset = load_json(asset_path)
        path = Path(asset["path"])
        require(path.is_file(), "原图缺失；不能借用另一张图")
        raw = path.read_bytes()
        require(asset["sha256"] == hashlib.sha256(raw).hexdigest(), "原图内容已变化；请作为新资产重新导入")
        return raw, {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[asset["format"]]

    def _directory(self, observation_id):
        return self.root/"observations"/_safe_id(observation_id)

    def head_id(self, observation_id):
        path = self._directory(observation_id)/"HEAD.json"
        return load_json(path)["annotation_id"] if path.exists() else None

    def read(self, observation_id, annotation_id=None):
        annotation_id = annotation_id or self.head_id(observation_id)
        require(annotation_id is not None, "找不到观测")
        path = self._directory(observation_id)/(_safe_id(annotation_id)+".json")
        require(path.is_file(), "找不到标注修订")
        return load_json(path)

    def records(self, collections=None):
        result = []
        for pointer in sorted((self.root/"observations").glob("*/HEAD.json")):
            r = self.read(pointer.parent.name)
            if collections is None or r["collection"] in collections:
                result.append(r)
        return result

    def history(self, observation_id):
        return sorted((load_json(p) for p in self._directory(observation_id).glob("*.json") if p.name != "HEAD.json"),
                      key=lambda r: (r["annotation"]["created_at"], r["annotation"]["id"]))

    def save(self, record, *, expected_revision=None):
        with self._locked():
            image_ref = _safe_id(record.get("image_ref"))
            asset_path = self.root/"assets"/(image_ref+".json")
            require(asset_path.is_file(), "图片资产未登记")
            validate_observation(record, self.catalog, {image_ref: load_json(asset_path)})
            oid, aid = record["observation_id"], record["annotation"]["id"]
            directory = self._directory(oid)
            path = directory/(_safe_id(aid)+".json")
            current = self.head_id(oid)
            if path.exists():
                require(load_json(path) == record, "同一修订编号不可覆盖不同内容")
                # Complete a revision published just before a crash in the HEAD update.
                # A newer HEAD is never rolled back by an old request.
                if current == expected_revision and current != aid and record['annotation']['parent_ids'] == ([current] if current else []):
                    _atomic_json(directory/'HEAD.json', {'annotation_id':aid})
                return record
            if current != expected_revision:
                raise ConflictError("此观测已有新修订，请重新载入后再保存")
            require(record["annotation"]["parent_ids"] == ([current] if current else []), "修订必须承接当前版本")
            if current:
                old = self.read(oid, current)
                for key in ("occurrence_id", "image_ref", "profile_ref", "subject", "coordinates", "collection"):
                    require(record[key] == old[key], f"{key}改变时请建立新的观测，保留原绑定")
                for flag in ("example_only", "test_only"):
                    require(not old.get(flag) or record.get(flag), f"不能移除隔离标记：{flag}")
            _atomic_json(path, record)
            _atomic_json(directory/"HEAD.json", {"annotation_id": aid})
            return record

    def edit(self, observation_id, expected_revision, changes, *, actor, review=None):
        # Save performs the final compare-and-swap under the OS lock.
        old = self.read(observation_id, expected_revision)
        updated = revise(old, self.catalog, changes, actor=actor, review=review)
        return self.save(updated, expected_revision=expected_revision)

    def verify(self):
        cat, assets = self.catalog, self.assets
        records, issues = self.records(), []
        for r in records:
            validate_observation(r, cat, assets)
            revisions = self.history(r["observation_id"])
            ids = {x["annotation"]["id"] for x in revisions}
            for revision in revisions:
                validate_observation(revision, cat, assets)
                require(set(revision["annotation"]["parent_ids"]) <= ids, "修订父版本缺失")
        for image_id, asset in assets.items():
            try:
                self.image_bytes(image_id)
            except DataError as exc:
                issues.append({"image_ref": image_id, "problem": str(exc)})
            for issue in asset["issues"]:
                if issue != "missing_image":
                    issues.append({"image_ref": image_id, "problem": issue})
        return {"records": len(records), "assets": len(assets), "catalog_sha256": cat.sha256, "image_issues": issues}
