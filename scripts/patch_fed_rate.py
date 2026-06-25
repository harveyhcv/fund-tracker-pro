"""Patch: Add Fed Rate field to DCA form + auto-fetch from Yahoo Finance ^IRX"""
import os
ROOT = os.path.join(os.path.dirname(__file__), '..')
HTML = os.path.join(ROOT, 'telegram-bot', 'miniapp', 'index.html')
content = open(HTML, encoding='utf-8').read()

INP = 'style="width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 8px;font-size:13px;box-sizing:border-box"'

# ── 1. Add Fed Rate field to the grid ───────────────────────────────────────
OLD_GRID = '''        <label>Dữ liệu thị trường hiện tại</label>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
          <div>
            <div style="font-size:11px;color:var(--txt2);margin-bottom:3px">USD/VND</div>
            <input type="text" inputmode="decimal" id="gp-usd" placeholder="VD: 25900" style="width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 8px;font-size:13px;box-sizing:border-box" oninput="runGoldPrediction()">
          </div>
          <div>
            <div style="font-size:11px;color:var(--txt2);margin-bottom:3px">XAU/USD</div>
            <input type="text" inputmode="decimal" id="gp-xau" placeholder="VD: 3300" style="width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 8px;font-size:13px;box-sizing:border-box" oninput="runGoldPrediction()">
          </div>
          <div>
            <div style="font-size:11px;color:var(--txt2);margin-bottom:3px">BTC/USD</div>
            <input type="text" inputmode="decimal" id="gp-btc" placeholder="VD: 105000" style="width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 8px;font-size:13px;box-sizing:border-box" oninput="runGoldPrediction()">
          </div>
          <div>
            <div style="font-size:11px;color:var(--txt2);margin-bottom:3px">Lạm phát VN (%/năm)</div>
            <input type="text" inputmode="decimal" id="gp-inf" placeholder="VD: 4.5" style="width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 8px;font-size:13px;box-sizing:border-box" oninput="runGoldPrediction()">
          </div>
        </div>
        <button onclick="autoFillMarketData()" style="width:100%;padding:8px;background:var(--bg3);border:1px solid var(--bdr);color:var(--c0);border-radius:8px;font-size:12px;cursor:pointer;margin-bottom:4px;font-family:var(--mono)">⟳ Tự động điền từ dữ liệu hiện có</button>'''

NEW_GRID = '''        <label>Dữ liệu thị trường hiện tại</label>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
          <div>
            <div style="font-size:11px;color:var(--txt2);margin-bottom:3px">USD/VND</div>
            <input type="text" inputmode="decimal" id="gp-usd" placeholder="VD: 25900" style="width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 8px;font-size:13px;box-sizing:border-box" oninput="runGoldPrediction()">
          </div>
          <div>
            <div style="font-size:11px;color:var(--txt2);margin-bottom:3px">XAU/USD</div>
            <input type="text" inputmode="decimal" id="gp-xau" placeholder="VD: 3300" style="width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 8px;font-size:13px;box-sizing:border-box" oninput="runGoldPrediction()">
          </div>
          <div>
            <div style="font-size:11px;color:var(--txt2);margin-bottom:3px">BTC/USD</div>
            <input type="text" inputmode="decimal" id="gp-btc" placeholder="VD: 105000" style="width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 8px;font-size:13px;box-sizing:border-box" oninput="runGoldPrediction()">
          </div>
          <div>
            <div style="font-size:11px;color:var(--txt2);margin-bottom:3px">Lạm phát VN (%/năm)</div>
            <input type="text" inputmode="decimal" id="gp-inf" placeholder="VD: 4.5" style="width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 8px;font-size:13px;box-sizing:border-box" oninput="runGoldPrediction()">
          </div>
          <div style="grid-column:1/-1">
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
              <span style="font-size:11px;color:var(--txt2)">Lãi suất Fed (%)</span>
              <span id="gp-fed-status" style="font-size:10px;color:var(--txt2);opacity:.6"></span>
            </div>
            <div style="display:flex;gap:6px;align-items:center">
              <input type="text" inputmode="decimal" id="gp-fed" placeholder="VD: 4.33" style="flex:1;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 8px;font-size:13px;box-sizing:border-box" oninput="runGoldPrediction()">
              <button onclick="fetchFedRate()" id="gp-fed-btn" style="flex-shrink:0;padding:7px 10px;background:var(--bg3);border:1px solid var(--bdr);color:var(--c0);border-radius:8px;font-size:11px;cursor:pointer;font-family:var(--mono);white-space:nowrap">⟳ Lấy</button>
            </div>
          </div>
        </div>
        <button onclick="autoFillMarketData()" style="width:100%;padding:8px;background:var(--bg3);border:1px solid var(--bdr);color:var(--c0);border-radius:8px;font-size:12px;cursor:pointer;margin-bottom:4px;font-family:var(--mono)">⟳ Tự động điền tất cả</button>'''

if OLD_GRID in content:
    content = content.replace(OLD_GRID, NEW_GRID)
    print('OK: Fed Rate field added to grid')
else:
    print('FAIL: grid not found')

# ── 2. Add fetchFedRate() function near autoFillMarketData ──────────────────
OLD_AUTO = '''function autoFillMarketData(){
  const prices = _goldData&&_goldData.prices ? _goldData.prices : {};
  const xau = prices['INTERNATIONAL:XAUUSD'] || Object.values(prices).find(function(p){return p.currency==='USD';});
  if (xau && xau.buy) document.getElementById('gp-xau').value = Number(xau.buy).toFixed(0);
  if (xau && xau.extra && xau.extra.usd_vnd) document.getElementById('gp-usd').value = Number(xau.extra.usd_vnd).toFixed(0);
  const btcEl = document.getElementById('gp-btc');
  if (btcEl && !btcEl.value) {
    fetch('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT')
      .then(r=>r.json()).then(d=>{if(d.price){btcEl.value=Number(d.price).toFixed(0);runGoldPrediction();}})
      .catch(()=>{});
  }
  runGoldPrediction();
}'''

NEW_AUTO = '''async function fetchFedRate(){
  const btn = document.getElementById('gp-fed-btn');
  const status = document.getElementById('gp-fed-status');
  if (btn) { btn.textContent = '...'; btn.disabled = true; }
  if (status) status.textContent = 'đang lấy...';
  try {
    // Yahoo Finance ^IRX = 13-week T-Bill rate — proxy cho Fed Funds Rate
    const r = await fetch('https://query1.finance.yahoo.com/v8/finance/chart/%5EIRX?interval=1d&range=5d');
    const d = await r.json();
    const rate = d?.chart?.result?.[0]?.meta?.regularMarketPrice;
    if (rate != null) {
      document.getElementById('gp-fed').value = rate.toFixed(2);
      if (status) status.textContent = '≈ T-Bill 13W';
      runGoldPrediction();
    } else if (status) status.textContent = 'không lấy được';
  } catch(e) {
    // CORS fallback: try alternative proxy
    try {
      const r2 = await fetch('https://query2.finance.yahoo.com/v8/finance/chart/%5EIRX?interval=1d&range=5d');
      const d2 = await r2.json();
      const rate2 = d2?.chart?.result?.[0]?.meta?.regularMarketPrice;
      if (rate2 != null) {
        document.getElementById('gp-fed').value = rate2.toFixed(2);
        if (status) status.textContent = '≈ T-Bill 13W';
        runGoldPrediction();
      } else if (status) status.textContent = 'lỗi kết nối';
    } catch { if (status) status.textContent = 'lỗi kết nối'; }
  }
  if (btn) { btn.textContent = '⟳ Lấy'; btn.disabled = false; }
}
function autoFillMarketData(){
  const prices = _goldData&&_goldData.prices ? _goldData.prices : {};
  const xau = prices['INTERNATIONAL:XAUUSD'] || Object.values(prices).find(function(p){return p.currency==='USD';});
  if (xau && xau.buy) document.getElementById('gp-xau').value = Number(xau.buy).toFixed(0);
  if (xau && xau.extra && xau.extra.usd_vnd) document.getElementById('gp-usd').value = Number(xau.extra.usd_vnd).toFixed(0);
  const btcEl = document.getElementById('gp-btc');
  if (btcEl && !btcEl.value) {
    fetch('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT')
      .then(r=>r.json()).then(d=>{if(d.price){btcEl.value=Number(d.price).toFixed(0);runGoldPrediction();}})
      .catch(()=>{});
  }
  if (!document.getElementById('gp-fed').value) fetchFedRate();
  runGoldPrediction();
}'''

if OLD_AUTO in content:
    content = content.replace(OLD_AUTO, NEW_AUTO)
    print('OK: fetchFedRate + autoFill updated')
else:
    print('FAIL: autoFillMarketData not found')

# ── 3. Use Fed rate in runGoldPrediction ─────────────────────────────────────
# After existing: const inf = parseDecimal(...) || 4.5;
OLD_INF_LINE = "  const inf    = parseDecimal(document.getElementById('gp-inf').value) || 4.5;"
NEW_INF_LINE = ("  const inf    = parseDecimal(document.getElementById('gp-inf').value) || 4.5;\n"
                "  const fedRate = parseDecimal(document.getElementById('gp-fed').value) || 0;")
if OLD_INF_LINE in content:
    content = content.replace(OLD_INF_LINE, NEW_INF_LINE, 1)
    print('OK: fedRate variable added to runGoldPrediction')
else:
    print('FAIL: inf line not found')

# ── 4. Show Fed Rate in the 'short' school output (sentiment row) ───────────
# Add a Fed Rate row after BB% row in the 'short' section
OLD_BB_ROW = ("         + '<div class=\"sum-row\"><span class=\"sum-label\">BB%</span>"
              "<span class=\"sum-val\">'+bbPct.toFixed(0)+'%'+(bbPct<25?' — day dai':bbPct>75?' — dinh dai':'')+'</span></div></div>'")
NEW_BB_ROW  = ("         + '<div class=\"sum-row\"><span class=\"sum-label\">BB%</span>"
               "<span class=\"sum-val\">'+bbPct.toFixed(0)+'%'+(bbPct<25?' — day dai':bbPct>75?' — dinh dai':'')+'</span></div>'\n"
               "         + (fedRate>0?'<div class=\"sum-row\"><span class=\"sum-label\">Fed Rate</span>"
               "<span class=\"sum-val\" style=\"color:'+(fedRate>4.5?'var(--sell)':fedRate<3?'var(--buy)':'var(--hold)')+'\">'+"
               "fedRate.toFixed(2)+'%'+(fedRate>4.5?' — that chat':fedRate<3?' — no long':'')+'</span></div>':'')\n"
               "         + '</div>'")
if OLD_BB_ROW in content:
    content = content.replace(OLD_BB_ROW, NEW_BB_ROW)
    print('OK: Fed Rate shown in short-term output')
else:
    print('WARN: BB% row pattern not found in short section')

# ── 5. Show Fed Rate in 'contrarian' school (macro section) ─────────────────
OLD_MACRO_INF = ("         + '<div class=\"sum-row\"><span class=\"sum-label\">Lam phat VN</span>"
                 "<span class=\"sum-val\" style=\"color:'+(inf>6?'var(--sell)':inf>4?'var(--hold)':'var(--buy)')+'\">'+"
                 "inf+'%/nam</span></div>'\n"
                 "         +'</div>';")
NEW_MACRO_INF  = ("         + '<div class=\"sum-row\"><span class=\"sum-label\">Lam phat VN</span>"
                  "<span class=\"sum-val\" style=\"color:'+(inf>6?'var(--sell)':inf>4?'var(--hold)':'var(--buy)')+'\">'+"
                  "inf+'%/nam</span></div>'\n"
                  "         + (fedRate>0?'<div class=\"sum-row\"><span class=\"sum-label\">Fed Rate</span>"
                  "<span class=\"sum-val\" style=\"color:'+(fedRate>4.5?'var(--sell)':fedRate<3?'var(--buy)':'var(--hold)')+'\">'+"
                  "fedRate.toFixed(2)+'%'+(fedRate>4.5?' — bat loi vang':fedRate<3?' — ho tro vang':'')+'</span></div>':'')\n"
                  "         +'</div>';")
if OLD_MACRO_INF in content:
    content = content.replace(OLD_MACRO_INF, NEW_MACRO_INF)
    print('OK: Fed Rate shown in contrarian macro section')
else:
    print('WARN: contrarian macro pattern not found')

open(HTML, 'w', encoding='utf-8').write(content)
print('\nDone.')
