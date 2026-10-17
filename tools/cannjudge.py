#!/usr/bin/env python3
"""Stage a validated kernel and drive the normal CANNJudge browser UI."""
import argparse
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from judge_workflow.core import (ROOT, Journal, check_origin, check_review, compare_results,
                           digest, read_json, static_audit, utcnow, validate_candidate, write_json)
from judge_workflow.repository import export_result, publish_candidate, sync_candidate


@contextmanager
def exclusive_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            lock.write(b'0')
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def stage(args):
    from verify_submission import verify
    from zipfile import ZipFile
    data = (ROOT / 'operators/rotary_pos_emb/kernel.asc').read_bytes()
    review = read_json(args.review)
    check_review(data, review)
    if b'\r' in data:
        raise ValueError('Use LF line endings so editor readback can be byte-exact')
    package = read_json(ROOT / 'dist/manifest.json')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if package['git_commit'] != revision or package['kernel_sha256'] != digest(data):
        raise ValueError('Package is not the current committed source')
    committed = subprocess.check_output(['git', 'show', revision + ':operators/rotary_pos_emb/kernel.asc'], cwd=ROOT)
    if committed != data:
        raise ValueError('Commit and validate the kernel before staging')
    with ZipFile(ROOT / 'dist/rotaryposemb_1743_submission.zip') as archive:
        names = [i.filename for i in archive.infolist() if not i.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate entries in submission ZIP')
        verify({name: archive.read(name) for name in names}, data)
    normal = ROOT / 'benchmarks/results' / (package['result'] + '.json')
    audit = ROOT / 'benchmarks/results' / (package['launch_audit'] + '.json')
    profile = ROOT / 'benchmarks/profiles' / package['launch_profile'] / 'launch_count.json'
    normal_json = read_json(normal)
    expected = {c['name'] for c in read_json(ROOT / 'tests/cases.json')}
    if {c['name'] for c in normal_json['cases']} != expected:
        raise ValueError('Staging requires the complete fixed local correctness suite')
    if digest((ROOT / 'build/rope_runner').read_bytes()) != normal_json['binary_sha256']:
        raise ValueError('The tested normal binary has changed')
    destination = args.output / digest(data)
    if destination.exists():
        existing, _ = validate_candidate(destination)
        if args.request and existing.get('tuning_request_id') != read_json(args.request)['request_id']:
            raise ValueError('Immutable candidate already exists without this tuning request; do not relabel its evidence')
        print(destination.resolve())
        return
    temporary = args.output / ('.' + digest(data) + '.staging')
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        evidence = temporary / 'evidence'
        evidence.mkdir()
        (temporary / 'kernel.asc').write_bytes(data)
        for source, name in ((args.review, 'compliance.json'), (ROOT / 'dist/manifest.json', 'package.json'),
                             (normal, 'correctness.json'), (audit, 'launch_audit.json'), (profile, 'launch_count.json')):
            shutil.copyfile(source, evidence / name)
        manifest = {'kernel_sha256': digest(data), 'git_commit': revision, 'staged_at': utcnow(),
                    'kernel_bytes': len(data), 'kernel_lines': len(data.splitlines()),
                    'evidence_sha256': {p.name: digest(p.read_bytes()) for p in evidence.iterdir()}}
        if args.request:
            request = read_json(args.request)
            if request.get('state') != 'ready_for_tuning' or not args.hypothesis:
                raise ValueError('A handoff response requires a ready request and an optimization hypothesis')
            if request['parent_kernel_sha256'] == digest(data):
                raise ValueError('Publish a new source hash in response to tuning feedback')
            manifest.update(tuning_request_id=request['request_id'],
                            parent_kernel_sha256=request['parent_kernel_sha256'],
                            optimization_hypothesis=args.hypothesis)
        write_json(temporary / 'candidate.json', manifest)
        validate_candidate(temporary)
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary)
        raise
    print(destination.resolve())


async def browser_command(args):
    from judge_workflow.browser import (browser_context, inspect, page_for, poll_result,
                                  replace_kernel, snapshot, validate_config, click_once, read_editor,
                                  platform_source_digest)
    config = read_json(args.config)
    if args.command == 'submit':
        validate_config(config)  # fail before opening or modifying any browser
        manifest, data = validate_candidate(args.candidate)
        journal = Journal(args.runs)
        if any(r['state'] not in ('accepted', 'rejected') for r in journal.records()):
            raise ValueError('An outstanding submission must be resumed first')
        if not args.repeat_source and any(r['kernel_sha256'] == manifest['kernel_sha256'] for r in journal.records()):
            raise ValueError('Exact source already submitted; do not duplicate it')
    async with browser_context(args) as context:
        if args.command == 'run':
            from judge_workflow.pipeline import run_once
            return await run_once(context, args, config, ROOT)
        elif args.command == 'preflight':
            validate_config(config)
            manifest, data = validate_candidate(args.candidate)
            page = await page_for(context, config['submit_url'])
            result = await replace_kernel(page, config, data)
            if await read_editor(page, config) != data:
                raise ValueError('Editor changed after preflight')
            await snapshot(page, args.output, 'preflight')
            write_json(args.output / 'preflight.json', result)
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        elif args.command == 'inspect':
            if args.url:
                check_origin(args.url, config['allowed_origin'])
                config = dict(config, submit_url=args.url)
            await inspect(context, config, args.output)
            print(args.output.resolve(), flush=True)
        elif args.command == 'login':
            if args.headless:
                raise ValueError('Interactive login requires a visible browser on a desktop')
            page = await page_for(context, config['submit_url'])
            print('请在打开的独立浏览器中手动登录，完成后按 Enter。密码和 Cookie 不会写入仓库。', flush=True)
            await asyncio.to_thread(input)
            page = await page_for(context, config['submit_url'])
            await page.get_by_role('link', name='退出', exact=True).wait_for(timeout=60000)
            print('已确认平台登录状态；请运行 inspect 检查编辑器并校准结果页。', flush=True)
        elif args.command == 'submit':
            page = await page_for(context, config['submit_url'])
            readback = await replace_kernel(page, config, data)
            await snapshot(page, args.runs / 'preflight', manifest['kernel_sha256'])
            # Verify again immediately before the one allowed submit click.
            if await read_editor(page, config) != data:
                raise ValueError('Editor changed after preflight')
            manifest = dict(manifest, platform_source_expected_sha256=platform_source_digest(data, config))
            record = await click_once(context, page, config, manifest, journal, allow_repeat=args.repeat_source)
            record['editor_readback'] = readback
            journal.save(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
            record = await poll_result(context, config, journal, record)
            print(json.dumps(record, ensure_ascii=False, indent=2), flush=True)
            from judge_workflow.pipeline import feedback
            feedback(journal, record, ROOT, publish=args.publish_feedback, notify_config=args.notify_config)
        elif args.command == 'resume':
            journal = Journal(args.runs)
            record = read_json(args.runs / args.run_id / 'run.json')
            if record['state'] in ('accepted', 'rejected') and not args.refresh:
                from judge_workflow.pipeline import feedback
                feedback(journal, record, ROOT, publish=args.publish_feedback, notify_config=args.notify_config)
                print(json.dumps(record, ensure_ascii=False, indent=2))
                return
            if args.result_url:
                check_origin(args.result_url, config['allowed_origin'])
                if record.get('result_url') and record['result_url'] != args.result_url:
                    raise ValueError('Cannot replace an already bound submission URL')
                record['result_url'] = args.result_url
                journal.save(record)
            saved_config = args.runs / args.run_id / 'browser_config.json'
            if saved_config.exists() and not args.refresh:
                config = dict(read_json(saved_config), poll_seconds=config['poll_seconds'],
                              result_timeout_seconds=config['result_timeout_seconds'])
            record = await poll_result(context, config, journal, record)
            print(json.dumps(record, ensure_ascii=False, indent=2), flush=True)
            from judge_workflow.pipeline import feedback
            feedback(journal, record, ROOT, publish=args.publish_feedback, notify_config=args.notify_config)


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest='command', required=True)
    audit = commands.add_parser('audit', help='Read-only compliance screen; nonzero if blocked')
    audit.add_argument('--source', type=Path, default=ROOT / 'operators/rotary_pos_emb/kernel.asc')
    audit.add_argument('--output', type=Path)
    stage_parser = commands.add_parser('stage', help='Freeze local validation evidence and the complete kernel')
    stage_parser.add_argument('--review', type=Path, required=True)
    stage_parser.add_argument('--request', type=Path, help='Mac feedback task this candidate responds to')
    stage_parser.add_argument('--hypothesis', help='Measured optimization hypothesis for this response')
    stage_parser.add_argument('--output', type=Path, default=ROOT / 'build/platform_candidates')
    publish = commands.add_parser('publish', help='Prepare a validated candidate for Git commit/push')
    publish.add_argument('--candidate', type=Path, required=True)
    sync = commands.add_parser('sync', help='Fetch a published candidate from GitHub without changing the checkout')
    sync.add_argument('--output', type=Path, default=ROOT / 'build/platform_candidates')
    sync.add_argument('--no-fetch', action='store_true', help='Read a locally available Git ref without network')
    sync.add_argument('--ref', default='origin/main', help='Used only with --no-fetch')
    export = commands.add_parser('export-result', help='Write a small platform result summary for Git sharing')
    export.add_argument('--run', type=Path, required=True)
    comparison = commands.add_parser('compare', help='Compare two accepted platform run.json records')
    comparison.add_argument('--baseline', type=Path, required=True)
    comparison.add_argument('--candidate', type=Path, required=True)
    comparison.add_argument('--output', type=Path, required=True)
    handoff = commands.add_parser('handoff', help='Prepare or publish feedback for the existing tuning session')
    handoff.add_argument('--run', type=Path, required=True)
    handoff.add_argument('--publish-feedback', action='store_true')
    handoff.add_argument('--notify-config', type=Path)
    incoming = commands.add_parser('inbox', help='Read Mac feedback via Git without modifying the checkout')
    incoming.add_argument('--after', help='Wait for a request newer than this completed ID')
    incoming.add_argument('--wait', action='store_true')
    incoming.add_argument('--interval', type=int, default=60)
    incoming.add_argument('--timeout', type=int, default=1800)
    for command in ('login', 'inspect', 'submit', 'resume', 'run', 'watch', 'preflight'):
        sub = commands.add_parser(command)
        sub.add_argument('--config', type=Path, default=ROOT / 'tools/judge_workflow/cannjudge.example.json')
        sub.add_argument('--cdp', help='Chrome debug endpoint reachable from this process, e.g. http://127.0.0.1:9222')
        sub.add_argument('--profile', type=Path, default=ROOT / '.local/cannjudge/browser')
        sub.add_argument('--headless', action='store_true')
        sub.add_argument('--channel', choices=('chrome', 'chromium'),
                         help='Launch installed Chrome directly; no CDP port or SSH tunnel needed')
        if command in ('submit', 'resume', 'run', 'watch'):
            sub.add_argument('--runs', type=Path, default=ROOT / 'benchmarks/platform/runs')
            sub.add_argument('--publish-feedback', action='store_true', help='Publish sanitized result and next-round request using an isolated Git clone')
            sub.add_argument('--notify-config', type=Path, help='Mac-local SSH host and fixed Codex thread UUID; notify only after publication')
        if command == 'submit':
            sub.add_argument('--candidate', type=Path, required=True)
            sub.add_argument('--repeat-source', action='store_true', help='Explicitly submit an already recorded source once; never bypasses an outstanding submission')
        elif command in ('run', 'watch'):
            sub.add_argument('--candidate', type=Path, help='Frozen validated directory; otherwise fetch GitHub latest')
            if command == 'watch':
                sub.add_argument('--interval', type=int, default=60)
                sub.add_argument('--idle-timeout', type=int, default=1800)
                sub.add_argument('--max-candidates', type=int, default=3)
        elif command == 'preflight':
            sub.add_argument('--candidate', type=Path, required=True)
            sub.add_argument('--output', type=Path, default=ROOT / '.local/cannjudge/preflight')
        elif command == 'resume':
            sub.add_argument('--run-id', required=True)
            sub.add_argument('--refresh', action='store_true', help='Re-read a completed result with the current configuration; never submit')
            sub.add_argument('--result-url', help='Reconcile a clicked-but-unbound submission by its real detail URL')
        elif command == 'inspect':
            sub.add_argument('--url', help='Read-only inspect a previous submission detail URL on the same origin')
            sub.add_argument('--output', type=Path, default=ROOT / '.local/cannjudge/inspection')
    return ap


def main():
    args = parser().parse_args()
    if args.command == 'audit':
        report = static_audit(args.source.read_bytes())
        if args.output:
            write_json(args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['static_screen_passed'] else 2
    if args.command == 'stage':
        stage(args)
    elif args.command == 'publish':
        print(publish_candidate(args.candidate))
    elif args.command == 'sync':
        destination, tip = sync_candidate(output=args.output, fetch=not args.no_fetch, ref=args.ref)
        print(json.dumps({'candidate': str(destination.resolve()), 'fetched_commit': tip}, indent=2))
    elif args.command == 'export-result':
        print(export_result(args.run))
    elif args.command == 'compare':
        write_json(args.output, compare_results(read_json(args.baseline), read_json(args.candidate)))
        print(args.output.resolve())
    elif args.command == 'handoff':
        from judge_workflow.pipeline import feedback
        record = read_json(args.run)
        journal = Journal(args.run.resolve().parent.parent)
        with exclusive_lock(journal.root / '.workflow.lock'):
            feedback(journal, record, ROOT, publish=args.publish_feedback, notify_config=args.notify_config)
    elif args.command == 'inbox':
        from judge_workflow.handoff import inbox
        path = inbox(ROOT, after=args.after, wait=args.wait, interval=args.interval, timeout=args.timeout)
        print(path.resolve() if path else 'No new feedback request')
    elif args.command == 'watch':
        if args.interval < 15 or args.idle_timeout < args.interval or not 1 <= args.max_candidates <= 100:
            raise ValueError('watch needs interval >=15, idle-timeout >=interval, max-candidates 1..100')
        args.command = 'run'
        seen = set()
        idle_since = time.monotonic()
        notify_config = args.notify_config
        args.expected_request_id = None
        controller = ROOT / '.local/cannjudge/controller.json'
        write_json(controller, {'pid': os.getpid(), 'state': 'running', 'started_at': utcnow(),
                                'max_candidates': args.max_candidates})
        while time.monotonic() - idle_since < args.idle_timeout:
            # The final result is published, but must not start an extra round.
            args.notify_config = notify_config if len(seen) < args.max_candidates - 1 else None
            with exclusive_lock(args.runs / '.workflow.lock'):
                record = asyncio.run(browser_command(args))
            args.expected_request_id = record['run_id'] if notify_config else None
            if record['kernel_sha256'] not in seen:
                seen.add(record['kernel_sha256'])
                idle_since = time.monotonic()
                if len(seen) >= args.max_candidates:
                    break
            from judge_workflow.handoff import tuning_response
            response = tuning_response(ROOT, record['run_id'])
            write_json(controller, {'pid': os.getpid(), 'state': 'waiting_for_candidate',
                                    'last_run_id': record['run_id'], 'processed_shas': sorted(seen),
                                    'updated_at': utcnow(), 'max_candidates': args.max_candidates})
            if response:
                write_json(controller, {'pid': os.getpid(), 'state': 'remote_stopped', 'response': response, 'updated_at': utcnow()})
                print(json.dumps(response, ensure_ascii=False), flush=True)
                return 0
            print('Waiting for a new validated candidate from GitHub...', flush=True)
            time.sleep(args.interval)
        write_json(controller, {'pid': os.getpid(), 'state': 'finished', 'processed_shas': sorted(seen), 'updated_at': utcnow()})
        print(f'Watcher finished after {len(seen)} distinct candidate(s)', flush=True)
    elif args.command in ('submit', 'resume', 'run', 'preflight'):
        with exclusive_lock((args.runs if hasattr(args, 'runs') else ROOT / 'benchmarks/platform/runs') / '.workflow.lock'):
            asyncio.run(browser_command(args))
    else:
        asyncio.run(browser_command(args))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print('工作流停止：' + str(error), file=sys.stderr)
        sys.exit(2)
