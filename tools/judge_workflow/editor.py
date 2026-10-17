"""Read/write the visible kernel editor through public models or normal UI actions."""
import re
import uuid
from urllib.parse import urlparse

from .core import check_origin, digest


MODELS = """() => {
    if (!globalThis.monaco?.editor?.getModels) return null;
    return monaco.editor.getModels().map(m => ({uri: m.uri.toString(), text: m.getValue()}));
}"""


def kernel_model(models, config):
    explicit = config.get('kernel_model_uri')
    matches = [m for m in models if m['uri'] == explicit] if explicit else [
        m for m in models if urlparse(m['uri']).path.rsplit('/', 1)[-1] == 'kernel.asc']
    if len(matches) != 1:
        raise ValueError('Cannot uniquely identify kernel.asc model; inspect and calibrate its URI')
    return matches[0]


async def editor_scope(page, config):
    if not config.get('editor_frame_selector'):
        return page
    frame_node = await unique_visible(page, config['editor_frame_selector'])
    handle = await frame_node.element_handle()
    frame = await handle.content_frame()
    if frame is None:
        raise ValueError('Configured editor iframe is not ready')
    check_origin(frame.url, config['allowed_origin'])
    return frame


async def unique_visible(scope, selector):
    locator = scope.locator(selector)
    await locator.first.wait_for(state='attached', timeout=15000)
    visible = [node for node in await locator.all() if await node.is_visible()]
    if len(visible) != 1:
        raise ValueError('Expected exactly one visible element for ' + selector)
    return visible[0]


async def models_ready(page):
    await page.wait_for_function('() => !!globalThis.monaco?.editor?.getModels', timeout=15000)
    models = await page.evaluate(MODELS)
    if not models:
        raise ValueError('No public Monaco models; configure the keyboard editor adapter')
    return models


async def editor_mode(page, config):
    mode = config.get('editor_mode', 'auto')
    if mode not in ('auto', 'monaco', 'keyboard'):
        raise ValueError('Unknown editor_mode: ' + str(mode))
    scope = await editor_scope(page, config)
    if mode == 'auto':
        mode = 'monaco' if await scope.evaluate(MODELS) else 'keyboard'
    if mode == 'keyboard':
        for field in ('editor_selector', 'kernel_tab_selector', 'kernel_active_selector'):
            if not config.get(field):
                raise ValueError('No global Monaco API; calibrate keyboard field: ' + field)
    return mode, scope


def identifies_kernel(label):
    names = re.findall(r'(?<![\w.])[\w./-]+\.(?:asc|h|txt|sh|py)(?![\w.])', label)
    return len(names) == 1 and names[0].rsplit('/', 1)[-1] == 'kernel.asc'


async def active_kernel(page, config):
    active = await unique_visible(page, config['kernel_active_selector'])
    label = (await active.inner_text()).strip()
    if not identifies_kernel(label):
        raise ValueError('The active file is not kernel.asc')


async def focus_kernel(page, config, scope, activate=False):
    if activate:
        tab = await unique_visible(page, config['kernel_tab_selector'])
        if not identifies_kernel(await tab.inner_text()):
            raise ValueError('Configured kernel tab does not identify kernel.asc')
        await tab.click()
    await active_kernel(page, config)
    editor = await unique_visible(scope, config['editor_selector'])
    await editor.click()
    if not await editor.evaluate('''node => {
        const a=document.activeElement;
        return !!a && (a===node || node.contains(a)) &&
            (a.tagName==='TEXTAREA' || a.isContentEditable || !!a.editContext || a.getAttribute('role')==='textbox');
    }'''):
        raise ValueError('Keyboard focus did not enter the configured kernel editor')
    return editor


async def copy_kernel(page, config, scope):
    # Clipboard contents are used only in memory. Never read or export the
    # user's previous clipboard; replace it with a fresh sentinel before copy.
    check_origin(page.url, config['allowed_origin'])
    await page.bring_to_front()
    await page.context.grant_permissions(['clipboard-read', 'clipboard-write'],
                                         origin=config['allowed_origin'])
    await focus_kernel(page, config, scope)
    sentinel = 'CANNJUDGE_COPY_' + uuid.uuid4().hex
    await page.evaluate('(s) => navigator.clipboard.writeText(s)', sentinel)
    await page.keyboard.press('ControlOrMeta+A')
    await page.keyboard.press('ControlOrMeta+C')
    await page.wait_for_function('async (s) => (await navigator.clipboard.readText()) !== s',
                                 arg=sentinel, timeout=15000)
    text = await page.evaluate('() => navigator.clipboard.readText()')
    await active_kernel(page, config)
    return text.encode('utf-8')


async def read_kernel(page, config, activate=False):
    mode, scope = await editor_mode(page, config)
    if mode == 'monaco':
        return kernel_model(await models_ready(scope), config)['text'].encode('utf-8')
    if activate:
        await focus_kernel(page, config, scope, activate=True)
    return await copy_kernel(page, config, scope)


async def verify_kernel(page, config, data):
    if await read_kernel(page, config) != data:
        raise ValueError('Editor readback differs from the complete candidate; submission blocked')


async def replace_kernel(page, config, data):
    mode, scope = await editor_mode(page, config)
    text = data.decode('utf-8')
    if mode == 'monaco':
        before = await models_ready(scope)
        target = kernel_model(before, config)
        await scope.evaluate('''({uri,text}) => {
            const m=monaco.editor.getModels().find(m=>m.uri.toString()===uri);
            if(!m) throw new Error('kernel model disappeared');
            m.setValue(text);
        }''', {'uri': target['uri'], 'text': text})
        after = await scope.evaluate(MODELS)
        readback = kernel_model(after, config)['text'].encode('utf-8')
        untouched_before = {m['uri']: m['text'] for m in before if m['uri'] != target['uri']}
        untouched_after = {m['uri']: m['text'] for m in after if m['uri'] != target['uri']}
        if untouched_before != untouched_after:
            raise ValueError('A non-kernel editor model changed; submission blocked')
        details = {'kernel_model_uri': target['uri'], 'unchanged_models': list(untouched_before)}
    else:
        await focus_kernel(page, config, scope, activate=True)
        original = await copy_kernel(page, config, scope)
        await page.evaluate('(s) => navigator.clipboard.writeText(s)', text)
        await page.keyboard.press('ControlOrMeta+V')
        readback = await copy_kernel(page, config, scope)
        details = {'original_kernel_sha256': digest(original),
                   'file_guard': 'active kernel.asc tab checked before and after clipboard readback',
                   'non_kernel_model_audit': 'not available without the public model API'}
    if readback != data:
        raise ValueError('Editor readback differs from the complete candidate; submission blocked')
    lines = text.splitlines()
    return dict(details, editor_mode=mode, readback_sha256=digest(readback), bytes=len(readback),
                lines=len(lines), first_line=lines[0] if lines else '', last_line=lines[-1] if lines else '')
