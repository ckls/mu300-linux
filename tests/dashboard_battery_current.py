"""Render battery flow/power/current in the real homepage, including dock discharge."""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2 if Path(__file__).parent.parent.name=='openwrt' else 1]
APP=next(p for p in (ROOT/'openwrt/luci-app-t551m',ROOT/'openwrt/luci-app-mu300') if p.is_dir())
JS=APP/'htdocs/luci-static/resources'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--browser')
    parser.add_argument('--app',type=Path,default=JS.parents[2]);args=parser.parse_args()
    resources=args.app/'htdocs/luci-static/resources'
    common=(resources/'mu300/common.js').read_text(encoding='utf-8')
    home=(resources/'view/mu300/home.js').read_text(encoding='utf-8')
    count=0
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,**({'executable_path':args.browser} if args.browser else {}))
        for lang in ('zh','en','tr'):
            for width in (320,390,1280):
                page=browser.new_page(viewport={'width':width,'height':900})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.set_content('<html><body><main></main></body></html>')
                page.evaluate("""([common,home,lang])=>{
                    const base={extend:x=>x},L={env:{lang}};
                    window.M=new Function('rpc','baseclass','L',common)({declare:()=>()=>Promise.resolve({})},base,L);
                    window.app=new Function('view','uci','R','M','SimRadio','L',home)(base,{}, {},M,{},L);
                    M.injectCss();app._root=document.querySelector('main');app._root.className='mud';
                    app._root.innerHTML=app.html();
                }""",[common,home,lang])
                labels={
                    'zh':{'in':'充电','out':'放电','full':'已充满','paused':'未充电','unknown':'未知','usb':'USB供电','battery':'电池供电','source':'供电来源未知'},
                    'en':{'in':'Charging ','out':'Discharging ','full':'Fully charged ','paused':'Not charging ','unknown':'Unknown ','usb':'USB power','battery':'Battery power','source':'Unknown power source'},
                    'tr':{'in':'Şarj ','out':'Deşarj ','full':'Tam şarj oldu ','paused':'Şarj olmuyor ','unknown':'Bilinmiyor ','usb':'USB gücü','battery':'Pil gücü','source':'Bilinmeyen güç kaynağı'},
                }[lang]
                cases=[
                    (-750000,3.92,0,'Discharging','out','2.9W/0.75A·3.92V·','battery'),
                    (750000,3.92,1,'Charging','in','2.9W/0.75A·3.92V·','usb'),
                    (-750000,3.92,1,'Charging','out','2.9W/0.75A·3.92V·','usb'),
                    (0,3.92,1,'Full','full','0.0W/0.00A·3.92V·','usb'),
                    (0,3.92,1,'Not charging','paused','0.0W/0.00A·3.92V·','usb'),
                    (None,3.92,1,'Charging','in','--W/--A·3.92V·','usb'),
                    (750000,None,1,'Charging','in','--W/0.75A·--V·','usb'),
                    (750000,0,1,'Charging','in','--W/0.75A·--V·','usb'),
                    (-4000,3.92,0,'Discharging','out','0.0W/0.004A·3.92V·','battery'),
                    (260000,3.94,1,'Charging','in','1.0W/0.26A·3.94V·','usb'),
                    (None,None,None,None,'unknown','--W/--A·--V·','source'),
                ]
                for current,voltage,usb,status,flow,readings,source in cases:
                    # A plugged-in dock can still discharge the battery: sign
                    # follows the actual measurement, never USB or status.
                    page.evaluate("p=>app.update({info:{power:p}})",dict(present=1,capacity=73,status=status,volt=voltage,ua=current,usb=usb))
                    actual=page.locator('#mud-batt-l').inner_text()
                    assert actual==labels[flow]+readings+labels[source],(args.app,lang,actual)
                    assert page.locator('#mud-batt-meter').is_visible()
                    assert page.locator('#mud-batt-bar').evaluate('el=>el.style.width')=='73%'
                    count+=1
                page.evaluate("app.update({info:{power:{present:0,ua:999999,usb:1}}})")
                assert 'mA' not in page.locator('#mud-batt-l').inner_text()
                assert page.locator('#mud-batt').inner_text()=='USB'
                assert not page.locator('#mud-batt-meter').is_visible()
                page.evaluate("app.update({info:{power:{present:1,capacity:73,ua:800000}}})")
                assert page.locator('#mud-batt-l').inner_text()==labels['in']+'--W/0.80A·--V·'+labels['source']
                assert page.locator('#mud-batt-meter').is_visible()
                for cap,bar_width in [(0,'0%'),(100,'100%'),(None,'0%')]:
                    page.evaluate('cap=>app.update({info:{power:{present:1,capacity:cap}}})',cap)
                    assert page.locator('#mud-batt-bar').evaluate('el=>el.style.width')==bar_width
                    assert page.locator('#mud-batt-meter').is_visible()==(cap is not None)
                assert page.locator('#mud-batt-l').evaluate('e=>e.scrollWidth<=e.clientWidth')
                if width>=390:
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors,errors
                count+=2;page.close()
        browser.close()
    print('PASS',count,'battery summary cases, three languages, mobile/desktop:',args.app)
if __name__=='__main__':main()
