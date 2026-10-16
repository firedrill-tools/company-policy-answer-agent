"""Noninteractive policy Q&A with optional model-free data selection/copy."""
import argparse
import asyncio
from datetime import date
import json
from pathlib import Path
import signal
import sys

from .answer import PolicyAnswerService
from .datasets import initialize,list_cases,select
from .policies import PolicyCorpus


async def run(service,question,as_of,args):
    loop=asyncio.get_running_loop();task=asyncio.current_task();previous=signal.getsignal(signal.SIGTERM)
    loop.add_signal_handler(signal.SIGTERM,task.cancel)
    try:return await service.ask_async(question,as_of,args.model,output_root=args.output_root,base_url=args.base_url)
    finally:loop.remove_signal_handler(signal.SIGTERM);signal.signal(signal.SIGTERM,previous)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Sourced company-policy Q&A',allow_abbrev=False)
    parser.add_argument('question',nargs='?')
    group=parser.add_mutually_exclusive_group();group.add_argument('--case');group.add_argument('--list-cases',action='store_true');group.add_argument('--init-case')
    parser.add_argument('--as-of',type=date.fromisoformat)
    parser.add_argument('--corpus',type=Path,help='custom source, or new destination for --init-case')
    parser.add_argument('--model',help='enabled Claude model name')
    parser.add_argument('--output-root',type=Path)
    parser.add_argument('--base-url',default='https://api.anthropic.com',help='explicit Anthropic-compatible endpoint; HTTPS or loopback HTTP')
    args=parser.parse_args(argv)
    if (args.case or args.list_cases or args.init_case) and (args.question or args.as_of):parser.error('a selected case already supplies its question/date')
    if args.case and args.corpus:parser.error('--case and custom --corpus are separate input selections')
    if args.list_cases and args.corpus:parser.error('--list-cases uses the bundled manifest')
    if (args.list_cases or args.init_case) and (args.model or args.output_root or args.base_url!='https://api.anthropic.com'):parser.error('list/init does not execute a model')
    try:
        if args.list_cases:output=list_cases()
        elif args.init_case:
            if args.corpus is None:parser.error('--init-case requires a new --corpus destination')
            output=initialize(args.init_case,args.corpus)
        else:
            if args.case:
                case,corpus,_=select(args.case);question=case['question'];as_of=date.fromisoformat(case['as_of'])
            else:
                if not args.question:parser.error('supply a question or --case')
                corpus=PolicyCorpus(args.corpus) if args.corpus is not None else select('starter')[1]
                question=args.question;as_of=args.as_of or date.today()
            output=asyncio.run(run(PolicyAnswerService(corpus),question,as_of,args))
        print(json.dumps(output,indent=2));return 0
    except (Exception,asyncio.CancelledError,KeyboardInterrupt) as error:
        source=error if getattr(error,'evidence',None) is not None else error.__context__
        print(json.dumps({'error':str(error) or type(error).__name__,'type':type(error).__name__,'receipt_path':getattr(source,'receipt_path',None),
            'evidence_error':getattr(source,'evidence',{}).get('evidence_error') if getattr(source,'evidence',None) else None}),file=sys.stderr)
        return 130 if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt)) else 1


if __name__=='__main__':raise SystemExit(main())
