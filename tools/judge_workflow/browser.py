"""Browser UI adapter. No private judge endpoints or authenticated request dumps."""
import asyncio
from contextlib import asynccontextmanager
import re
import time
from urllib.parse import urljoin

from .core import check_origin, digest, latency_us, utcnow, write_json
from .discovery import structure_report
from .editor import MODELS, kernel_model, models_ready, read_kernel, replace_kernel, verify_kernel


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
    models = await page.evaluate(MODELS)
    links = await page.locator('a[href]').evaluate_all(
        '(nodes) => nodes.map(n => ({text:n.innerText,href:n.href}))')
    buttons = await page.get_by_role('button').all_text_contents()
    structure = await structure_report(page)
    write_json(output / 'structure.json', structure)
    write_json(output / 'inspect.json', {
        'url': page.url, 'captured_at': utcnow(), 'buttons': buttons, 'links': links,
        'models': None if models is None else [
            {'uri': m['uri'], 'bytes': len(m['text'].encode()), 'lines': len(m['text'].splitlines()),
             'sha256': digest(m['text'].encode())} for m in models],
        'note': 'Read-only discovery. Calibrate result selectors against an actual submission detail page.'})
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


async def click_once(context, page, config, candidate, journal):
    validate_config(config)
    check_origin(page.url, config['allowed_origin'])
    before_links = await visible_links(page, config)
    old_pages = set(context.pages)
    submit = page.get_by_role('button', name=config['submit_button_name'], exact=True)
    if await submit.count() != 1 or not await submit.is_enabled():
        raise ValueError('Cannot uniquely identify an enabled submit button')
    # Intent is durable before the only write. Any subsequent failure is
    # ambiguous and stays blocked; click is never retried in this workflow.
    record = journal.create(candidate, config)
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
                else:
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


async def read_result(page, config, record):
    if record.get('result_url') and page.url != record['result_url']:
        raise ValueError('Result page URL differs from this submission')
    if config.get('result_adapter') == 'cannjudge-table':
        from .site import read_cannjudge_result
        return await read_cannjudge_result(page, config, record)
    # The result page must display the record ID that the URL identifies.
    submission_id = await unique_text(page, config['result_id_selector'])
    if not submission_id or (config.get('result_id_matches_url', True) and not re.search(
            r'(?<![\w-])' + re.escape(submission_id) + r'(?![\w-])', page.url)):
        raise ValueError('Visible submission ID does not match the bound result URL')
    if record.get('submission_id') and record['submission_id'] != submission_id:
        raise ValueError('Result page switched to another submission')
    record['submission_id'] = submission_id
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
    for row in await page.locator(config['case_row_selector']).all():
        case_id = (await row.locator(config['case_id_selector']).inner_text()).strip()
        match = re.fullmatch(r'(?:测试点\s*)?(\d+)', case_id)
        if not match:
            raise ValueError('Unrecognized case ID: ' + case_id)
        status = (await row.locator(config['case_status_selector']).inner_text()).strip()
        if status not in config['case_success_statuses']:
            raise ValueError('Overall success disagrees with per-case precision/status: ' + status)
        raw = (await row.locator(config['case_latency_selector']).inner_text()).strip()
        cases.append({'id': int(match[1]), 'latency_us': latency_us(raw),
                      'raw_latency': raw, 'status': status})
    if len(cases) != 15 or {c['id'] for c in cases} != set(range(1, 16)):
        raise ValueError('Success needs exactly 15 unique case results')
    return {'state': 'accepted', 'cases': sorted(cases, key=lambda c: c['id'])}


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
            record.update(result)
            record.pop('last_error', None)
        except Exception as error:
            record['last_error'] = str(error)
            journal.save(record)
            await snapshot(page, directory, 'result_parse_error')
            raise
        journal.save(record)
        if record['state'] in ('accepted', 'rejected'):
            await snapshot(page, directory, 'result')
            if config.get('log_selector'):
                (directory / 'compiler_or_runtime_log.txt').write_text(
                    await unique_text(page, config['log_selector']))
            return record
        await asyncio.sleep(config['poll_seconds'])
        await page.reload(wait_until='domcontentloaded', timeout=30000)
    record['last_error'] = 'Timed out waiting for this result; resume reads the same submission without clicking'
    journal.save(record)
    await snapshot(page, directory, 'pending_timeout')
    raise TimeoutError(record['last_error'])
