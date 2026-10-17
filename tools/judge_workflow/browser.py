"""Browser UI adapter. No private judge endpoints or authenticated request dumps."""
import asyncio
from asyncio import sleep as poll_sleep
from contextlib import asynccontextmanager
import re
import math
import time
import uuid
from urllib.parse import urljoin, urlparse

from .core import check_origin, digest, latency_us, utcnow, write_json
from .discovery import structure_report
from .editor import read_kernel, verify_kernel, replace_kernel as replace_configured_kernel


MODELS = """() => {
    if (!globalThis.monaco?.editor?.getModels) return null;
    return monaco.editor.getModels().map(m => ({uri: m.uri.toString(), text: m.getValue()}));
}"""


@asynccontextmanager
async def browser_context(args):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        if args.cdp:
            browser = await p.chromium.connect_over_cdp(args.cdp, timeout=15000)
            if not browser.contexts:
                raise ValueError('Connected Chrome has no default browser context')
            # Do not close the user's browser. The transport disconnects when
            # Playwright stops. No cookies/storage state are exported.
            yield browser.contexts[0]
        else:
            args.profile.mkdir(parents=True, exist_ok=True, mode=0o700)
            context = await p.chromium.launch_persistent_context(
                str(args.profile.resolve()), headless=args.headless,
                channel=getattr(args, 'channel', None))
            try:
                yield context
            finally:
                await context.close()


async def page_for(context, url):
    for page in context.pages:
        if page.url == url:
            return page
    page = await context.new_page()
    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
    return page


async def snapshot(page, directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    # Page-visible information only. Never save request headers, cookies,
    # localStorage or the whole authenticated network trace.
    text = await page.locator('body').inner_text(timeout=15000)
    (directory / (name + '.txt')).write_text(text)
    await page.screenshot(path=str(directory / (name + '.png')), full_page=True, timeout=15000)


async def inspect(context, config, output):
    page = await page_for(context, config['submit_url'])
    await page.wait_for_function(
        """() => {
            const text = document.body?.innerText.trim();
            return !!text && !/^(加载中[.…]*|Loading[.…]*)$/i.test(text);
        }""", timeout=60000)
    await page.wait_for_function(
        "() => !document.body.innerText.includes('正在加载代码编辑器')", timeout=60000)
    await snapshot(page, output, 'inspect')
    structure = await structure_report(page)
    write_json(output / 'structure.json', structure)
    models = await page.evaluate(MODELS)
    links = await page.locator('a[href]').evaluate_all(
        '(nodes) => nodes.map(n => ({text:n.innerText,href:n.href}))')
    buttons = await page.get_by_role('button').all_text_contents()
    write_json(output / 'inspect.json', {
        'url': page.url, 'captured_at': utcnow(), 'buttons': buttons, 'links': links,
        'models': None if models is None else [
            {'uri': m['uri'], 'bytes': len(m['text'].encode()), 'lines': len(m['text'].splitlines()),
             'sha256': digest(m['text'].encode())} for m in models],
        'note': 'Read-only discovery. Calibrate result selectors against an actual submission detail page.'})
    if config.get('result_status_selector'):
        status = page.locator(config['result_status_selector'])
        if await status.count() == 1 and (await status.inner_text()).strip() in config['failure_statuses']:
            await capture_diagnostics(page, config, output)
    return structure


def validate_config(config):
    if config.get('calibrated') is not True:
        raise ValueError('Live selectors are not calibrated; run inspect before enabling submission')
    fields = ['submit_url', 'allowed_origin', 'submit_button_name', 'result_link_selector', 'result_url_pattern']
    adapter = config.get('result_adapter', 'selectors')
    if adapter == 'cannjudge-table':
        fields += ['result_metadata_selector', 'result_table_selector']
    elif adapter == 'selectors':
        fields += ['result_id_selector', 'result_status_selector', 'case_row_selector',
                   'case_id_selector', 'case_latency_selector', 'case_status_selector']
    else:
        raise ValueError('Unknown result_adapter: ' + str(adapter))
    for key in fields:
        if not config.get(key):
            raise ValueError('Missing calibrated browser field: ' + key)
    check_origin(config['submit_url'], config['allowed_origin'])
    if config.get('expected_cases') != 15:
        raise ValueError('RotaryPosEmb expects exactly 15 cases')
    if not 5 <= config['poll_seconds'] <= 60 or not 30 <= config['result_timeout_seconds'] <= 1800:
        raise ValueError('Use a 5..60 second poll and a bounded 30..1800 second wait')
    re.compile(config['result_url_pattern'])
    if config.get('result_identity') == 'source_and_url':
        for key in ('result_id_pattern', 'result_kernel_tab_selector', 'result_code_selector'):
            if not config.get(key):
                raise ValueError('Missing source-bound result field: ' + key)
    if config.get('editor_adapter') == 'keyboard':
        for key in ('editor_selector', 'editor_copy_selector', 'editor_file_selector'):
            if not config.get(key):
                raise ValueError('Missing keyboard editor field: ' + key)
    if config.get('require_official_score'):
        for key in ('ranking_url', 'ranking_search_selector', 'ranking_row_selector',
                    'result_submitter_selector', 'result_time_selector'):
            if not config.get(key):
                raise ValueError('Missing official score field: ' + key)
        check_origin(config['ranking_url'], config['allowed_origin'])


async def models_ready(page):
    await page.wait_for_function('() => !!globalThis.monaco?.editor?.getModels', timeout=15000)
    models = await page.evaluate(MODELS)
    if not models:
        raise ValueError('No Monaco models: login or editor API connection is missing')
    return models


def kernel_model(models, config):
    explicit = config.get('kernel_model_uri')
    matches = [m for m in models if m['uri'] == explicit] if explicit else [
        m for m in models if urlparse(m['uri']).path.rsplit('/', 1)[-1] == 'kernel.asc']
    if len(matches) != 1:
        raise ValueError('Cannot uniquely identify kernel.asc model; inspect and calibrate its URI')
    return matches[0]


async def replace_kernel(page, config, data):
    if config.get('editor_adapter') == 'keyboard':
        return await replace_keyboard_kernel(page, config, data)
    if 'editor_mode' in config:
        return await replace_configured_kernel(page, config, data)
    before = await models_ready(page)
    target = kernel_model(before, config)
    text = data.decode('utf-8')
    await page.evaluate('''({uri,text}) => {
        const m=monaco.editor.getModels().find(m=>m.uri.toString()===uri);
        if(!m) throw new Error('kernel model disappeared');
        m.setValue(text);
    }''', {'uri': target['uri'], 'text': text})
    after = await page.evaluate(MODELS)
    readback = kernel_model(after, config)['text'].encode('utf-8')
    if readback != data:
        raise ValueError('Editor readback differs from the complete candidate; submission blocked')
    untouched_before = {m['uri']: m['text'] for m in before if m['uri'] != target['uri']}
    untouched_after = {m['uri']: m['text'] for m in after if m['uri'] != target['uri']}
    if untouched_before != untouched_after:
        raise ValueError('A non-kernel editor model changed; submission blocked')
    return {'kernel_model_uri': target['uri'], 'readback_sha256': digest(readback),
            'bytes': len(readback), 'lines': len(text.splitlines()),
            'first_line': text.splitlines()[0], 'last_line': text.splitlines()[-1],
            'unchanged_models': list(untouched_before)}


async def keyboard_editor(page, config):
    check_origin(page.url, config['allowed_origin'])
    await page.get_by_role('link', name='退出', exact=True).wait_for(timeout=60000)
    editor = page.locator(config['editor_selector'])
    await editor.wait_for(state='visible', timeout=60000)
    files = await page.locator(config['editor_file_selector']).evaluate_all(
        "els=>els.map(e=>({file:e.dataset.file,readonly:e.classList.contains('is-readonly'),active:e.classList.contains('active')}))")
    # Desktop and compact explorers both render the same file tree in the DOM.
    unique = {}
    for file in files:
        if file['file'] in unique and unique[file['file']] != file:
            raise ValueError('Conflicting file permissions between editor explorers')
        unique[file['file']] = file
    files = list(unique.values())
    writable = [f for f in files if not f['readonly']]
    if len(writable) != 1 or writable[0]['file'] != 'kernel.asc' or not writable[0]['active']:
        raise ValueError('Expected kernel.asc to be the only writable and active file: ' + repr(files))
    if await editor.count() != 1:
        raise ValueError('Expected exactly one kernel editor')
    await page.context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=config['allowed_origin'])
    await page.bring_to_front()
    return editor, files


async def clipboard_text(page):
    return await page.evaluate('navigator.clipboard.readText()')


async def copy_editor(page, config):
    # A sentinel prevents reading a stale clipboard if the site's copy failed.
    sentinel = 'cannjudge-readback-' + uuid.uuid4().hex
    await page.evaluate('(text)=>navigator.clipboard.writeText(text)', sentinel)
    await page.locator(config['editor_copy_selector']).click()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        text = await clipboard_text(page)
        if text != sentinel:
            return text.encode('utf-8')
        await asyncio.sleep(.1)
    raise ValueError('Editor copy did not produce a fresh full-source readback')


async def read_editor(page, config):
    if config.get('editor_adapter') != 'keyboard':
        if 'editor_mode' in config:
            return await read_kernel(page, config)
        return kernel_model(await models_ready(page), config)['text'].encode('utf-8')
    await keyboard_editor(page, config)
    previous = await clipboard_text(page)
    try:
        return await copy_editor(page, config)
    finally:
        await page.evaluate('(text)=>navigator.clipboard.writeText(text)', previous)


async def replace_keyboard_kernel(page, config, data):
    editor, files = await keyboard_editor(page, config)
    text = data.decode('utf-8')
    previous = await clipboard_text(page)
    try:
        await page.evaluate('(text)=>navigator.clipboard.writeText(text)', text)
        await editor.focus()
        await editor.press('ControlOrMeta+a')
        await editor.press('ControlOrMeta+v')
        if await copy_editor(page, config) != data:
            raise ValueError('Full-source clipboard readback differs; submission blocked')
        _, after = await keyboard_editor(page, config)
        if files != after:
            raise ValueError('Editor file permissions or active file changed')
    finally:
        await page.evaluate('(text)=>navigator.clipboard.writeText(text)', previous)
    return {'adapter': 'keyboard', 'readback_sha256': digest(data), 'bytes': len(data),
            'lines': len(text.splitlines()), 'readonly_files': [f['file'] for f in files if f['readonly']]}


def platform_source_digest(data, config):
    # The live submission view removes the final LF. No interior whitespace,
    # CRLF, indentation or other source differences are normalized.
    return digest(data.rstrip(b'\n') if config.get('result_source_final_newline') else data)


async def result_source(page, config):
    await page.locator(config['result_kernel_tab_selector']).click(timeout=60000)
    code = page.locator(config['result_code_selector'])
    await code.wait_for(timeout=60000)
    return (await code.text_content()).encode('utf-8')


async def existing_result(context, config, data, limit=10):
    if not config.get('history_url') or not config.get('result_code_selector'):
        return None
    history = await page_for(context, config['history_url'])
    await history.get_by_role('link', name='退出', exact=True).wait_for(timeout=60000)
    await history.locator('text=我的提交记录').wait_for(timeout=60000)
    links = await visible_links(history, config)
    # Preserve the history's newest-first DOM order.
    ordered = await history.locator(config['result_link_selector']).evaluate_all('(els)=>els.map(e=>e.href)')
    for url in list(dict.fromkeys(ordered))[:limit]:
        if url not in links:
            continue
        page = await page_for(context, url)
        source = await result_source(page, config)
        if platform_source_digest(source, config) == platform_source_digest(data, config):
            return url
        await page.close()
    return None


async def visible_links(page, config):
    links = []
    locator = page.locator(config['result_link_selector'])
    for item in await locator.all():
        if not await item.is_visible():
            continue
        href = await item.get_attribute('href')
        if href:
            url = urljoin(page.url, href)
            check_origin(url, config['allowed_origin'])
            if re.search(config['result_url_pattern'], url):
                links.append(url)
    return set(links)


async def click_once(context, page, config, candidate, journal, allow_repeat=False):
    validate_config(config)
    check_origin(page.url, config['allowed_origin'])
    before_links = await visible_links(page, config)
    old_pages = set(context.pages)
    submit = page.get_by_role('button', name=config['submit_button_name'], exact=True)
    if await submit.count() != 1 or not await submit.is_enabled():
        raise ValueError('Cannot uniquely identify an enabled submit button')
    # Intent is durable before the only write. Any subsequent failure is
    # ambiguous and stays blocked; click is never retried in this workflow.
    record = journal.create(candidate, config, allow_repeat=allow_repeat)
    if candidate.get('platform_source_expected_sha256'):
        record['platform_source_expected_sha256'] = candidate['platform_source_expected_sha256']
        journal.save(record)
    directory = journal.root / record['run_id']
    write_json(directory / 'browser_config.json', config)
    try:
        await submit.click(timeout=15000, no_wait_after=True)
        record['state'] = 'awaiting_result_link'
        journal.save(record)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            urls = set()
            pages = [page] + [p for p in context.pages if p not in old_pages]
            for current in pages:
                if current.url == 'about:blank':
                    continue
                check_origin(current.url, config['allowed_origin'])
                if re.search(config['result_url_pattern'], current.url) and current.url != config['submit_url']:
                    urls.add(current.url)
                urls.update(await visible_links(current, config) - before_links)
            if len(urls) > 1:
                raise ValueError('Multiple new submission URLs: refuse ambiguous result binding')
            if len(urls) == 1:
                record['result_url'] = next(iter(urls))
                record['state'] = 'pending'
                journal.save(record)
                return record
            await asyncio.sleep(1)
        raise TimeoutError('Submission clicked but no unique new result URL was observed; do not re-submit')
    except Exception as error:
        record['last_error'] = str(error)
        journal.save(record)
        try:
            await snapshot(page, directory, 'submit_uncertain')
        except Exception:
            pass
        raise


async def unique_text(page, selector):
    locator = page.locator(selector)
    await locator.first.wait_for(state='visible', timeout=15000)
    if await locator.count() != 1:
        raise ValueError('Expected exactly one element for ' + selector)
    return (await locator.inner_text()).strip()


async def capture_diagnostics(page, config, directory):
    """Capture visible judge errors, including a status-triggered details dialog."""
    directory.mkdir(parents=True, exist_ok=True)
    message = ''
    selector = config.get('log_selector')
    if selector:
        log = page.locator(selector)
        if await log.count() == 1:
            message = (await log.text_content()).strip()
            if not message:
                try:
                    await page.locator(config['result_status_selector']).click(timeout=5000)
                    await page.wait_for_function(
                        'selector=>!!document.querySelector(selector)?.textContent.trim()',
                        arg=selector, timeout=15000)
                except Exception:
                    pass
                message = (await log.text_content()).strip()
    if not message:
        message = await page.locator('body').inner_text()
    locations = []
    for match in re.finditer(r'(?P<file>[\w./\\-]+\.(?:asc|cpp|cc|c|h|hpp)):(?P<line>\d+)(?::(?P<column>\d+))?', message):
        location = {'file': match['file'], 'line': int(match['line'])}
        if match['column']:
            location['column'] = int(match['column'])
        if location not in locations:
            locations.append(location)
    report = {'message': message, 'locations': locations, 'captured_at': utcnow()}
    write_json(directory / 'diagnostics.json', report)
    (directory / 'compiler_or_runtime_log.txt').write_text(message)
    await snapshot(page, directory, 'diagnostics')
    return report


async def read_result(page, config, record):
    if config.get('result_adapter') == 'cannjudge-table' and config.get('result_identity') != 'source_and_url':
        from .site import read_cannjudge_result
        return await read_cannjudge_result(page, config, record)
    # The result page must display the record ID that the URL identifies.
    submission_id = await unique_text(page, config['result_id_selector'])
    if config.get('result_id_pattern'):
        match = re.fullmatch(config['result_id_pattern'], submission_id)
        if not match:
            raise ValueError('Unrecognized displayed submission ID')
        submission_id = match[1]
    source_bound = config.get('result_identity') == 'source_and_url'
    if source_bound:
        check_origin(page.url, config['allowed_origin'])
        if page.url != record.get('result_url') or not re.search(config['result_url_pattern'], page.url):
            raise ValueError('Result URL changed')
        expected = record.get('platform_source_expected_sha256')
        if not expected:
            raise ValueError('Missing candidate source identity for the opaque result URL')
        actual = platform_source_digest(await result_source(page, config), config)
        if actual != expected:
            raise ValueError('Platform submission source differs from the verified candidate')
        record['platform_source_sha256'] = actual
    elif not submission_id or not re.search(r'(?<![\w-])' + re.escape(submission_id) + r'(?![\w-])', page.url):
        raise ValueError('Visible submission ID does not match the bound result URL')
    if record.get('submission_id') and record['submission_id'] != submission_id:
        raise ValueError('Result page switched to another submission')
    record['submission_id'] = submission_id
    if config.get('result_submitter_selector'):
        value = await unique_text(page, config['result_submitter_selector'])
        record['platform_submitter'] = re.sub(r'^提交人[：:]\s*', '', value)
        value = await unique_text(page, config['result_time_selector'])
        record['platform_submission_time'] = re.sub(r'^提交时间[：:]\s*', '', value)
    status = await unique_text(page, config['result_status_selector'])
    record['platform_status'] = status
    if config.get('score_selector'):
        record['platform_score_raw'] = await unique_text(page, config['score_selector'])
    if status in config['failure_statuses']:
        return {'state': 'rejected', 'cases': []}
    if status not in config['success_statuses']:
        # Unknown status is pending/uncertain, never inferred as success.
        return {'state': 'pending', 'cases': []}
    cases = []
    rows = await page.locator(config['case_row_selector']).all()
    if config.get('allow_partial_results') and len(rows) < config['expected_cases']:
        return {'state': 'pending', 'cases': [], 'waiting_for': 'all_case_rows'}
    for row in rows:
        case_id = (await row.locator(config['case_id_selector']).inner_text()).strip()
        match = re.fullmatch(r'(?:测试点\s*)?(\d+)', case_id)
        if not match:
            raise ValueError('Unrecognized case ID: ' + case_id)
        status = (await row.locator(config['case_status_selector']).inner_text()).strip()
        if config.get('allow_partial_results') and status in config.get('case_pending_statuses', []):
            return {'state': 'pending', 'cases': [], 'waiting_for': 'case_evaluation'}
        if status not in config['case_success_statuses']:
            raise ValueError('Overall success disagrees with per-case precision/status: ' + status)
        raw = (await row.locator(config['case_latency_selector']).inner_text()).strip()
        if config.get('allow_partial_results') and raw in ('', '-', '--'):
            return {'state': 'pending', 'cases': [], 'waiting_for': 'case_timings'}
        case = {'id': int(match[1]), 'latency_us': latency_us(raw), 'raw_latency': raw, 'status': status}
        if config.get('case_error_selector'):
            error = (await row.locator(config['case_error_selector']).inner_text()).strip()
            if not re.fullmatch(r'\d+(?:\.\d+)?\s*%', error):
                raise ValueError('Unrecognized output error percentage: ' + error)
            percent = float(error.rstrip('%').strip())
            if not 0 <= percent <= config.get('case_max_error_percent', 100):
                raise ValueError('Pass status disagrees with the allowed output error percentage: ' + error)
            case['output_error_percent'] = percent
        if config.get('case_best_latency_selector'):
            best = (await row.locator(config['case_best_latency_selector']).inner_text()).strip()
            if config.get('allow_partial_results') and best in ('', '-', '--'):
                return {'state': 'pending', 'cases': [], 'waiting_for': 'best_timings'}
            case['best_latency_us'] = latency_us(best)
            case['ratio_to_best'] = case['latency_us'] / case['best_latency_us']
        cases.append(case)
    if len(cases) != 15 or {c['id'] for c in cases} != set(range(1, 16)):
        raise ValueError('Success needs exactly 15 unique case results')
    result = {'state': 'accepted', 'cases': sorted(cases, key=lambda c: c['id'])}
    if all('best_latency_us' in c for c in cases):
        denominators = [1 + math.log(c['ratio_to_best'], 1.5) for c in cases]
        if all(d > 0 for d in denominators):
            result['displayed_timings_score'] = sum(100 / d for d in denominators) / len(cases)
            result['score_note'] = 'Estimate from rounded displayed timings and current best times; not an official raw score'
    return result


async def official_score(context, config, record, directory):
    """Bind a displayed leaderboard score to this submitter, time and all 15 timings."""
    if not config.get('ranking_url') or not record.get('platform_submitter'):
        return False
    check_origin(config['ranking_url'], config['allowed_origin'])
    page = await context.new_page()
    try:
        await page.goto(config['ranking_url'], wait_until='domcontentloaded', timeout=30000)
        search = page.locator(config['ranking_search_selector'])
        await search.wait_for(timeout=60000)
        leaders = []
        await page.locator(config['ranking_row_selector']).first.wait_for(timeout=15000)
        for row in (await page.locator(config['ranking_row_selector']).all())[:5]:
            cells = [t.strip() for t in await row.locator('td').all_text_contents()]
            if len(cells) != 21 or cells[3] not in config['success_statuses']:
                continue
            rank = re.match(r'\d+', cells[0])
            if not rank:
                continue
            leaders.append({'rank': int(rank[0]), 'team': cells[1], 'score_raw': cells[4],
                            'cases': [{'id': i, 'latency_us': latency_us(raw),
                                       'speedup_needed': record['cases'][i-1]['latency_us'] / latency_us(raw)}
                                      for i, raw in enumerate(cells[6:], 1)]})
        await search.fill(record['platform_submitter'])
        await page.get_by_role('button', name='搜索', exact=True).click()
        await page.get_by_role('button', name='清除', exact=True).wait_for(timeout=15000)
        rows = await page.locator(config['ranking_row_selector']).all()
        for row in rows:
            cells = [t.strip() for t in await row.locator('td').all_text_contents()]
            if len(cells) != 21 or cells[2] != record['platform_submitter'] or cells[5] != record['platform_submission_time']:
                continue
            if cells[3] not in config['success_statuses']:
                continue
            if any(latency_us(raw) != case['latency_us'] for raw, case in zip(cells[6:], record['cases'])):
                continue
            if not re.fullmatch(r'\d+(?:\.\d+)?', cells[4]):
                continue
            record['platform_score_raw'] = cells[4]
            rank = re.match(r'\d+', cells[0])
            if rank:
                record['platform_rank'] = int(rank[0])
            record['score_binding'] = 'submitter + exact submission time + all 15 displayed timings'
            write_json(directory / 'leaderboard.json', {
                'captured_at': utcnow(), 'rank': record.get('platform_rank'),
                'score_raw': cells[4], 'leaders': leaders,
                'priority_cases': sorted(record['cases'], key=lambda c: c.get('ratio_to_best', 0), reverse=True),
                'note': 'Public leaderboard snapshot. Case IDs do not identify hidden input shapes.'})
            await snapshot(page, directory, 'score')
            return True
        return False
    finally:
        await page.close()


async def capture_problem_context(context, config, directory):
    if not config.get('history_url'):
        return
    check_origin(config['history_url'], config['allowed_origin'])
    page = await context.new_page()
    try:
        await page.goto(config['history_url'], wait_until='domcontentloaded', timeout=30000)
        await page.get_by_text('四、规则要求', exact=True).wait_for(timeout=60000)
        text = await page.locator('body').inner_text()
        def section(start, end):
            if start not in text:
                return None
            value = text.split(start, 1)[1]
            return value.split(end, 1)[0].strip()
        def field(label):
            match = re.search(re.escape(label) + r'\s*([^\n]+)', text)
            return match[1] if match else None
        report = {'captured_at': utcnow(), 'source_url': config['history_url'],
                  'start': field('题目开始：'), 'deadline': field('题目结束：'),
                  'constraints': section('3.4 关键输入约束', '3.5 核心属性说明'),
                  'rules': section('四、规则要求', '五、精度判断规则'),
                  'precision': section('五、精度判断规则', '六、得分规则'),
                  'scoring': section('六、得分规则', '七、示例说明')}
        write_json(directory / 'problem-context.json', report)
        statement = text.split('描述', 1)[-1].split('我的提交记录', 1)[0]
        (directory / 'problem-statement.txt').write_text(statement)
    finally:
        await page.close()


async def poll_result(context, config, journal, record):
    validate_config(config)
    if not record.get('result_url'):
        raise ValueError('Missing result URL: reconcile the clicked submission before resume')
    check_origin(record['result_url'], config['allowed_origin'])
    if not re.search(config['result_url_pattern'], record['result_url']):
        raise ValueError('Result URL does not match the calibrated submission-detail pattern')
    page = await page_for(context, record['result_url'])
    directory = journal.root / record['run_id']
    deadline = time.monotonic() + config['result_timeout_seconds']
    while time.monotonic() < deadline:
        if page.url != record['result_url']:
            raise ValueError('Result navigation changed: login or page calibration may be required')
        try:
            result = await read_result(page, config, record)
            record.pop('waiting_for', None)
            record.update(result)
            if record['state'] == 'accepted' and config.get('ranking_url'):
                has_score = await official_score(context, config, record, directory)
                if not has_score and config.get('require_official_score') and not record.get('reused_history'):
                    record.update(state='pending', waiting_for='official_score')
            record.pop('last_error', None)
        except Exception as error:
            record['last_error'] = str(error)
            journal.save(record)
            await snapshot(page, directory, 'result_parse_error')
            raise
        journal.save(record)
        print(f"{record['run_id']}: {record.get('platform_status', '')} / {record['state']}"
              f" {record.get('waiting_for', '')}", flush=True)
        if record['state'] in ('accepted', 'rejected'):
            await snapshot(page, directory, 'result')
            if record['state'] == 'rejected':
                await capture_diagnostics(page, config, directory)
                record['diagnostics_file'] = str((directory / 'diagnostics.json').resolve())
                journal.save(record)
            elif config.get('log_selector'):
                log = page.locator(config['log_selector'])
                if await log.count() == 1:
                    (directory / 'compiler_or_runtime_log.txt').write_text(await log.text_content())
            try:
                await capture_problem_context(context, config, directory)
            except Exception as error:
                record['context_error'] = str(error)
                journal.save(record)
            return record
        await poll_sleep(config['poll_seconds'])
        await page.reload(wait_until='domcontentloaded', timeout=30000)
    record['last_error'] = 'Timed out waiting for this result; resume reads the same submission without clicking'
    journal.save(record)
    await snapshot(page, directory, 'pending_timeout')
    raise TimeoutError(record['last_error'])
