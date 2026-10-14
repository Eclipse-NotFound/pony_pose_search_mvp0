"""Persistent mixed-media catalog CLI; never modifies source material."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/common'))
from multispecies import Library, DataError
from source_catalog import SourceCatalog, SourceService
from workflow import ProjectContext


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, default=ROOT/'data/pose_library_v2')
    sub = parser.add_subparsers(dest='command', required=True)
    add = sub.add_parser('add'); add.add_argument('paths', nargs='+'); add.add_argument('--exclude', action='append', default=[])
    scan = sub.add_parser('scan'); scan.add_argument('root_id'); scan.add_argument('--force', action='store_true')
    sub.add_parser('status')
    listing = sub.add_parser('list'); listing.add_argument('--query', default=''); listing.add_argument('--format', default=''); listing.add_argument('--offset', type=int, default=0)
    sub.add_parser('work', help='处理队列直到清空；Ctrl+C 留待下次继续')
    sub.add_parser('pause'); sub.add_parser('resume')
    retry = sub.add_parser('retry'); retry.add_argument('job_id')
    frame = sub.add_parser('frame'); frame.add_argument('file_id'); frame.add_argument('--frame', type=int, default=1, help='从1开始'); frame.add_argument('--stream', type=int)
    rebind = sub.add_parser('rebind'); rebind.add_argument('root_id'); rebind.add_argument('path')
    export = sub.add_parser('export'); export.add_argument('output', type=Path)
    legacy = sub.add_parser('legacy-report'); legacy.add_argument('output', type=Path)
    args = parser.parse_args()
    context = ProjectContext(ROOT, args.library)
    library, catalog = context.library, context.sources
    result = None
    try:
        if args.command == 'add':
            result = catalog.add_inputs(args.paths, excludes=args.exclude)
        elif args.command == 'scan':
            catalog.get_root(args.root_id)
            result = {'job_id': catalog.queue('scan', {'root_id': args.root_id, 'force': args.force})}
        elif args.command == 'list':
            result = catalog.list_files(query=args.query, format=args.format, offset=args.offset)
        elif args.command in {'pause','resume'}:
            catalog.pause(args.command == 'pause'); result = catalog.status()
        elif args.command == 'retry':
            catalog.retry(args.job_id); result = catalog.job(args.job_id)
        elif args.command == 'frame':
            file = catalog.file(args.file_id)
            result = {'job_id': catalog.queue('position', {'fid': file['id'], 'version_id': file['version_id'], 'ordinal0': args.frame-1, 'stream_index': args.stream})}
        elif args.command == 'rebind':
            catalog.get_root(args.root_id)
            result = {'job_id': catalog.queue('rebind', {'root_id': args.root_id, 'path': args.path})}
        elif args.command in {'export','legacy-report'}:
            result = catalog.export() if args.command == 'export' else SourceService(catalog,library).legacy_report()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            result = {'output': str(args.output.resolve())}
        elif args.command == 'work':
            catalog.start()
            try:
                while True:
                    result = catalog.status()
                    if result['paused'] or not any(result['states'].get(k,0) for k in ('queued','running')):
                        break
                    time.sleep(.4)
            except KeyboardInterrupt:
                pass
            finally:
                catalog.stop()
            result = catalog.status()
        else:
            result = catalog.status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (DataError,OSError) as exc:
        parser.exit(1, str(exc)+'\n')


if __name__ == '__main__':
    main()
