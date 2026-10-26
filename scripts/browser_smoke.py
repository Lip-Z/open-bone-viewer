"""Browser verification. Screenshots/results must be outside the source tree."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def browser_executable() -> str | None:
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', '')) / 'ms-playwright'
        candidates = sorted(base.glob('chromium-*/chrome-win64/chrome.exe'), reverse=True)
        if candidates:
            return str(candidates[0])
    return None


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_projection_study(page, study_id: str) -> None:
    page.locator(f'[data-study-id="{study_id}"] .study-select').click()
    image = page.locator('.xray-host img')
    image.wait_for(state='visible', timeout=180000)
    page.wait_for_function(
        'document.querySelector(".xray-host img")?.complete && '
        'document.querySelector(".xray-host img").naturalWidth > 0',
        timeout=180000,
    )
    image_info = image.evaluate('image => ({width: image.naturalWidth, height: image.naturalHeight})')
    check(image_info['width'] > 100 and image_info['height'] > 100, f'X-ray image is empty: {image_info}')


def check_projection_viewer(page, output: Path, report: dict, *, search_help: bool) -> None:
    check(page.locator('.viewer-advanced').get_attribute('open') is None, 'X-ray advanced controls should start closed')
    page.get_by_role('button', name='X 光怎么看？', exact=True).click()
    page.get_by_role('heading', name='先看完整画面，再放大想了解的位置', exact=True).wait_for(state='visible')
    if search_help:
        page.get_by_label('搜索答疑', exact=True).fill('不同深度')
        page.get_by_role('heading', name='找到 1 个相关问题', exact=True).wait_for(state='visible')
    page.get_by_role('button', name='关闭答疑', exact=True).click()
    check(page.locator('.help-dialog').get_attribute('open') is None, 'X-ray help did not close')

    page.get_by_role('button', name='放大影像', exact=True).click()
    check('120%' in page.locator('.zoom-controls').inner_text(), 'X-ray zoom failed')
    page.get_by_role('button', name='恢复初始显示', exact=True).click()
    check('100%' in page.locator('.zoom-controls').inner_text(), 'X-ray zoom reset failed')

    page.locator('.viewer-advanced > summary').click()
    page.get_by_label('X 光对比度', exact=True).fill('1.5')
    page.get_by_label('X 光亮度', exact=True).fill('1.2')
    page.get_by_role('button', name='恢复初始显示', exact=True).click()
    check(page.get_by_label('X 光对比度', exact=True).input_value() == '1', 'X-ray contrast reset failed')
    check(page.get_by_label('X 光亮度', exact=True).input_value() == '1', 'X-ray brightness reset failed')
    check(page.get_by_role('link', name='保存显示图片 PNG', exact=True).get_attribute('href'), 'X-ray image download missing')

    page.set_viewport_size({'width': 390, 'height': 844})
    check(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 2'), 'Horizontal overflow in mobile X-ray viewport')
    page.get_by_role('button', name='X 光怎么看？', exact=True).click()
    page.get_by_role('heading', name='先看完整画面，再放大想了解的位置', exact=True).wait_for(state='visible')
    check(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 2'), 'Horizontal overflow in mobile X-ray help')
    page.screenshot(path=str(output / 'xray-mobile-help.png'), full_page=True)
    page.get_by_role('button', name='关闭答疑', exact=True).click()
    page.screenshot(path=str(output / 'xray-mobile.png'), full_page=True)
    report['checks'].append('Projection help, zoom, display reset and 390 px mobile layout operated')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:4318')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--study-id', help='Inspect an existing CT or X-ray instead of creating a synthetic demo')
    parser.add_argument('--headed', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error('Test artifacts must be stored outside the source checkout.')
    output.mkdir(parents=True, exist_ok=True)
    report: dict = {'checks': [], 'console_errors': [], 'external_requests': []}
    started = time.monotonic()
    with httpx.Client(base_url=args.url, trust_env=False, timeout=60) as api, sync_playwright() as p:
        check(api.get('/api/health').json()['status'] == 'ok', 'Local API unavailable')
        browser = p.chromium.launch(headless=not args.headed, executable_path=browser_executable(), args=['--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--no-proxy-server'])
        page = browser.new_page(viewport={'width': 1500, 'height': 1100}, device_scale_factor=1, accept_downloads=True)
        page.on('pageerror', lambda error: report['console_errors'].append(str(error)))
        page.on('console', lambda message: report['console_errors'].append(message.text) if message.type == 'error' else None)
        page.on('request', lambda request: report['external_requests'].append(request.url) if not request.url.startswith(args.url) and not request.url.startswith(('blob:', 'data:')) else None)
        page.goto(args.url, wait_until='networkidle')
        page.screenshot(path=str(output / 'initial.png'), full_page=True)
        if args.study_id:
            study_id = args.study_id
            card = page.locator(f'[data-study-id="{study_id}"] .study-select')
            card.click()
            study = next(
                item for item in api.get('/api/studies').json()['studies']
                if item['id'] == study_id
            )
        else:
            old_ids = {item['id'] for item in api.get('/api/studies').json()['studies']}
            page.get_by_role('button', name='打开合成示例', exact=True).click()
            page.get_by_label('横断位层面', exact=True).wait_for(state='visible', timeout=120000)
            studies = api.get('/api/studies').json()['studies']
            created = [item for item in studies if item['id'] not in old_ids]
            study_id = next(item['id'] for item in created if item['kind'] == 'ct' and item['supported'])
            study = next(item for item in studies if item['id'] == study_id)
            report['created_study_ids'] = [item['id'] for item in created]
            report['checks'].append('Synthetic demo created from the browser')
        if study['kind'] == 'xray':
            check(study['supported'], 'Requested X-ray study is unsupported')
            load_projection_study(page, study_id)
            check_projection_viewer(page, output, report, search_help=True)
            report['study_id'] = study_id
            report['study_kind'] = 'xray'
            report['elapsed_seconds'] = round(time.monotonic() - started, 2)
            report['passed'] = not report['console_errors'] and not report['external_requests']
            (output / 'browser-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
            browser.close()
            check(report['passed'], f'Browser errors or external requests found: {report}')
            print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'elapsed_seconds': report['elapsed_seconds']}, ensure_ascii=False))
            return
        page.get_by_label('横断位层面', exact=True).wait_for(state='visible', timeout=180000)
        page.locator('.three-viewport .render-badge').wait_for(state='visible', timeout=120000)
        page.locator('.three-viewport .view-message').wait_for(state='hidden', timeout=120000)
        check(page.locator('.slice-panel canvas').count() == 3, 'Expected three MPR canvases')
        check(page.locator('.three-viewport canvas').count() == 1, 'Expected a WebGL canvas')
        report['checks'].append('Three MPR canvases and volume rendering loaded')
        check(page.locator('.viewer-advanced').get_attribute('open') is None, 'Advanced controls should be closed initially')
        page.get_by_role('button', name='这几个画面怎么看？', exact=True).click()
        page.get_by_role('heading', name='三个切面，是同一份 CT 的不同方向', exact=True).wait_for(state='visible')
        page.get_by_label('搜索答疑', exact=True).fill('十字线')
        page.get_by_role('heading', name='找到 1 个相关问题', exact=True).wait_for(state='visible')
        page.get_by_role('button', name='关闭答疑', exact=True).click()
        check(page.locator('.help-dialog').get_attribute('open') is None, 'Help did not close')
        report['checks'].append('Contextual CT help and local FAQ search opened and closed')
        page.screenshot(path=str(output / 'ct-basic.png'), full_page=True)
        if page.get_by_role('button', name='主体预览', exact=True).count():
            check(page.get_by_role('button', name='主体预览', exact=True).get_attribute('aria-pressed') == 'true', 'Body preview should be initially selected')
            page.get_by_role('button', name='全部结构', exact=True).click()
            page.locator('.three-viewport .view-message').wait_for(state='hidden', timeout=120000)
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(output / 'ct-all-structures.png'), full_page=True)
            page.get_by_role('button', name='主体预览', exact=True).click()
            page.locator('.three-viewport .view-message').wait_for(state='hidden', timeout=120000)
            check(page.get_by_role('button', name='主体预览', exact=True).get_attribute('aria-pressed') == 'true', 'Body preview selection failed')
            report['checks'].append('Body preview and complete-structure rendering toggled')
        # A canvas must contain actual image intensities, not just an element.
        image_stats = page.locator('.slice-panel canvas').evaluate_all('canvases => canvases.map(c => { const d=c.getContext("2d").getImageData(0,0,c.width,c.height).data; const levels=new Set(); for(let i=0;i<d.length;i+=4) if(d[i]===d[i+1] && d[i]===d[i+2]) levels.add(d[i]); return {width:c.width,height:c.height,levels:levels.size}; })')
        check(all(item['levels'] > 3 for item in image_stats), f'MPR appears empty: {image_stats}')
        report['mpr_canvas_stats'] = image_stats
        page.locator('.viewer-advanced > summary').click()
        point_before = page.locator('.position-readout code').inner_text()
        axial = page.get_by_label('横断位层面', exact=True)
        maximum = int(axial.get_attribute('max'))
        axial.fill(str(max(0, maximum // 3)))
        check(page.locator('.position-readout code').inner_text() != point_before, 'Slice slider did not change position')
        canvas = page.locator('.slice-panel canvas').first
        bounds = canvas.bounding_box()
        canvas.click(position={'x': bounds['width'] * .6, 'y': bounds['height'] * .45})
        page.get_by_role('button', name='看软组织', exact=True).click()
        check(page.get_by_label('窗位 HU', exact=True).input_value() == '40', 'Window preset failed')
        page.get_by_role('button', name='看骨骼', exact=True).click()
        report['checks'].append('Slice slider, crosshair and window preset operated')
        page.get_by_role('button', name='横断位全屏', exact=True).click()
        page.wait_for_function('Boolean(document.fullscreenElement)')
        page.get_by_role('button', name='退出横断位全屏', exact=True).click()
        page.wait_for_function('!document.fullscreenElement')
        report['checks'].append('MPR fullscreen entered and exited')
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(output / 'ct-volume.png'), full_page=True)
        with page.expect_download(timeout=60000) as download_event:
            page.get_by_role('link', name='下载原始数据 NRRD', exact=True).click()
        download = download_event.value
        download.save_as(str(output / 'source.nrrd'))
        check((output / 'source.nrrd').stat().st_size > 100, 'NRRD download empty')
        page.get_by_role('button', name='生成表面模型', exact=True).click()
        page.get_by_role('button', name='生成表面模型', exact=True).wait_for(state='visible', timeout=240000)
        page.locator('.mesh-progress').wait_for(state='hidden', timeout=240000)
        page.locator('.model-details').wait_for(state='visible', timeout=180000)
        page.locator('.three-viewport .render-badge').wait_for(state='visible', timeout=120000)
        page.locator('.three-viewport .view-message').wait_for(state='hidden', timeout=120000)
        check('300 HU' in page.locator('.model-details').inner_text(), 'Unexpected model threshold')
        with page.expect_download(timeout=60000) as download_event:
            page.get_by_role('link', name='导出 STL', exact=True).click()
        download_event.value.save_as(str(output / 'surface.stl'))
        size = (output / 'surface.stl').stat().st_size
        check(size > 84 and (size - 84) % 50 == 0, 'STL download invalid')
        report['checks'].append('Surface generated in browser; NRRD and STL downloaded')
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(output / 'ct-surface.png'), full_page=True)
        page.get_by_label('阈值 HU', exact=True).fill('450')
        check(page.locator('.model-control-heading a').get_attribute('aria-disabled') == 'true', 'Stale export should be disabled after parameter changes')
        report['checks'].append('Changing threshold prevents stale model export')
        # Rotate the surface and verify a real pointer interaction is accepted.
        surface = page.locator('.three-viewport canvas')
        rect = surface.bounding_box()
        page.mouse.move(rect['x'] + rect['width'] * .5, rect['y'] + rect['height'] * .5)
        page.mouse.down()
        page.mouse.move(rect['x'] + rect['width'] * .7, rect['y'] + rect['height'] * .6, steps=12)
        page.mouse.up()
        page.get_by_role('button', name='重置三维视角', exact=True).click()
        report['checks'].append('Three-dimensional drag and reset operated')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(output / 'ct-mobile.png'), full_page=True)
        check(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 2'), 'Horizontal overflow in mobile CT viewport')
        page.get_by_role('button', name='这几个画面怎么看？', exact=True).click()
        page.get_by_role('heading', name='三个切面，是同一份 CT 的不同方向', exact=True).wait_for(state='visible')
        check(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 2'), 'Horizontal overflow in mobile CT help')
        page.screenshot(path=str(output / 'ct-mobile-help.png'), full_page=True)
        page.get_by_role('button', name='关闭答疑', exact=True).click()
        report['checks'].append('CT layout and contextual help fit a 390 px mobile viewport')
        page.set_viewport_size({'width': 1500, 'height': 1100})
        studies = api.get('/api/studies').json()['studies']
        projection = next((item for item in studies if item['kind'] == 'xray' and item['supported']), None)
        if projection:
            load_projection_study(page, projection['id'])
            check_projection_viewer(page, output, report, search_help=False)
            page.screenshot(path=str(output / 'xray.png'), full_page=True)
        report['study_id'] = study_id
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        report['passed'] = not report['console_errors'] and not report['external_requests']
        (output / 'browser-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        browser.close()
        check(report['passed'], f'Browser errors or external requests found: {report}')
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'elapsed_seconds': report['elapsed_seconds']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
