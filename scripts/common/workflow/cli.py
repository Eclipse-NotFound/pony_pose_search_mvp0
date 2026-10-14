"""The CLI adapter for the same operations as M10 (no GUI imports)."""
import argparse
import json
from pathlib import Path
import sys

from multispecies.catalog import DataError, load_json
from multispecies.library import _atomic_json
from .project import ProjectContext
from .inventory import inventory, create_copy

ROOT = Path(__file__).resolve().parents[3]


def _json(path):
    return load_json(path) if path else {}


def run_module(module_id, argv=None):
    p = argparse.ArgumentParser(description=module_id+' 共用姿态资料库入口')
    p.add_argument('--workflow', action='store_true')
    p.add_argument('--project-root', type=Path, default=ROOT)
    p.add_argument('--library', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--actor', default='命令行用户')
    p.add_argument('--request', type=Path, help='操作参数 JSON，与共同流程参数同义')
    p.add_argument('--action', choices={
        'M01':['list','import','frames','position','character-inspect','character-prepare',
               'character-export','character-accept','character-positions'], 'M02':['list','decide','sets'],
        'M03':['list','region','history'], 'M04':['list','generate'],
        'M05':['edit'], 'M06':['verify','derive','migrate','snapshot','pair','export','train'],
        'M07':['query'], 'M08':['search'], 'M09':['export'],
        'AI':['models','register','predict','suggestions','review','jobs','job','retry','cancel','pause']
    }[module_id])
    p.add_argument('--wait',action='store_true',help='处理本次排队任务至结束，失败返回非零')
    p.add_argument('--observation');p.add_argument('--revision')
    p.add_argument('--patch',type=Path);p.add_argument('--review',type=Path)
    p.add_argument('--contract',default='pony.body14@1');p.add_argument('--options',type=Path)
    p.add_argument('--source-filters',type=Path);p.add_argument('--query-ref');p.add_argument('--run-ref')
    p.add_argument('--output-dir',type=Path)
    args = p.parse_args(argv)
    context = None
    try:
        context = ProjectContext(args.project_root, args.library)
        request=_json(args.request)
        action=args.action or {'M01':'list','M02':'list','M03':'list','M04':'list','M05':'edit',
            'M06':'verify','M07':'query','M08':'search','M09':'export','AI':'jobs'}[module_id]
        operations={
            'M01':{'list':context.sources.list_files,'import':context.sources.add_inputs,
                   'frames':context.dataset.queue_frames,'position':context.sources.create_position,
                   'character-inspect':context.characters.inspect,'character-prepare':context.characters.prepare_export,
                   'character-export':context.characters.queue_export,'character-accept':context.characters.accept_export,
                   'character-positions':context.characters.positions},
            'M02':{'list':context.dataset.candidates,'decide':context.dataset.decide,'sets':context.dataset.candidate_set},
            'M03':{'list':context.dataset.regions,'region':context.dataset.region,'history':context.dataset.store.history},
            'M04':{'list':context.dataset.samples,'generate':context.dataset.queue_generate},
            'M06':{'verify':context.library.verify,'derive':context.derive,'snapshot':context.training.freeze,
                   'pair':context.training.freeze_pair,'export':context.training.materialize,'train':context.models.queue_train},
            'AI':{'models':context.models.models,'register':context.models.register,'predict':context.models.queue_predict,
                  'suggestions':context.models.suggestions,'review':context.models.review,'jobs':context.sources.status,
                  'job':context.sources.job,'retry':context.sources.retry,'cancel':context.sources.cancel,'pause':context.sources.pause}}
        if module_id=='M05':
            result=context.library.edit(args.observation,args.revision,_json(args.patch),actor=args.actor,
                review=_json(args.review) if args.review else None)
        elif module_id=='M07':
            result=context.poses.prepare_query(args.observation,revision=args.revision,contract_ref=args.contract,
                options=_json(args.options),source_filters=_json(args.source_filters))
        elif module_id=='M08':result=context.poses.search(args.query_ref)
        elif module_id=='M09':
            result={k:str(v) for k,v in context.poses.export(args.run_ref,output_dir=args.output_dir,include_html=True).items()}
        elif module_id=='M06' and action=='migrate':
            result=context.sources.queue('migration',request,'migration:'+__import__('uuid').uuid4().hex)
        else:result=operations[module_id][action](**request)
        if args.wait:
            import time
            context.sources.pause(False);context.sources.start()
            queued=[result] if isinstance(result,str) and result.startswith('job_') else (result.get('jobs',[]) if isinstance(result,dict) else [])
            while True:
                jobs=[context.sources.job(j) for j in queued]
                if jobs and all(j['state'] in {'done','failed','cancelled'} for j in jobs):break
                if not jobs and not any(context.sources.status()['states'].get(k,0) for k in ('queued','running')):break
                time.sleep(.2)
            if queued:
                result=[context.sources.job(j) for j in queued]
                failures=[j for j in result if j['state']!='done']
                if failures:raise DataError(str(failures))
        if args.output:
            _atomic_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return result
    except (DataError, OSError, KeyError, TypeError, ValueError) as exc:
        p.exit(1, str(exc)+'\n')
    finally:
        if context:
            context.close()


def maybe_run_module(module_id):
    run_module(module_id)
    return True


def audit_main(argv=None):
    p = argparse.ArgumentParser(description='只读盘点旧资料，或建立不覆盖原件的独立资料副本')
    p.add_argument('--project-root', type=Path, default=ROOT)
    p.add_argument('--library', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--copy-to', type=Path)
    args = p.parse_args(argv)
    try:
        result = create_copy(args.project_root, args.copy_to, args.library) if args.copy_to else inventory(args.project_root, args.library)
        if args.output:
            _atomic_json(args.output, result)
        print(json.dumps(result if args.copy_to else {'counts': result['counts'], 'conflicts': result['conflicts'],
              'issues': result['issues'], 'inventory_sha256': result['inventory_sha256']}, ensure_ascii=False))
    except (DataError, OSError, ValueError) as exc:
        p.exit(1, str(exc)+'\n')
