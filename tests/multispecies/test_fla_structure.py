"""Timeline identity, safe reads, and conservative suggestions; no Animate needed."""
from pathlib import Path
import struct
import sys
import zipfile
import zlib

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/common'))
from multispecies.catalog import DataError
from source_catalog import fla_structure as subject


def timeline(name='Scene 1', refs=(), duration=8, index=0):
    symbols = ''.join(f'<DOMSymbolInstance libraryItemName="{r}"/>' for r in refs)
    return f'<DOMTimeline name="{name}"><layers><DOMLayer name="misleading Character"><frames><DOMFrame index="{index}" duration="{duration}"><elements>{symbols}</elements></DOMFrame></frames></DOMLayer></layers></DOMTimeline>'


def fixture():
    return {
        'DOMDocument.xml': '<DOMDocument frameRate="2"><symbols><Include href="body.xml"/><Include href="head.xml"/><Include href="leg.xml"/><Include href="Character.xml"/></symbols><timelines>'+timeline(refs=('Exact Folder/~Body',))+'</timelines></DOMDocument>',
        'LIBRARY/body.xml': '<DOMSymbolItem name="Exact Folder/~Body"><timeline>'+timeline(refs=('Head', 'Leg'), duration=120)+'</timeline></DOMSymbolItem>',
        'LIBRARY/head.xml': '<DOMSymbolItem name="Head"><timeline>'+timeline(duration=100)+'</timeline></DOMSymbolItem>',
        'LIBRARY/leg.xml': '<DOMSymbolItem name="Leg"><timeline>'+timeline(duration=50)+'</timeline></DOMSymbolItem>',
        'LIBRARY/Character.xml': '<DOMSymbolItem name="Character"><timeline>'+timeline(duration=1)+'</timeline></DOMSymbolItem>',
    }


def write(path, data, container='zip'):
    if container == 'xfl':
        path.mkdir()
        for name, raw in data.items():
            child = path/name
            child.parent.mkdir(parents=True, exist_ok=True)
            child.write_bytes(raw.encode() if isinstance(raw, str) else raw)
    elif container == 'local':
        with path.open('wb') as stream:
            for name, raw in data.items():
                raw = raw.encode() if isinstance(raw, str) else raw
                encoded = name.encode('utf-8')
                compressor = zlib.compressobj(wbits=-15)
                packed = compressor.compress(raw)+compressor.flush()
                stream.write(b'PK\x03\x04'+struct.pack('<HHHHHIIIHH', 20, 0x800, 8, 0, 0, zlib.crc32(raw), len(packed), len(raw), len(encoded), 0)+encoded+packed)
            stream.write(b'ADOBE_TRAILER')
    else:
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in data.items():
                archive.writestr(name, raw)
    return path


@pytest.mark.parametrize('container', ['zip', 'local', 'xfl'])
def test_exact_timelines_and_conservative_suggestions(tmp_path, container):
    path = write(tmp_path/'template.fla', fixture(), container)
    result = subject.inspect_structure(path)
    items = {x['id']:x for x in result['timelines']}
    assert items['scene:0']['frame_count'] == 8
    assert items['scene:0']['index0'] == 0
    assert items['symbol:Exact Folder/~Body']['frame_count'] == 120
    assert items['symbol:Exact Folder/~Body']['suggested']
    assert items['symbol:Head']['frame_count'] == 100
    assert not items['symbol:Head']['suggested']
    assert not items['symbol:Character']['suggested']
    assert result['native_inspect'] is False
    assert result['warnings']


def test_ole_explicitly_requires_native_inspection(tmp_path):
    path = tmp_path/'old.fla'
    path.write_bytes(subject.OLE_MAGIC+b'opaque binary')
    result = subject.inspect_structure(path)
    assert result['container'] == 'ole'
    assert result['native_inspect'] and not result['timelines']


@pytest.mark.parametrize('container', ['zip', 'local'])
@pytest.mark.parametrize('bad_name', ['../outside.xml', '/absolute.xml', 'C:/drive.xml', 'LIBRARY/../../escape.xml', 'LIBRARY\\..\\escape.xml'])
def test_archive_rejects_dangerous_names_even_for_unused_members(tmp_path, container, bad_name):
    data = fixture()
    data[bad_name] = 'unused'
    path = write(tmp_path/'unsafe.fla', data, container)
    with pytest.raises(DataError, match='危险|绝对'):
        subject.inspect_structure(path)


@pytest.mark.parametrize('container', ['zip', 'local', 'xfl'])
@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16'])
def test_xml_declarations_rejected_in_library_members(tmp_path, container, encoding):
    data = fixture()
    data['LIBRARY/head.xml'] = '<!DOCTYPE DOMSymbolItem [<!ENTITY x SYSTEM "file:///secret">]><DOMSymbolItem name="Head"/>'.encode(encoding)
    with pytest.raises(DataError, match='声明'):
        subject.inspect_structure(write(tmp_path/'unsafe.fla', data, container))


def test_duplicate_exact_symbol_names_rejected(tmp_path):
    data = fixture()
    data['LIBRARY/leg.xml'] = data['LIBRARY/head.xml']
    with pytest.raises(DataError, match='重复库元件名称'):
        subject.inspect_structure(write(tmp_path/'duplicate.fla', data))


def test_duplicate_archive_member_rejected(tmp_path):
    path = write(tmp_path/'duplicate.fla', fixture())
    with pytest.warns(UserWarning), zipfile.ZipFile(path, 'a') as archive:
        archive.writestr('LIBRARY/head.xml', fixture()['LIBRARY/head.xml'])
    with pytest.raises(DataError, match='重复成员'):
        subject.inspect_structure(path)


def test_case_alias_cannot_bypass_structural_duplicate_rejection(tmp_path):
    data = fixture()
    data['library/HEAD.xml'] = data['LIBRARY/head.xml']
    with pytest.raises(DataError, match='重复成员'):
        subject.inspect_structure(write(tmp_path/'alias.fla', data))


def test_adobe_repeated_non_structure_descriptor_is_ignored(tmp_path):
    path = write(tmp_path/'descriptor.fla', fixture())
    with zipfile.ZipFile(path, 'a') as archive:
        archive.writestr('mimetype', b'application/octet-stream')
        with pytest.warns(UserWarning):
            archive.writestr('mimetype', b'application/octet-stream')
    assert len(subject.inspect_structure(path)['timelines']) == 5


@pytest.mark.parametrize('container', ['zip', 'local', 'xfl'])
def test_total_xml_limit_enforced(tmp_path, monkeypatch, container):
    path = write(tmp_path/'budget.fla', fixture(), container)
    monkeypatch.setattr(subject, 'MAX_TOTAL', 800)
    with pytest.raises(DataError, match='总量'):
        subject.inspect_structure(path)


@pytest.mark.parametrize('container', ['zip', 'local', 'xfl'])
def test_member_count_limit_enforced(tmp_path, monkeypatch, container):
    path = write(tmp_path/'budget.fla', fixture(), container)
    monkeypatch.setattr(subject, 'MAX_MEMBERS', 3)
    with pytest.raises(DataError, match='数量'):
        subject.inspect_structure(path)


def test_missing_included_symbol_cannot_silently_look_complete(tmp_path):
    data = fixture()
    del data['LIBRARY/head.xml']
    with pytest.raises(DataError, match='缺失'):
        subject.inspect_structure(write(tmp_path/'missing.fla', data))


@pytest.mark.parametrize('container', ['zip', 'local', 'xfl'])
def test_member_limit_enforced_before_parsing(tmp_path, monkeypatch, container):
    path = write(tmp_path/'large.fla', fixture(), container)
    monkeypatch.setattr(subject, 'MAX_MEMBER', 32)
    with pytest.raises(DataError, match='上限'):
        subject.inspect_structure(path)


def test_local_crc_failure_rejected(tmp_path):
    path = write(tmp_path/'bad.fla', fixture(), 'local')
    raw = bytearray(path.read_bytes())
    raw[14] ^= 0xff
    path.write_bytes(raw)
    with pytest.raises(DataError, match='CRC'):
        subject.inspect_structure(path)


@pytest.mark.parametrize('index,duration', [(-1, 8), (0, 0), (0, 10000001)])
def test_invalid_frame_ranges_rejected(tmp_path, index, duration):
    data = {'DOMDocument.xml': '<DOMDocument><timelines>'+timeline(index=index, duration=duration)+'</timelines></DOMDocument>'}
    with pytest.raises(DataError, match='关键帧范围'):
        subject.inspect_structure(write(tmp_path/'range.fla', data))


def test_scene_labels_and_tween_bounds_preserved(tmp_path):
    data = {'DOMDocument.xml': '<DOMDocument xmlns="http://ns.adobe.com/xfl/2008/"><timelines><DOMTimeline name="角度"><layers><DOMLayer><frames><DOMFrame index="0" duration="12" name="front" labelType="name" tweenType="motion"/><DOMFrame index="12" duration="2" name="side"/></frames></DOMLayer></layers></DOMTimeline></timelines></DOMDocument>'}
    item = subject.inspect_structure(write(tmp_path/'labels.fla', data))['timelines'][0]
    assert item['frame_count'] == 14
    assert item['stored_key_starts0'] == [0,12]
    assert item['labels'][1]['name'] == 'side'
    assert item['tween_types'] == ['motion']


def test_scene_index_is_exact_even_when_scene_names_repeat(tmp_path):
    data = {'DOMDocument.xml': '<DOMDocument><timelines>'+timeline()+timeline(duration=2)+'</timelines></DOMDocument>'}
    items = subject.inspect_structure(write(tmp_path/'scenes.fla', data))['timelines']
    assert [(t['id'], t['index0'], t['frame_count']) for t in items] == [('scene:0', 0, 8), ('scene:1', 1, 2)]
