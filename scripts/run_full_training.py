"""Wait for complete pinned downloads, prepare every file, then run one streaming epoch."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('datasets/india-law'))
    p.add_argument('--out',type=Path,default=Path('training/output/full-domain-20261009'))
    a=p.parse_args()
    status_path=a.root/'full-training-pipeline.json'
    def status(stage,**values):
        data={'stage':stage,'complete':False,'pid':os.getpid(),
              'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),**values}
        status_path.write_text(json.dumps(data,indent=2));print(json.dumps(data),flush=True)
    corpus=a.root/'full-domain-corpus'
    try:
        while True:
            snapshots={k:json.loads((a.root/'downloads'/k/'download-status.json').read_text()) for k in ('kanoon','vaquill')}
            if all(v.get('complete') for v in snapshots.values()):break
            if any(v.get('error_type') for v in snapshots.values()):raise RuntimeError('Dataset transfer failed. Resume downloads before restarting the pipeline.')
            status('waiting_for_complete_downloads',downloads={k:v.get('complete',False) for k,v in snapshots.items()})
            time.sleep(30)
        env=dict(os.environ);env['HF_HUB_OFFLINE']='1'
        if not (corpus/'manifest.json').exists() or not json.loads((corpus/'manifest.json').read_text()).get('complete'):
            if corpus.exists():raise RuntimeError('Incomplete corpus preparation exists. Preserve it for inspection and choose a new output path before restarting.')
            status('preparing_full_corpus')
            subprocess.run([sys.executable,'-m','training.prepare_full_corpus','--downloads',str(a.root/'downloads'),'--out',str(corpus)],env=env,check=True)
        status('training_full_epoch',corpus=str(corpus),output=str(a.out))
        cmd=[sys.executable,'-m','training.train_full_domain','--corpus',str(corpus),'--out',str(a.out)]
        if (a.out/'latest.json').exists():cmd.append('--resume')
        subprocess.run(cmd,env=env,check=True)
        actual=json.loads((a.out/'status.json').read_text())
        status('completed' if actual.get('complete') else 'incomplete',complete=bool(actual.get('complete')),training=actual)
    except BaseException as exc:
        status('failed',error_type=type(exc).__name__)
        raise


if __name__=='__main__':main()
