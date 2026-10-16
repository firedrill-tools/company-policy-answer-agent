"""Fresh locked dependencies plus wheel and sdist outside the source checkout."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import tomllib
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
UV=os.environ.get('UV') or shutil.which('uv')
if not UV:raise RuntimeError('uv is required for distribution verification')
VERSION=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
wheel=ROOT/'dist'/f'company_policy_answer_agent-{VERSION}-py3-none-any.whl'
sdist=ROOT/'dist'/f'company_policy_answer_agent-{VERSION}.tar.gz'
env={**os.environ}
for key in ('ANTHROPIC_API_KEY','VIRTUAL_ENV','PYTHONPATH','PYTHONHOME'):env.pop(key,None)


def run(command,cwd,check=True):
    return subprocess.run(command,cwd=cwd,env=env,check=check,text=True,capture_output=True,timeout=180)


def exercise(python,base):
    cli=[str(python),'-I','-m','policy_answer.cli']
    run([str(python.parent/'policy-answer'),'--help'],base)
    manifest=json.loads(run([*cli,'--list-cases'],base).stdout)
    assert len(manifest['cases'])==11 and manifest['version']==1
    for case in manifest['cases']:
        file=base/f'{case["id"]}.json'
        selected=json.loads(run([*cli,'--init-case',case['id'],'--corpus',str(file)],base).stdout)
        assert selected['sha256']==case['sha256'] and file.stat().st_mode&0o777==0o600
    for case_id in ('ambiguous-topic','out-of-scope'):
        result=json.loads(run([*cli,'--case',case_id],base).stdout)
        assert result['execution_kind']=='model_free_clarification' and result['reported_usage']['attempts']==0
    failed=run([*cli,'--case','starter','--model','claude-sonnet-4-6'],base,False)
    assert failed.returncode==1
    receipt=json.loads(Path(json.loads(failed.stderr)['receipt_path']).read_text())
    assert receipt['status']=='failed' and receipt['provider_observations']==[]
    program='''
from datetime import date
from pathlib import Path
import sys
import policy_answer
from policy_answer.answer import SourceAnswer,validate_answer
from policy_answer.policies import PolicyCorpus
assert Path(policy_answer.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
base=Path(sys.argv[1]);corpus=PolicyCorpus(base/'busy.json');before=corpus.path.read_bytes()
assert len(corpus.documents)==24 and len({p.topic for p in corpus.documents})==8
assert [p.id for p in corpus.active_authorities('office-expense',date(2026,10,15))]==['EXPENSE-2026']
validate_answer(SourceAnswer(status='answered',answer='Obtain manager approval before ordering and submit receipts within 30 days.',citations=['EXPENSE-2026']),corpus,'office-expense',date(2026,10,15),{'EXPENSE-2026'})
old=PolicyCorpus(base/'historical-boundary.json')
assert [p.id for p in old.active_authorities('remote-work',date(2025,12,31))]==['REMOTE-2024']
assert corpus.path.read_bytes()==before
'''
    run([str(python),'-I','-c',program,str(base)],base)


with TemporaryDirectory(prefix='policy-distribution-') as directory:
    temp=Path(directory)
    with ZipFile(wheel) as archive:
        assert 'policy_answer/sample_data/manifest.json' in archive.namelist()
        assert len([n for n in archive.namelist() if n.startswith('policy_answer/sample_data/') and n.endswith('.json')])==12
    requirements=temp/'requirements.txt'
    requirements.write_text(run([UV,'export','--locked','--no-dev','--no-emit-project','--format','requirements-txt'],ROOT).stdout)
    wheel_env=temp/'wheel-env';run([UV,'venv','--python',sys.executable,str(wheel_env)],temp)
    wheel_python=wheel_env/'bin/python'
    run([UV,'pip','sync','--python',str(wheel_python),str(requirements)],temp)
    run([UV,'pip','install','--python',str(wheel_python),'--no-deps',str(wheel)],temp)
    wheel_case=temp/'wheel-case';wheel_case.mkdir();exercise(wheel_python,wheel_case)
    source_root=temp/'source';source_root.mkdir()
    with tarfile.open(sdist) as archive:archive.extractall(source_root,filter='data')
    source,=source_root.iterdir();assert (source/'uv.lock').exists()
    run([UV,'sync','--locked','--no-dev','--no-editable','--project',str(source)],temp)
    source_case=temp/'source-case';source_case.mkdir();exercise(source/'.venv/bin/python',source_case)
print('Wheel and sdist passed fresh locked installs, console/module CLI, eleven private cases, model-free clarification, failed-key receipt and actual busy/historical source-authority operations outside checkout.')
