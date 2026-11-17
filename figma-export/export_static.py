"""ダッシュボードの各画面を、JS描画後の状態で静的HTMLに書き出す（Figma取り込み用）。

使い方:  python figma-export/export_static.py [画面名の一部 ...]
  例)    python figma-export/export_static.py            # 全画面
         python figma-export/export_static.py 01 04      # 01と04だけ

Figma の html_to_figma は「幅1280×高さ720」のビューポートで描画するため、
viewport に依存する指定（@media・position:fixed・sticky）をここで固定値に置き換える。
"""
import base64, pathlib, re, sys
from playwright.sync_api import sync_playwright

PROJECT = pathlib.Path(__file__).resolve().parent.parent
SRC = PROJECT / "kankeijinko_dashboard.html"
OUT = PROJECT / "figma-export"
WIDTH, HEIGHT = 1440, 900

SCREENS = [
    ("01-login", "screen=login", "ログイン"),
    ("02-password-reset", "screen=reset", "ID・パスワード再設定"),
    ("03-password-reset-done", "screen=reset-done", "再設定リンク送信完了"),
    ("04-home-town", "screen=dash&view=gov", "ホーム（まち全体ビュー）"),
    ("05-home-town-route-detail", "screen=dash&view=gov&route=1&detail=1", "まち全体ビュー（主要ルート・詳細を表示）"),
    ("06-home-business", "screen=dash&view=biz&store=1", "ホーム（事業者ビュー）"),
    ("07-home-business-townref", "screen=dash&view=biz&store=1&townref=1", "事業者ビュー（まち全体の参考値を表示）"),
    ("08-history", "screen=hist", "推移ビュー"),
    ("09-list", "screen=list", "一覧ビュー"),
    ("10-account-menu", "screen=dash&view=gov&menu=1", "アカウントメニュー"),
]

FREEZE_JS = r"""
({title, height}) => {
  const SVGNS = 'http://www.w3.org/2000/svg';

  // 1) <use href="#..."> を実体に展開（Figmaは <use> を解決できない）
  document.querySelectorAll('svg use').forEach(u => {
    const ref = (u.getAttribute('href') || u.getAttribute('xlink:href') || '').slice(1);
    const sym = ref && document.getElementById(ref);
    if (!sym) return;
    const g = document.createElementNS(SVGNS, sym.tagName.toLowerCase() === 'symbol' ? 'svg' : 'g');
    if (sym.getAttribute('viewBox')) { g.setAttribute('viewBox', sym.getAttribute('viewBox')); g.setAttribute('width', '100%'); g.setAttribute('height', '100%'); }
    const spriteDefs = sym.ownerSVGElement && sym.ownerSVGElement.querySelector('defs');
    if (spriteDefs) g.appendChild(spriteDefs.cloneNode(true));
    [...sym.childNodes].forEach(n => g.appendChild(n.cloneNode(true)));
    u.replaceWith(g);
  });

  // 2) 白フチ文字（paint-order: stroke）を「白フチの下敷き」＋「フチなしの文字」の2枚に分ける
  //    Figma は paint-order を解釈せず、フチが文字を覆って白い塊になるため
  document.querySelectorAll('svg text').forEach(t => {
    const cs = getComputedStyle(t);
    if (!cs.stroke || cs.stroke === 'none' || !/^stroke/.test(cs.paintOrder)) return;
    const under = t.cloneNode(true);
    under.removeAttribute('class');
    under.setAttribute('fill', cs.stroke);
    under.setAttribute('stroke', cs.stroke);
    under.setAttribute('stroke-width', cs.strokeWidth);
    under.setAttribute('stroke-linejoin', 'round');
    under.setAttribute('font-weight', cs.fontWeight);
    t.parentNode.insertBefore(under, t);
    t.setAttribute('font-weight', cs.fontWeight);
    t.style.stroke = 'none';
  });

  // 3) アカウントメニューを body 直下へ移す（DOM順＝重なり順になるため、後続の要素に隠れないように）
  const menu = document.querySelector('.acct-menu.show');
  if (menu) {
    const r = menu.getBoundingClientRect();
    menu.style.position = 'absolute';
    menu.style.left = (r.left + scrollX) + 'px';
    menu.style.top = (r.top + scrollY) + 'px';
    menu.style.right = 'auto';
    menu.style.width = r.width + 'px';
    menu.style.zIndex = '1000';
    document.body.appendChild(menu);
  }

  // 4) 表示されていない要素を削除（HTML要素のみ）
  const hidden = [];
  document.body.querySelectorAll('*').forEach(el => {
    if (el.namespaceURI !== 'http://www.w3.org/1999/xhtml') return;
    if (el.hidden || getComputedStyle(el).display === 'none') hidden.push(el);
  });
  hidden.forEach(el => el.remove());
  document.querySelectorAll('body > svg[width="0"]').forEach(s => s.remove());

  // 5) フォームの現在値を属性に固定
  document.querySelectorAll('select').forEach(s => {
    [...s.options].forEach((o, i) => { if (i === s.selectedIndex) o.setAttribute('selected', ''); else o.removeAttribute('selected'); });
  });
  document.querySelectorAll('input').forEach(i => {
    if (i.type === 'checkbox' || i.type === 'radio') { if (i.checked) i.setAttribute('checked', ''); else i.removeAttribute('checked'); }
    else if (i.value) i.setAttribute('value', i.value);
  });

  // 6) @media を「今の幅（1440px）で当てはまるものだけ中身を展開、それ以外は削除」に置き換える
  const flatten = (rules) => {
    const out = [];
    for (const r of rules) {
      if (r instanceof CSSMediaRule) {
        if (matchMedia(r.conditionText).matches) out.push(...flatten(r.cssRules));
      } else out.push(r.cssText);
    }
    return out;
  };
  document.querySelectorAll('style').forEach(st => {
    if (!st.sheet) return;
    st.textContent = '\n' + flatten(st.sheet.cssRules).join('\n') + '\n';
  });

  // 7) スクリプトとイベント属性を除去
  document.querySelectorAll('script, noscript').forEach(s => s.remove());
  document.querySelectorAll('*').forEach(el => {
    [...el.attributes].forEach(a => { if (/^on/i.test(a.name)) el.removeAttribute(a.name); });
  });

  // 8) 幅・フォント・位置指定・アニメーションを固定
  const st = document.createElement('style');
  st.textContent = `
    :root { --sans: "Noto Sans JP", sans-serif; }
    html, body { width: ${innerWidth}px; min-width: ${innerWidth}px; margin: 0; overflow: visible !important; }
    body, button, input, select, textarea, svg text { font-family: "Noto Sans JP", sans-serif !important; }
    .topbar { position: relative !important; }
    .login-view { position: relative !important; inset: auto !important; width: 100% !important;
                  min-height: ${height}px; box-sizing: border-box; overflow: visible !important; }
    *, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent; }
  `;
  document.head.appendChild(st);
  document.title = title;
  return '<!DOCTYPE html>\n' + document.documentElement.outerHTML;
}
"""


def main(filters):
    logo_uri = "data:image/png;base64," + base64.b64encode((PROJECT / "logo.png").read_bytes()).decode()
    targets = [s for s in SCREENS if not filters or any(f in s[0] for f in filters)]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, query, label in targets:
            ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
            ctx.add_init_script("try{localStorage.setItem('rokamap_auth','1')}catch(e){}")
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(SRC.as_uri() + "?" + query)
            page.wait_for_load_state("load")
            page.wait_for_timeout(1500)  # 描画・トランジション完了を待つ
            html = page.evaluate(FREEZE_JS, {"title": f"{name} {label}", "height": HEIGHT})
            ctx.close()
            html = html.replace('src="logo.png"', f'src="{logo_uri}"')
            html = html.replace("data:image/png;base64,/9j/", "data:image/jpeg;base64,/9j/")  # 中身はJPEG
            leftovers = re.findall(r'(?:src|href)="(?!data:|#)([^"]+)"', html)
            (OUT / f"{name}.html").write_text(html, encoding="utf-8")
            print(f"{name}: {len(html.encode())//1024} KB  errors={errors}  external_refs={leftovers}")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
