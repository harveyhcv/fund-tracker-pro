"""Patch: Gold form redesign + CCQ date fix + autoFill BTC + gold chip color"""
import sys, os
ROOT = os.path.join(os.path.dirname(__file__), '..')
HTML = os.path.join(ROOT, 'telegram-bot', 'miniapp', 'index.html')
content = open(HTML, encoding='utf-8').read()

# ── 1. Replace Gold form HTML ────────────────────────────────────────────────
OLD_GOLD = '''    <!-- Gold form -->
    <div id="trade-sub-gold" style="display:none">
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
          <label style="margin:0">Giao dịch</label>
          <div id="gold-type-pill" onclick="toggleGoldType()" style="display:flex;align-items:center;width:120px;height:32px;border-radius:16px;border:1px solid var(--bdr);background:var(--bg2);position:relative;cursor:pointer;overflow:hidden">
            <div id="gold-pill-thumb" style="position:absolute;left:0;width:60px;height:100%;border-radius:16px;background:var(--buy);transition:left .2s"></div>
            <span style="position:relative;flex:1;text-align:center;font-size:12px;font-weight:700;color:#000;z-index:1">MUA</span>
            <span style="position:relative;flex:1;text-align:center;font-size:12px;font-weight:700;color:var(--txt2);z-index:1">BÁN</span>
          </div>
        </div>
        <label>Sản phẩm vàng</label>
        <select id="gold-product-select" onchange="onGoldProductChange()">
          <option value="SJC_1L">Vàng miếng SJC 9999 — 1 lượng</option>
          <option value="DOJI_NHAN_9999">Nhẫn tròn DOJI 9999 (HN)</option>
          <option value="DOJI_NHAN_HCM">Nhẫn tròn DOJI 9999 (HCM)</option>
          <option value="SJC_NHAN">Nhẫn tròn SJC 9999</option>
          <option value="PNJ_VANGMY">Nhẫn vàng mỹ PNJ</option>
          <option value="PNJ_24K">Nhẫn 24K PNJ 9999</option>
          <option value="BAOTINNGUYEN">Vàng nhẫn Bảo Tín 9999</option>
          <option value="VIETTIN_SJC">Vàng SJC tại Việt Tín</option>
          <option value="OTHER">Vàng khác (ghi rõ tên)</option>
        </select>
        <input type="text" id="gold-other-name" placeholder="Nhập tên sản phẩm vàng..." style="display:none;width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:8px;margin-bottom:8px;box-sizing:border-box;font-size:13px">
        <label>Đơn vị</label>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:4px" id="gold-unit-group">
          <div id="gold-unit-luong" onclick="setGoldUnit('luong')" style="padding:8px;border-radius:8px;border:1px solid var(--c0);background:#052e3a;color:var(--c0);text-align:center;cursor:pointer;font-size:12px">Lượng</div>
          <div id="gold-unit-chi" onclick="setGoldUnit('chi')" style="padding:8px;border-radius:8px;border:1px solid var(--bdr);background:var(--bg3);color:var(--txt2);text-align:center;cursor:pointer;font-size:12px">Chỉ</div>
          <div id="gold-unit-gram" onclick="setGoldUnit('gram')" style="padding:8px;border-radius:8px;border:1px solid var(--bdr);background:var(--bg3);color:var(--txt2);text-align:center;cursor:pointer;font-size:12px">Gram</div>
        </div>
        <label>Số lượng</label>
        <input type="text" inputmode="decimal" id="gold-qty" placeholder="VD: 1 (lượng)" oninput="calcGoldTotal()">
        <label>Giá mua/bán (VNĐ / lượng)</label>
        <input type="text" inputmode="decimal" id="gold-price" placeholder="VD: 89000000" oninput="calcGoldTotal()">
        <div id="gold-total-preview" style="display:none;color:var(--c0);font-size:13px;margin:8px 0;font-family:var(--mono)"></div>
        <label>Ngày giao dịch</label>
        <input type="date" id="gold-date-input">
        <button class="btn btn-buy" id="gold-submit-btn" onclick="submitGoldTrade()">XÁC NHẬN MUA</button>
      </div>
    </div>'''

NEW_GOLD = '''    <!-- Gold form -->
    <div id="trade-sub-gold" style="display:none">
      <div class="card">
        <!-- Hàng 1: Toggle + Sản phẩm + Ngày -->
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
          <div id="gold-type-pill" onclick="toggleGoldType()" style="flex-shrink:0;display:flex;align-items:center;width:100px;height:34px;border-radius:17px;border:1px solid var(--bdr);background:var(--bg2);position:relative;cursor:pointer;overflow:hidden">
            <div id="gold-pill-thumb" style="position:absolute;left:0;width:50px;height:100%;border-radius:17px;background:var(--buy);transition:left .2s"></div>
            <span style="position:relative;flex:1;text-align:center;font-size:11px;font-weight:700;color:#000;z-index:1;font-family:var(--mono)">MUA</span>
            <span style="position:relative;flex:1;text-align:center;font-size:11px;font-weight:700;color:var(--txt2);z-index:1;font-family:var(--mono)">BÁN</span>
          </div>
          <select id="gold-product-select" onchange="onGoldProductChange()" style="flex:1;min-width:0;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:6px 8px;font-size:12px;height:34px">
            <option value="SJC_1L">SJC 9999 (miếng)</option>
            <option value="DOJI_NHAN_9999">DOJI 9999 (HN)</option>
            <option value="DOJI_NHAN_HCM">DOJI 9999 (HCM)</option>
            <option value="SJC_NHAN">SJC 9999 (nhẫn)</option>
            <option value="PNJ_VANGMY">PNJ Vàng mỹ</option>
            <option value="PNJ_24K">PNJ 24K</option>
            <option value="BAOTINNGUYEN">Bảo Tín 9999</option>
            <option value="VIETTIN_SJC">Việt Tín SJC</option>
            <option value="OTHER">Vàng khác...</option>
          </select>
          <input type="date" id="gold-date-input" style="flex-shrink:0;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:6px 8px;font-size:12px;height:34px;box-sizing:border-box;width:130px">
        </div>
        <!-- Tên vàng khác (ẩn khi không cần) -->
        <input type="text" id="gold-other-name" placeholder="Nhập tên sản phẩm vàng..." style="display:none;width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:8px;margin-bottom:8px;box-sizing:border-box;font-size:13px">
        <!-- Hàng 2: Đơn vị + Số lượng + Tổng giá trị -->
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
          <div id="gold-unit-group" style="display:flex;gap:3px;flex-shrink:0">
            <div id="gold-unit-luong" onclick="setGoldUnit('luong')" style="padding:5px 9px;border-radius:6px;border:1px solid var(--c0);background:#052e3a;color:var(--c0);cursor:pointer;font-size:11px;font-family:var(--mono);font-weight:700">L</div>
            <div id="gold-unit-chi" onclick="setGoldUnit('chi')" style="padding:5px 9px;border-radius:6px;border:1px solid var(--bdr);background:var(--bg3);color:var(--txt2);cursor:pointer;font-size:11px;font-family:var(--mono);font-weight:700">C</div>
            <div id="gold-unit-gram" onclick="setGoldUnit('gram')" style="padding:5px 9px;border-radius:6px;border:1px solid var(--bdr);background:var(--bg3);color:var(--txt2);cursor:pointer;font-size:11px;font-family:var(--mono);font-weight:700">G</div>
          </div>
          <input type="text" inputmode="decimal" id="gold-qty" placeholder="Số lượng" oninput="calcGoldTotal()" style="flex:1;min-width:0;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:8px;font-size:13px;box-sizing:border-box">
          <input type="text" inputmode="numeric" id="gold-price" placeholder="Tổng giá trị (₫)" oninput="calcGoldTotal()" style="flex:1;min-width:0;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:8px;font-size:13px;box-sizing:border-box">
        </div>
        <div id="gold-total-preview" style="display:none;color:var(--c0);font-size:12px;margin:0 0 8px;font-family:var(--mono)"></div>
        <button class="btn btn-buy" id="gold-submit-btn" onclick="submitGoldTrade()">XÁC NHẬN MUA</button>
      </div>
    </div>'''

if OLD_GOLD in content:
    content = content.replace(OLD_GOLD, NEW_GOLD)
    print('OK: Gold form replaced')
else:
    print('WARN: Gold form not found exactly — check manually')

# ── 2. CCQ date: remove label div, fix date input height ────────────────────
OLD_CCQ_DATE = '''          <!-- Date -->
          <div style="flex-shrink:0;text-align:right">
            <div id="trade-date-label" style="font-size:10px;color:var(--txt2);margin-bottom:2px;font-family:var(--mono)">NGÀY MUA</div>
            <input type="date" id="trade-date" onchange="onTradeDateChange()" style="background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:4px 6px;font-size:12px;width:120px">
          </div>'''
NEW_CCQ_DATE = '''          <!-- Date -->
          <input type="date" id="trade-date" onchange="onTradeDateChange()" style="flex-shrink:0;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:6px 8px;font-size:12px;height:34px;box-sizing:border-box;width:130px">'''
if OLD_CCQ_DATE in content:
    content = content.replace(OLD_CCQ_DATE, NEW_CCQ_DATE)
    print('OK: CCQ date fixed')
else:
    print('WARN: CCQ date not found')

# ── 3. Remove trade-date-label JS reference ──────────────────────────────────
OLD_LABEL_JS = "  document.getElementById('trade-date-label').textContent=isBuy?'NGÀY MUA':'NGÀY BÁN';\n"
if OLD_LABEL_JS in content:
    content = content.replace(OLD_LABEL_JS, '')
    print('OK: trade-date-label JS removed')
else:
    print('WARN: trade-date-label JS not found')

# ── 4. calcGoldTotal: price field is now total value ────────────────────────
OLD_CALC = '''function calcGoldTotal() {
  const qty   = parseDecimal(document.getElementById('gold-qty').value);
  const price = parseDecimal(document.getElementById('gold-price').value);
  const el    = document.getElementById('gold-total-preview');
  const unitF = {'luong':1,'chi':0.1,'gram':1/37.5}[_goldUnit] || 1;
  if (qty > 0 && price > 0) {
    const total = qty * unitF * price;
    const qtyL  = qty * unitF;
    el.textContent = `${qtyL.toFixed(4)} lượng × ${price.toLocaleString('vi-VN')} ₫ = ${total.toLocaleString('vi-VN')} ₫`;
    el.style.display = 'block';
  } else { el.style.display = 'none'; }
}'''
NEW_CALC = '''function calcGoldTotal() {
  const qty   = parseDecimal(document.getElementById('gold-qty').value);
  const total = parseDecimal(document.getElementById('gold-price').value); // total VND
  const el    = document.getElementById('gold-total-preview');
  const unitF = {'luong':1,'chi':0.1,'gram':1/37.5}[_goldUnit] || 1;
  if (qty > 0 && total >= 0) {
    const qtyL = qty * unitF;
    const pricePerLuong = qtyL > 0 ? total / qtyL : 0;
    el.textContent = `${qtyL.toFixed(4)} lượng — giá/lượng: ${Math.round(pricePerLuong).toLocaleString('vi-VN')} ₫`;
    el.style.display = 'block';
  } else { el.style.display = 'none'; }
}'''
if OLD_CALC in content:
    content = content.replace(OLD_CALC, NEW_CALC)
    print('OK: calcGoldTotal updated')
else:
    print('WARN: calcGoldTotal not found')

# ── 5. submitGoldTrade: derive price_per_luong from total ───────────────────
OLD_SUBMIT = '''  const qty   = parseDecimal(document.getElementById('gold-qty').value);
  const price = parseDecimal(document.getElementById('gold-price').value);
  const dt    = document.getElementById('gold-date-input').value;
  if (!qty || qty <= 0) { toast('Nhập số lượng'); return; }
  if (price == null || price < 0) { toast('Nhập giá/lượng (≥ 0)'); return; }
  if (!dt) { toast('Chọn ngày giao dịch'); return; }
  let product = document.getElementById('gold-product-select')?.value || 'SJC_1L';
  if (product === 'OTHER') {
    const customName = document.getElementById('gold-other-name')?.value?.trim();
    if (!customName) { toast('Nhập tên sản phẩm vàng'); return; }
    product = 'OTHER:' + customName;
  }
  const unitF = {'luong':1,'chi':0.1,'gram':1/37.5}[_goldUnit] || 1;
  const total = Math.round(qty * unitF * price);'''
NEW_SUBMIT = '''  const qty   = parseDecimal(document.getElementById('gold-qty').value);
  const totalRaw = parseDecimal(document.getElementById('gold-price').value); // total VND
  const dt    = document.getElementById('gold-date-input').value;
  if (!qty || qty <= 0) { toast('Nhập số lượng'); return; }
  if (totalRaw == null || totalRaw < 0) { toast('Nhập tổng giá trị (≥ 0)'); return; }
  if (!dt) { toast('Chọn ngày giao dịch'); return; }
  let product = document.getElementById('gold-product-select')?.value || 'SJC_1L';
  if (product === 'OTHER') {
    const customName = document.getElementById('gold-other-name')?.value?.trim();
    if (!customName) { toast('Nhập tên sản phẩm vàng'); return; }
    product = 'OTHER:' + customName;
  }
  const unitF = {'luong':1,'chi':0.1,'gram':1/37.5}[_goldUnit] || 1;
  const qtyLuong = qty * unitF;
  const price = qtyLuong > 0 ? totalRaw / qtyLuong : 0; // price_per_luong derived
  const total = Math.round(totalRaw);'''
if OLD_SUBMIT in content:
    content = content.replace(OLD_SUBMIT, NEW_SUBMIT)
    print('OK: submitGoldTrade updated')
else:
    print('WARN: submitGoldTrade not found')

# ── 6. autoFillMarketData: also fill BTC ─────────────────────────────────────
OLD_AUTO = '''function autoFillMarketData(){
  const prices = _goldData&&_goldData.prices ? _goldData.prices : {};
  const xau = prices['INTERNATIONAL:XAUUSD'] || Object.values(prices).find(function(p){return p.currency==='USD';});
  if (xau && xau.buy) document.getElementById('gp-xau').value = Number(xau.buy).toFixed(0);
  if (xau && xau.extra && xau.extra.usd_vnd) document.getElementById('gp-usd').value = Number(xau.extra.usd_vnd).toFixed(0);
  runGoldPrediction();
}'''
NEW_AUTO = '''function autoFillMarketData(){
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
if OLD_AUTO in content:
    content = content.replace(OLD_AUTO, NEW_AUTO)
    print('OK: autoFillMarketData updated')
else:
    print('WARN: autoFillMarketData not found')

# ── 7. Gold chip: brighter gold color ───────────────────────────────────────
OLD_CHIP = 'background:#92400e;color:#fbbf24;'
NEW_CHIP = 'background:#78350f;color:#fde68a;border:1px solid #fbbf24;'
count = content.count(OLD_CHIP)
if count:
    content = content.replace(OLD_CHIP, NEW_CHIP)
    print(f'OK: Gold chip color updated ({count} occurrences)')
else:
    print('WARN: Gold chip not found')

# ── 8. setGoldUnit: update placeholder text ──────────────────────────────────
OLD_PLACEHOLDER = "  const placeholder = unit==='luong' ? 'VD: 1 (lượng)' : unit==='chi' ? 'VD: 5 (chỉ)' : 'VD: 37.5 (gram)';\n  document.getElementById('gold-qty').placeholder = placeholder;"
NEW_PLACEHOLDER = "  const ph = unit==='luong' ? 'Số lượng (lượng)' : unit==='chi' ? 'Số lượng (chỉ)' : 'Số lượng (gram)';\n  document.getElementById('gold-qty').placeholder = ph;"
if OLD_PLACEHOLDER in content:
    content = content.replace(OLD_PLACEHOLDER, NEW_PLACEHOLDER)
    print('OK: setGoldUnit placeholder updated')
else:
    print('WARN: setGoldUnit placeholder not found')

open(HTML, 'w', encoding='utf-8').write(content)
print('\nDone.')
