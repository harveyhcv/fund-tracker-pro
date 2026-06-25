"""Patch: 1) Gold unit dropdown (between qty/total, default=Chỉ)
          2) Admin NAV manual import panel inside token-modal"""
import os
ROOT = os.path.join(os.path.dirname(__file__), '..')
HTML = os.path.join(ROOT, 'telegram-bot', 'miniapp', 'index.html')
content = open(HTML, encoding='utf-8').read()

# ══════════════════════════════════════════════════════════════════════════════
# 1. GOLD UNIT: Replace L/C/G buttons with select between qty and total
# ══════════════════════════════════════════════════════════════════════════════
OLD_ROW2 = '''        <!-- Hàng 2: Đơn vị + Số lượng + Tổng giá trị -->
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
          <div id="gold-unit-group" style="display:flex;gap:3px;flex-shrink:0">
            <div id="gold-unit-luong" onclick="setGoldUnit('luong')" style="padding:5px 9px;border-radius:6px;border:1px solid var(--c0);background:#052e3a;color:var(--c0);cursor:pointer;font-size:11px;font-family:var(--mono);font-weight:700">L</div>
            <div id="gold-unit-chi" onclick="setGoldUnit('chi')" style="padding:5px 9px;border-radius:6px;border:1px solid var(--bdr);background:var(--bg3);color:var(--txt2);cursor:pointer;font-size:11px;font-family:var(--mono);font-weight:700">C</div>
            <div id="gold-unit-gram" onclick="setGoldUnit('gram')" style="padding:5px 9px;border-radius:6px;border:1px solid var(--bdr);background:var(--bg3);color:var(--txt2);cursor:pointer;font-size:11px;font-family:var(--mono);font-weight:700">G</div>
          </div>
          <input type="text" inputmode="decimal" id="gold-qty" placeholder="Số lượng" oninput="calcGoldTotal()" style="flex:1;min-width:0;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:8px;font-size:13px;box-sizing:border-box">
          <input type="text" inputmode="numeric" id="gold-price" placeholder="Tổng giá trị (₫)" oninput="calcGoldTotal()" style="flex:1;min-width:0;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:8px;font-size:13px;box-sizing:border-box">
        </div>'''

NEW_ROW2 = '''        <!-- Hàng 2: Số lượng + Đơn vị dropdown + Tổng giá trị -->
        <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px">
          <input type="text" inputmode="decimal" id="gold-qty" placeholder="Số lượng" oninput="calcGoldTotal()" style="flex:1;min-width:0;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:8px;font-size:13px;box-sizing:border-box">
          <select id="gold-unit-sel" onchange="setGoldUnit(this.value)" style="flex-shrink:0;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 6px;font-size:13px;height:38px;cursor:pointer">
            <option value="chi">Chỉ</option>
            <option value="luong">Lượng</option>
            <option value="gram">Gram</option>
          </select>
          <input type="text" inputmode="numeric" id="gold-price" placeholder="Tổng giá trị (₫)" oninput="calcGoldTotal()" style="flex:1;min-width:0;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:8px;font-size:13px;box-sizing:border-box">
        </div>'''

if OLD_ROW2 in content:
    content = content.replace(OLD_ROW2, NEW_ROW2)
    print('OK: Gold unit → dropdown')
else:
    print('FAIL: gold row2 not found')

# Update setGoldUnit JS — sync dropdown instead of div active states
OLD_SET_UNIT = '''function setGoldUnit(unit) {
  _goldUnit = unit;
  ['luong','chi','gram'].forEach(u => {
    const el = document.getElementById(`gold-unit-${u}`);
    if (u === unit) {
      el.style.borderColor = 'var(--c0)';
      el.style.background  = '#052e3a';
      el.style.color       = 'var(--c0)';
    } else {
      el.style.borderColor = 'var(--bdr)';
      el.style.background  = 'var(--bg3)';
      el.style.color       = 'var(--txt2)';
    }
  });
  const ph = unit==='luong' ? 'Số lượng (lượng)' : unit==='chi' ? 'Số lượng (chỉ)' : 'Số lượng (gram)';
  document.getElementById('gold-qty').placeholder = ph;
  calcGoldTotal();
}'''

NEW_SET_UNIT = '''function setGoldUnit(unit) {
  _goldUnit = unit;
  const sel = document.getElementById('gold-unit-sel');
  if (sel && sel.value !== unit) sel.value = unit;
  const ph = unit==='luong' ? 'Số lượng (lượng)' : unit==='chi' ? 'Số lượng (chỉ)' : 'Số lượng (gram)';
  document.getElementById('gold-qty').placeholder = ph;
  calcGoldTotal();
}'''

if OLD_SET_UNIT in content:
    content = content.replace(OLD_SET_UNIT, NEW_SET_UNIT)
    print('OK: setGoldUnit updated')
else:
    print('FAIL: setGoldUnit not found')

# Change default _goldUnit from 'luong' to 'chi'
content = content.replace("let _goldUnit = 'luong'", "let _goldUnit = 'chi'", 1)
if "let _goldUnit = 'chi'" in content:
    print('OK: default unit → chi')
else:
    print('WARN: _goldUnit default not found, may already be chi')

# ══════════════════════════════════════════════════════════════════════════════
# 2. ADMIN NAV IMPORT — add to token-modal
# ══════════════════════════════════════════════════════════════════════════════
OLD_MODAL_END = '''    <button onclick="triggerFetchAllNav()" style="width:100%;padding:10px;background:var(--bg3);color:var(--buy);border:1px solid var(--buy);border-radius:8px;font-weight:700;font-size:13px;cursor:pointer;font-family:var(--mono)">⟳ FETCH ALL FUNDS (fmarket + TCBS)</button>
  </div>
</div>'''

NEW_MODAL_END = '''    <button onclick="triggerFetchAllNav()" style="width:100%;padding:10px;background:var(--bg3);color:var(--buy);border:1px solid var(--buy);border-radius:8px;font-weight:700;font-size:13px;cursor:pointer;font-family:var(--mono)">⟳ FETCH ALL FUNDS (fmarket + TCBS)</button>

    <!-- Manual NAV Import -->
    <div style="margin-top:18px;border-top:1px solid #1e3a5f;padding-top:14px">
      <div style="font-size:12px;font-weight:700;color:#fbbf24;margin-bottom:10px;font-family:var(--mono)">NHẬP NAV THỦ CÔNG</div>
      <div style="display:flex;gap:6px;margin-bottom:8px;align-items:center">
        <input type="text" id="nav-import-code" placeholder="Mã quỹ (VD: TCFF)" oninput="this.value=this.value.toUpperCase()" style="flex:1;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:7px 8px;font-size:13px;font-family:var(--mono)">
        <button onclick="navAddRow()" style="flex-shrink:0;padding:7px 12px;background:#1e3a5f;border:1px solid #2563eb;color:#93c5fd;border-radius:8px;font-size:12px;cursor:pointer;white-space:nowrap">+ Thêm hàng</button>
      </div>
      <div id="nav-import-rows" style="max-height:220px;overflow-y:auto;display:flex;flex-direction:column;gap:5px;margin-bottom:8px"></div>
      <div style="font-size:10px;color:var(--txt2);margin-bottom:8px">Mỗi hàng: ngày + NAV/CCQ. Sẽ bỏ qua nếu ngày đã tồn tại trong DB.</div>
      <button onclick="navSubmitImport()" style="width:100%;padding:10px;background:#1a3a1a;color:var(--buy);border:1px solid var(--buy);border-radius:8px;font-weight:700;font-size:13px;cursor:pointer;font-family:var(--mono)">💾 LƯU VÀO DATABASE</button>
      <div id="nav-import-status" style="font-size:12px;color:var(--txt2);margin-top:8px;min-height:16px;font-family:var(--mono)"></div>
    </div>
  </div>
</div>'''

if OLD_MODAL_END in content:
    content = content.replace(OLD_MODAL_END, NEW_MODAL_END)
    print('OK: Admin NAV import panel added to token-modal')
else:
    print('FAIL: token-modal end not found')

# ── Add navAddRow + navSubmitImport JS ─────────────────────────────────────
OLD_SUBMIT_TOKEN_END = '''async function triggerFetchAllNav(){'''

NEW_NAV_JS = '''function navAddRow(){
  const rows = document.getElementById('nav-import-rows');
  const today = new Date().toISOString().split('T')[0];
  const row = document.createElement('div');
  row.style = 'display:flex;gap:5px;align-items:center';
  row.innerHTML = `<input type="date" value="${today}" style="flex:1;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:6px;padding:6px 7px;font-size:12px;min-width:0"><input type="text" inputmode="decimal" placeholder="NAV/CCQ" style="flex:1;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:6px;padding:6px 7px;font-size:12px;min-width:0;font-family:var(--mono)"><button onclick="this.closest('div').remove()" style="flex-shrink:0;padding:4px 8px;background:none;border:1px solid #374151;color:#9ca3af;border-radius:6px;font-size:14px;cursor:pointer;line-height:1">×</button>`;
  rows.appendChild(row);
}
async function navSubmitImport(){
  const code = (document.getElementById('nav-import-code').value||'').trim().toUpperCase();
  const status = document.getElementById('nav-import-status');
  if (!code) { status.style.color='var(--sell)'; status.textContent='Nhập mã quỹ'; return; }
  const rowEls = document.querySelectorAll('#nav-import-rows > div');
  const navList = [];
  rowEls.forEach(row => {
    const inputs = row.querySelectorAll('input');
    const date = inputs[0]?.value;
    const nav = parseFloat((inputs[1]?.value||'').replace(/,/g,''));
    if (date && nav > 0) navList.push({ date, nav });
  });
  if (!navList.length) { status.style.color='var(--sell)'; status.textContent='Chưa có hàng nào hợp lệ'; return; }
  status.style.color='var(--txt2)'; status.textContent=`Đang lưu ${navList.length} điểm NAV cho ${code}...`;
  try {
    const res = await fetch(`${API_BASE}/api/admin/import-nav`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ funds: { [code]: navList } })
    });
    const d = await res.json();
    if (d.ok || d.total !== undefined) {
      const ins = d.inserted?.[code] ?? d.total ?? navList.length;
      status.style.color='var(--buy)'; status.textContent=`✓ Đã lưu ${ins} điểm NAV cho ${code}`;
      tg?.HapticFeedback?.notificationOccurred('success');
    } else { status.style.color='var(--sell)'; status.textContent='Lỗi: '+(d.error||'unknown'); }
  } catch(e) { status.style.color='var(--sell)'; status.textContent='Lỗi kết nối: '+e.message; }
}
async function triggerFetchAllNav(){'''

if OLD_SUBMIT_TOKEN_END in content:
    content = content.replace(OLD_SUBMIT_TOKEN_END, NEW_NAV_JS)
    print('OK: navAddRow + navSubmitImport JS added')
else:
    print('FAIL: triggerFetchAllNav marker not found')

open(HTML, 'w', encoding='utf-8').write(content)
print('\nDone.')
