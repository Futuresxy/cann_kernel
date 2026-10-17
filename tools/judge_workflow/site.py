"""CANNJudge's visible submission header and five-column execution table."""
import math
import re

from .core import check_origin, latency_us
from .editor import unique_visible


RESULT_PATTERN = r'/public/op_challenge_jingdong_prelim/rotaryposemb/submission/[A-Za-z0-9_-]+(?:[/?#].*)?$'

TABLE = """(table) => ({
    headers: [...table.querySelectorAll('thead th, thead td, [role="columnheader"]')].map(n=>n.innerText.trim()),
    rows: [...table.querySelectorAll('tbody tr, [role="rowgroup"] [role="row"]')].filter(n=>n.getClientRects().length)
        .map(n=>[...n.querySelectorAll('td, [role="cell"]')].map(c=>c.innerText.trim()))
})"""


def parse_table(table, config):
    headers = [re.sub(r'\s+', '', text) for text in table['headers']]
    required = ['测试点', '结果', '输出错误占比', '用时', '最优用时']
    if any(headers.count(name) != 1 for name in required):
        raise ValueError('Expected unique CANNJudge columns: ' + ', '.join(required))
    index = {name: headers.index(name) for name in required}
    cases = []
    for cells in table['rows']:
        if len(cells) != len(headers):
            raise ValueError('Result table row has an unexpected column count')
        case_id = cells[index['测试点']]
        if not re.fullmatch(r'\d+', case_id):
            raise ValueError('Unrecognized case ID: ' + case_id)
        status = cells[index['结果']]
        if status not in config['case_success_statuses']:
            raise ValueError('Overall success disagrees with per-case precision/status: ' + status)
        raw_error = cells[index['输出错误占比']]
        if not re.fullmatch(r'\d+(?:\.\d+)?\s*%', raw_error):
            raise ValueError('Unrecognized output-error percentage: ' + raw_error)
        error_percent = float(raw_error.rstrip('%').strip())
        if not math.isfinite(error_percent) or not 0 <= error_percent <= 100:
            raise ValueError('Invalid output-error percentage')
        raw = cells[index['用时']]
        best = cells[index['最优用时']]
        cases.append({'id': int(case_id), 'latency_us': latency_us(raw), 'raw_latency': raw,
                      'status': status, 'error_percent': error_percent, 'raw_error_percent': raw_error,
                      'best_latency_us': latency_us(best), 'raw_best_latency': best})
    if len(cases) != 15 or {c['id'] for c in cases} != set(range(1, 16)):
        raise ValueError('Success needs exactly 15 unique case results')
    return sorted(cases, key=lambda c: c['id'])


async def read_cannjudge_result(page, config, record):
    check_origin(page.url, config['allowed_origin'])
    if not re.search(config['result_url_pattern'], page.url):
        raise ValueError('Not a calibrated submission detail URL')
    header = await unique_visible(page, config['result_metadata_selector'])
    text = await header.inner_text()
    identity = re.search(r'提交\s*ID\s*[:：]\s*([\w-]+)', text, re.I)
    status_label = re.search(r'提交\s*状态\s*[:：]\s*([^\n]+)', text)
    if identity is None or status_label is None:
        raise ValueError('Submission ID or status is missing from the visible metadata header')
    submission_id = identity[1]
    # The URL contains an opaque database key, while the visible ID is numeric.
    # Bind both independently; never require one to be a substring of the other.
    if record.get('submission_id') and record['submission_id'] != submission_id:
        raise ValueError('Result page switched to another submission')
    record['submission_id'] = submission_id
    status = status_label[1].strip()
    record['platform_status'] = status
    if config.get('score_selector'):
        score = await unique_visible(page, config['score_selector'])
        record['platform_score_raw'] = (await score.inner_text()).strip()
    if status in config['failure_statuses']:
        return {'state': 'rejected', 'cases': []}
    if status not in config['success_statuses']:
        return {'state': 'pending', 'cases': []}
    table = await unique_visible(page, config['result_table_selector'])
    return {'state': 'accepted', 'cases': parse_table(await table.evaluate(TABLE), config)}


async def calibrate_result(page, config):
    """Read-only discovery against a completed, real historical result page."""
    check_origin(page.url, config['allowed_origin'])
    if not re.search(RESULT_PATTERN, page.url):
        raise ValueError('Use an actual RotaryPosEmb /submission/... detail URL')
    await page.wait_for_function("() => /提交\\s*ID\\s*[:：]/i.test(document.body?.innerText || '')", timeout=60000)
    found = await page.evaluate(r"""() => {
        const visible=n=>!!n.getClientRects().length;
        const path=n=>{
            const parts=[];
            for(let x=n;x && x.nodeType===1;x=x.parentElement){
                if(x.id){parts.unshift('#'+CSS.escape(x.id)); break;}
                const siblings=x.parentElement?[...x.parentElement.children]:[x];
                parts.unshift(x.tagName.toLowerCase()+':nth-child('+(siblings.indexOf(x)+1)+')');
            }
            return parts.join(' > ');
        };
        const headers=[...document.querySelectorAll('div,section,header')].filter(n=>{
            const t=n.innerText || '';
            return visible(n) && t.length<1500 && /提交\s*ID\s*[:：]/i.test(t) && /提交\s*状态\s*[:：]/.test(t);
        });
        const leaves=headers.filter(n=>!headers.some(c=>c!==n && n.contains(c)));
        const tables=[...document.querySelectorAll('table,[role="table"]')].filter(n=>{
            const h=[...n.querySelectorAll('thead th,thead td,[role="columnheader"]')].map(c=>c.innerText.replace(/\s+/g,''));
            return visible(n) && ['测试点','结果','输出错误占比','用时','最优用时'].every(s=>h.filter(x=>x===s).length===1);
        });
        return {headers:leaves.map(path),tables:tables.map(path)};
    }""")
    if len(found['headers']) != 1 or len(found['tables']) != 1:
        raise ValueError('Cannot uniquely discover the header/table; run inspect --share on this result page')
    calibrated = dict(config, result_adapter='cannjudge-table', result_url_pattern=RESULT_PATTERN,
                      result_link_selector='a[href*="/rotaryposemb/submission/"]',
                      result_metadata_selector=found['headers'][0], result_table_selector=found['tables'][0],
                      result_id_matches_url=False, calibrated=False)
    for field in ('success_statuses', 'case_success_statuses'):
        calibrated[field] = list(dict.fromkeys([*calibrated[field], 'Pass']))
    record = {'result_url': page.url}
    result = await read_cannjudge_result(page, calibrated, record)
    if result['state'] != 'accepted':
        raise ValueError('Calibrate using a completed Pass result with all 15 case rows')
    return calibrated, {'submission_id': record['submission_id'], 'case_count': len(result['cases']),
                        'note': 'Historical result used only for UI calibration, not associated with the candidate kernel.'}
