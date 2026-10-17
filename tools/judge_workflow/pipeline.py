"""Mac-only candidate -> browser -> durable performance feedback pipeline."""
import csv
import copy
import json
import re
from pathlib import Path

from .browser import (browser_context, click_once, existing_result, page_for, platform_source_digest,
                      poll_result, read_editor, replace_kernel, snapshot, validate_config)
from .core import Journal, TERMINAL, compare_results, read_json, utcnow, validate_candidate, write_json
from .repository import export_result, sync_candidate


def feedback(journal, record, repository, publish=False, notify_config=None, target_score=None):
    """Machine-readable feedback is the interface to the next tuning round."""
    directory = journal.root / record['run_id']
    exported = export_result(directory / 'run.json', repository=repository)
    report = {'schema_version': 1, 'run_id': record['run_id'], 'state': record['state'],
              'kernel_sha256': record['kernel_sha256'], 'submission_id': record['submission_id'],
              'platform_status': record.get('platform_status'), 'created_at': utcnow(),
              'export': str(exported.resolve()), 'cases': record.get('cases', [])}
    for key in ('platform_score_raw', 'platform_rank', 'displayed_timings_score', 'score_note'):
        if key in record:
            report[key] = record[key]
    for name in ('leaderboard', 'problem-context'):
        path = directory / (name + '.json')
        if path.exists():
            report[name.replace('-', '_')] = read_json(path)
    accepted = [r for r in journal.records() if r['state'] == 'accepted' and
                r['run_id'] != record['run_id'] and r['kernel_sha256'] != record['kernel_sha256']]
    if record['state'] == 'accepted':
        if accepted:
            baseline = max(accepted, key=lambda r: r['created_at'])
            report['comparison'] = compare_results(baseline, record)
            report['baseline_run_id'] = baseline['run_id']
        report['slowest_relative_to_best'] = sorted(
            [c for c in record['cases'] if 'ratio_to_best' in c],
            key=lambda c: c['ratio_to_best'], reverse=True)
        report['next_action'] = 'Use timings and local profiling to validate a new source candidate'
    else:
        report['next_action'] = 'Fix compilation/correctness before evaluating performance'
        diagnostics = directory / 'diagnostics.json'
        if diagnostics.exists():
            report['diagnostics'] = read_json(diagnostics)
    from .handoff import create_request, publish_feedback
    request = create_request(record, report, repository)
    report['handoff_request'] = str(request.resolve())
    receipt = directory / 'feedback-published.json'
    if publish and not receipt.exists():
        revision = publish_feedback(request, repository)
        write_json(receipt, {'request_id': record['run_id'], 'git_commit': revision, 'published_at': utcnow()})
    if receipt.exists():
        report['publication'] = read_json(receipt)
    target_reached = (target_score is not None and record['state'] == 'accepted' and
                      record.get('platform_score_raw') is not None and float(record['platform_score_raw']) >= target_score)
    report['target_reached'] = target_reached
    if notify_config and not target_reached:
        if not receipt.exists():
            raise ValueError('Publish feedback before notifying the remote session')
        from .notify import notify_remote
        report['notification'] = notify_remote(record, read_json(request), read_json(receipt), notify_config, directory)
    write_json(directory / 'feedback.json', report)
    write_json(journal.root / 'latest-feedback.json', report)
    columns = ('id', 'status', 'latency_us', 'best_latency_us', 'ratio_to_best', 'output_error_percent')
    with (directory / 'cases.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(record.get('cases', []))
    print(json.dumps({'run_id': record['run_id'], 'state': record['state'],
                      'feedback': str((directory / 'feedback.json').resolve()),
                      'result': str(exported.resolve())}, ensure_ascii=False), flush=True)
    return report


async def run_once(context, args, config, repository):
    validate_config(config)
    journal = Journal(args.runs)
    outstanding = [r for r in journal.records() if r['state'] not in TERMINAL]
    if outstanding:
        if len(outstanding) != 1:
            raise ValueError('Multiple outstanding submissions; reconcile their records first')
        record = outstanding[0]
        if not record.get('result_url'):
            raise ValueError('An uncertain click needs resume --result-url after checking history; no new click allowed')
        if context is None:
            async with browser_context(args) as opened:
                return await run_once(opened, args, config, repository)
        saved = journal.root / record['run_id'] / 'browser_config.json'
        poll_config = dict(read_json(saved), poll_seconds=config['poll_seconds'],
                           result_timeout_seconds=config['result_timeout_seconds']) if saved.exists() else config
        record = await poll_result(context, poll_config, journal, record)
        feedback(journal, record, repository, publish=getattr(args, 'publish_feedback', False), notify_config=getattr(args, 'notify_config', None), target_score=getattr(args, 'target_score', None))
        return record
    if args.candidate:
        candidate = Path(args.candidate)
    else:
        candidate, _ = sync_candidate(repository=repository)
    manifest, data = validate_candidate(candidate)
    matches = [r for r in journal.records() if r['kernel_sha256'] == manifest['kernel_sha256']]
    if matches:
        record = matches[-1]
        feedback(journal, record, repository, publish=getattr(args, 'publish_feedback', False), notify_config=getattr(args, 'notify_config', None), target_score=getattr(args, 'target_score', None))
        return record
    expected = getattr(args, 'expected_request_id', None)
    if expected:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', expected):
            raise ValueError('Invalid coordinator request ID')
        parents = [r for r in journal.records() if r['run_id'] == expected]
        if not parents:
            try:
                task = read_json(Path(repository) / 'tuning_requests/rotary_pos_emb' / (expected + '.json'))
            except (OSError, ValueError) as error:
                raise ValueError('Missing coordinator continuation request') from error
            if task.get('request_id') != expected:
                raise ValueError('Continuation request identity differs')
            parents = [r for r in journal.records() if r['run_id'] == task.get('baseline_run_id') and
                       r['kernel_sha256'] == task.get('parent_kernel_sha256')]
        if len(parents) != 1 or manifest.get('tuning_request_id') != expected or manifest.get('parent_kernel_sha256') != parents[0]['kernel_sha256']:
            raise ValueError('New candidate does not respond to the coordinator current request and parent source')
    if context is None:
        prepared = copy.copy(args)
        prepared.candidate = candidate
        async with browser_context(args) as opened:
            return await run_once(opened, prepared, config, repository)
    manifest = dict(manifest, platform_source_expected_sha256=platform_source_digest(data, config))
    url = await existing_result(context, config, data)
    if url:
        record = journal.create(manifest, config)
        record.update(state='pending', result_url=url, reused_history=True,
                      platform_source_expected_sha256=manifest['platform_source_expected_sha256'])
        journal.save(record)
        write_json(journal.root / record['run_id'] / 'browser_config.json', config)
        print('Found identical source in platform history; collecting its result without another submission', flush=True)
    else:
        page = await page_for(context, config['submit_url'])
        readback = await replace_kernel(page, config, data)
        await snapshot(page, args.runs / 'preflight', manifest['kernel_sha256'])
        if await read_editor(page, config) != data:
            raise ValueError('Editor changed after preflight')
        record = await click_once(context, page, config, manifest, journal)
        record['editor_readback'] = readback
        journal.save(record)
    record = await poll_result(context, config, journal, record)
    feedback(journal, record, repository, publish=getattr(args, 'publish_feedback', False), notify_config=getattr(args, 'notify_config', None), target_score=getattr(args, 'target_score', None))
    return record
