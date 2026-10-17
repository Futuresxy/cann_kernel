"""A shareable DOM structure report: no source, input values, cookies or URLs."""
from .core import utcnow


STRUCTURE = r"""() => {
    const visible = n => !!(n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden');
    const path = n => {
        if(n.id) return '#' + CSS.escape(n.id);
        const parts=[];
        for(let x=n; x && x.nodeType===1 && parts.length<8; x=x.parentElement) {
            if(x.id) {parts.unshift('#'+CSS.escape(x.id)); break;}
            const siblings=x.parentElement ? [...x.parentElement.children] : [x];
            parts.unshift(x.tagName.toLowerCase()+':nth-child('+(siblings.indexOf(x)+1)+')');
        }
        return parts.join(' > ');
    };
    const label = n => {
        const s=(n.innerText || '').trim();
        if(/^(kernel\.asc|main\.asc|提交代码|提交|关闭|退出|Accepted|AC|PASS|FAIL|Waiting|Pending|Running|Judging|Compile Error|Wrong Answer|Runtime Error|Time Limit Exceeded|Memory Limit Exceeded|System Error|通过|测试通过|精度错误|编译错误|运行错误|超时|正在编译|编译中|排队中|运行中|评测中|提交成功|提交状态\s*[:：]\s*[\w\s\u4e00-\u9fff]+|测试点\s*\d+|\d+(\.\d+)?\s*(ns|us|µs|μs|ms|s)|\d{1,2})$/i.test(s)) return s;
        if(s.length<100 && /kernel\.asc/.test(s)) return 'kernel.asc';
        if(s.length<100 && /main\.asc/.test(s)) return 'main.asc';
        return null;
    };
    const chosen=new Set();
    const select=n => {for(let depth=0;n && depth<3;depth++,n=n.parentElement) chosen.add(n);};
    for(const n of document.querySelectorAll('.monaco-editor,.cm-editor,.cm-content,.CodeMirror,.ace_editor,textarea,[contenteditable="true"],[role="tab"],[role="dialog"],[role="status"],dialog,table,tr,button,a,span,div')) {
        if(n.matches('.monaco-editor,.cm-editor,.cm-content,.CodeMirror,.ace_editor,textarea,[contenteditable="true"],[role="tab"],[role="dialog"],[role="status"],dialog,table,tr') || label(n)) select(n);
        if(chosen.size>700) break;
    }
    return {
        public_monaco: !!globalThis.monaco?.editor?.getModels,
        nodes: [...chosen].slice(0,700).map(n=>({
            selector:path(n), tag:n.tagName.toLowerCase(), role:n.getAttribute('role'),
            classes:typeof n.className==='string' ? n.className.slice(0,500) : '',
            selected:n.getAttribute('aria-selected'), visible:visible(n), label:label(n),
            editable:n.matches('textarea,[contenteditable="true"]'), parent:n.parentElement ? path(n.parentElement) : null
        })),
        frames:[...document.querySelectorAll('iframe')].map(n=>({selector:path(n),visible:visible(n)}))
    };
}"""


async def structure_report(page):
    report = await page.evaluate(STRUCTURE)
    report.update(schema='cannjudge-dom-structure-v1', captured_at=utcnow())
    report['note'] = ('Structure and allowlisted UI labels only. CSS selectors require live verification. '
                      'No editor contents, account labels, input values, hrefs or browser storage.')
    return report
