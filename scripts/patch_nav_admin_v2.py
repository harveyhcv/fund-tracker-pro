"""
Patch v2:
1. Remove NAV import from token-modal
2. Add "Nhập NAV thủ công" + "Cập nhật tự động" buttons below hist-chart
3. New standalone nav-import-modal (1 fund, dynamic date rows)
4. New tcbs-token-mini-modal (quick token entry for auto-update flow)
5. JS: autoUpdateNav, openNavImport, navImportAddRow, navImportSubmit, crossCheckNav
"""
import os
ROOT = os.path.join(os.path.dirname(__file__), '..')
HTML = os.path.join(ROOT, 'telegram-bot', 'miniapp', 'index.html')
c = open(HTML, encoding='utf-8').read()
ok = []
fail = []

def rep(old, new, label):
    global c
    if old in c:
        c = c.replace(old, new, 1)
        ok.append(label)
    else:
        fail.append(label)

# ══════════════════════════════════════════════════════════════════════════════
# 1. Remove NAV import block from token-modal
# ══════════════════════════════════════════════════════════════════════════════
rep(
    '''
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
    </div>''',
    '',
    'Removed NAV import from token-modal'
)

# ══════════════════════════════════════════════════════════════════════════════
# 2. Add action buttons BELOW chart in History page
# ══════════════════════════════════════════════════════════════════════════════
rep(
    '    <div id="hist-content"></div>\n    <div class="chart-wrap"><canvas id="hist-chart"></canvas></div>\n  </div>\n</div>',
    '''    <div id="hist-content"></div>
    <div class="chart-wrap"><canvas id="hist-chart"></canvas></div>
    <!-- Admin action buttons below chart -->
    <div id="hist-admin-btns" style="display:flex;gap:8px;margin-top:10px">
      <button onclick="openNavImport()" style="flex:1;padding:9px 0;background:var(--bg3);border:1px solid var(--bdr);color:var(--txt2);border-radius:8px;font-size:12px;cursor:pointer;font-family:var(--mono)">✏️ Nhập NAV thủ công</button>
      <button onclick="autoUpdateNav()" style="flex:1;padding:9px 0;background:var(--bg3);border:1px solid var(--c0);color:var(--c0);border-radius:8px;font-size:12px;cursor:pointer;font-family:var(--mono)">⟳ Cập nhật tự động</button>
    </div>
    <div id="hist-auto-status" style="font-size:11px;color:var(--txt2);margin-top:6px;min-height:14px;font-family:var(--mono)"></div>
  </div>
</div>''',
    'Admin buttons added below hist-chart'
)

# ══════════════════════════════════════════════════════════════════════════════
# 3. New modals: nav-import-modal + tcbs-token-mini-modal
#    Insert before closing </body> or before nav#nav
# ══════════════════════════════════════════════════════════════════════════════
NEW_MODALS = '''
<!-- NAV Import Modal (standalone, from History page) -->
<div id="nav-import-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:2000;overflow-y:auto">
  <div style="background:#0d1b2a;margin:40px 16px 80px;border-radius:12px;padding:20px;border:1px solid #1e3a5f">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
      <div style="font-size:13px;font-weight:700;color:#fbbf24;font-family:var(--mono)">NHẬP NAV THỦ CÔNG — <span id="nav-import-title">...</span></div>
      <button onclick="closeNavImport()" style="background:none;border:none;color:var(--txt2);font-size:22px;cursor:pointer;line-height:1">×</button>
    </div>
    <div style="font-size:11px;color:var(--txt2);margin-bottom:12px;line-height:1.5">Mỗi hàng: 1 ngày + NAV/CCQ tương ứng. DB sẽ bỏ qua nếu ngày đã tồn tại, và tự động cross-check với dữ liệu nguồn sau khi lưu.</div>
    <input type="hidden" id="nav-import-code">
    <div id="nav-import-rows" style="display:flex;flex-direction:column;gap:6px;margin-bottom:10px;max-height:50vh;overflow-y:auto"></div>
    <button onclick="navImportAddRow()" style="width:100%;padding:9px;background:#0d2234;border:1px solid #1e3a5f;color:#93c5fd;border-radius:8px;font-size:13px;cursor:pointer;margin-bottom:12px">+ Thêm ngày</button>
    <button onclick="navImportSubmit()" style="width:100%;padding:12px;background:#0a2a0a;color:var(--buy);border:1px solid var(--buy);border-radius:8px;font-weight:700;font-size:14px;cursor:pointer;font-family:var(--mono)">💾 LƯU VÀO DATABASE & CROSS-CHECK</button>
    <div id="nav-import-status" style="font-size:12px;color:var(--txt2);margin-top:10px;min-height:16px;font-family:var(--mono);white-space:pre-wrap"></div>
  </div>
</div>

<!-- TCBS Token Mini Modal (quick token for auto-update flow) -->
<div id="tcbs-mini-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:2100;display:none;align-items:center;justify-content:center">
  <div style="background:#0d1b2a;width:calc(100% - 32px);max-width:420px;border-radius:12px;padding:20px;border:1px solid #f59e0b;margin:auto;position:relative;top:20%">
    <div style="font-size:13px;font-weight:700;color:#f59e0b;margin-bottom:8px;font-family:var(--mono)">TOKEN TCBS HẾT HẠN</div>
    <div style="font-size:11px;color:var(--txt2);margin-bottom:12px;line-height:1.5">Vào TCInvest → F12 → Network → tìm request có Authorization → copy Bearer token.</div>
    <textarea id="tcbs-mini-token" rows="4" placeholder="Paste JWT token ở đây..." style="width:100%;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:8px;padding:10px;font-size:11px;font-family:var(--mono);resize:none;box-sizing:border-box;margin-bottom:10px"></textarea>
    <div style="display:flex;gap:8px">
      <button onclick="tcbsMiniSkip()" style="flex:1;padding:10px;background:var(--bg3);border:1px solid var(--bdr);color:var(--txt2);border-radius:8px;cursor:pointer;font-size:13px">Bỏ qua TCBS</button>
      <button onclick="tcbsMiniSubmit()" style="flex:2;padding:10px;background:#f59e0b;color:#000;border:none;border-radius:8px;font-weight:700;font-size:13px;cursor:pointer;font-family:var(--mono)">CẬP NHẬT & FETCH</button>
    </div>
    <div id="tcbs-mini-status" style="font-size:11px;color:var(--txt2);margin-top:8px;min-height:14px"></div>
  </div>
</div>

'''

rep(
    '<!-- Token Update Modal -->',
    NEW_MODALS + '<!-- Token Update Modal -->',
    'New modals inserted'
)

# ══════════════════════════════════════════════════════════════════════════════
# 4. Replace old navAddRow + navSubmitImport with new JS + add new functions
# ══════════════════════════════════════════════════════════════════════════════
OLD_NAV_JS = '''function navAddRow(){
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
}'''

NEW_NAV_JS = '''// ── NAV Import Modal ──────────────────────────────────────────────────────
function openNavImport(){
  const code = _histCode || '';
  document.getElementById('nav-import-code').value = code;
  document.getElementById('nav-import-title').textContent = code || '(chọn quỹ ở tab)';
  document.getElementById('nav-import-rows').innerHTML = '';
  document.getElementById('nav-import-status').textContent = '';
  navImportAddRow(); // 1 hàng mặc định
  document.getElementById('nav-import-modal').style.display = 'block';
}
function closeNavImport(){
  document.getElementById('nav-import-modal').style.display = 'none';
}
function navImportAddRow(){
  const rows = document.getElementById('nav-import-rows');
  const today = new Date().toISOString().split('T')[0];
  const row = document.createElement('div');
  row.className = 'nav-row';
  row.style.cssText = 'display:flex;gap:6px;align-items:center';
  const INP = 'background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:6px;padding:7px 8px;font-size:13px;min-width:0;box-sizing:border-box';
  row.innerHTML = `<input type="date" value="${today}" style="${INP};flex:1.2"><input type="text" inputmode="decimal" placeholder="NAV/CCQ" style="${INP};flex:1;font-family:var(--mono)"><button onclick="this.closest('.nav-row').remove()" style="flex-shrink:0;width:30px;height:30px;background:none;border:1px solid #374151;color:#6b7280;border-radius:6px;font-size:16px;cursor:pointer;line-height:1;padding:0">×</button>`;
  rows.appendChild(row);
  // Auto-scroll to bottom
  rows.scrollTop = rows.scrollHeight;
}
// Legacy alias for old code
function navAddRow(){ navImportAddRow(); }

async function navImportSubmit(){
  const code = (document.getElementById('nav-import-code').value||'').trim().toUpperCase();
  const statusEl = document.getElementById('nav-import-status');
  if (!code) { statusEl.style.color='var(--sell)'; statusEl.textContent='Chưa có mã quỹ'; return; }
  const rowEls = document.querySelectorAll('#nav-import-rows .nav-row');
  const navList = [];
  rowEls.forEach(row => {
    const [dateInp, navInp] = row.querySelectorAll('input');
    const date = dateInp?.value;
    const nav = parseFloat((navInp?.value||'').replace(/,/g,'').replace(/\./g,'').replace(/\s/g,''));
    if (date && nav > 0) navList.push({ date, nav });
  });
  if (!navList.length) { statusEl.style.color='var(--sell)'; statusEl.textContent='Chưa có hàng hợp lệ'; return; }
  statusEl.style.color='var(--txt2)'; statusEl.textContent=`Dang luu ${navList.length} diem NAV cho ${code}...`;
  try {
    const res = await fetch(`${API_BASE}/api/admin/import-nav`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ funds: { [code]: navList } })
    });
    const d = await res.json();
    const ins = d.inserted?.[code] ?? d.total ?? navList.length;
    statusEl.style.color = 'var(--buy)';
    statusEl.textContent = `Luu ${ins} diem. Dang cross-check...`;
    tg?.HapticFeedback?.notificationOccurred('success');
    // Reload chart data then cross-check
    await crossCheckNav(code, navList);
  } catch(e) { statusEl.style.color='var(--sell)'; statusEl.textContent='Loi ket noi: '+e.message; }
}
// Legacy alias
async function navSubmitImport(){ await navImportSubmit(); }

async function crossCheckNav(code, manualList){
  const statusEl = document.getElementById('nav-import-status');
  try {
    // Reload fresh DB data
    const data = await apiFetch('/api/nav/' + code);
    const dbMap = {};
    (data.data||[]).forEach(p => { dbMap[p.date] = p.nav; });
    const issues = [];
    manualList.forEach(m => {
      const dbVal = dbMap[m.date];
      if (dbVal == null) {
        issues.push(`${m.date}: chua co trong DB`);
      } else {
        const diff = Math.abs(dbVal - m.nav) / m.nav * 100;
        if (diff > 0.5) {
          issues.push(`${m.date}: thu cong=${m.nav.toLocaleString()} | DB=${Math.round(dbVal).toLocaleString()} | lech ${diff.toFixed(2)}%`);
        }
      }
    });
    if (issues.length) {
      statusEl.style.color = '#f59e0b';
      statusEl.textContent = 'CANH BAO chenh lech:\n' + issues.join('\n');
    } else {
      statusEl.style.color = 'var(--buy)';
      statusEl.textContent += '\nCross-check OK - du lieu khop.';
    }
    // Also reload the chart
    if (_histCode === code) { _histAllPoints = data.data||[]; applyDateRange(); }
  } catch(e) {
    statusEl.textContent += '\n(Cross-check loi: ' + e.message + ')';
  }
}

// ── Auto-update NAV ────────────────────────────────────────────────────────
let _fetchNavSkipTcbs = false;
async function autoUpdateNav(){
  const statusEl = document.getElementById('hist-auto-status');
  const btn = document.querySelector('[onclick="autoUpdateNav()"]');
  if (btn) { btn.textContent = '...'; btn.disabled = true; }
  statusEl.style.color = 'var(--c0)';
  statusEl.textContent = 'Dang fetch du lieu tu tat ca nguon...';
  _fetchNavSkipTcbs = false;
  try {
    const res = await fetch(`${API_BASE}/api/admin/fetch-nav`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ skip_tcbs: false })
    });
    const d = await res.json();
    if (d.ok) {
      statusEl.style.color = 'var(--buy)';
      statusEl.textContent = 'Dang fetch trong nen. Doi 1-2 phut roi lam moi app.';
    } else if (d.error === 'token_expired' || d.tcbs_error?.includes('token')) {
      // Token expired -> show mini modal
      statusEl.textContent = 'Token TCBS het han - hien popup...';
      showTcbsMiniModal();
    } else {
      statusEl.style.color = 'var(--sell)';
      statusEl.textContent = 'Loi: ' + (d.error || 'unknown');
    }
  } catch(e) {
    statusEl.style.color = 'var(--sell)';
    statusEl.textContent = 'Loi ket noi: ' + e.message;
  }
  if (btn) { btn.textContent = '⟳ Cap nhat tu dong'; btn.disabled = false; }
  // Reload chart after short delay
  setTimeout(() => { if(_histCode) loadHistChart(_histCode); }, 5000);
}
function showTcbsMiniModal(){
  document.getElementById('tcbs-mini-modal').style.display = 'flex';
  document.getElementById('tcbs-mini-token').value = '';
  document.getElementById('tcbs-mini-status').textContent = '';
}
async function tcbsMiniSubmit(){
  const token = (document.getElementById('tcbs-mini-token').value||'').trim();
  const st = document.getElementById('tcbs-mini-status');
  if (!token) { st.textContent = 'Paste token truoc'; return; }
  st.textContent = 'Dang cap nhat token...';
  try {
    const r1 = await fetch(`${API_BASE}/api/admin/settoken`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});
    const d1 = await r1.json();
    if (!d1.ok) { st.style.color='var(--sell)'; st.textContent='Loi: '+(d1.error||'?'); return; }
    st.style.color = 'var(--buy)'; st.textContent = 'Token OK. Dang fetch tat ca...';
    const r2 = await fetch(`${API_BASE}/api/admin/fetch-nav`, {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const d2 = await r2.json();
    st.textContent = d2.ok ? 'Dang fetch trong nen. Dong popup sau 3s.' : 'Loi fetch: '+(d2.error||'?');
    setTimeout(()=>{ document.getElementById('tcbs-mini-modal').style.display='none'; if(_histCode)loadHistChart(_histCode); }, 3000);
  } catch(e) { st.style.color='var(--sell)'; st.textContent='Loi: '+e.message; }
}
async function tcbsMiniSkip(){
  document.getElementById('tcbs-mini-modal').style.display = 'none';
  const statusEl = document.getElementById('hist-auto-status');
  statusEl.style.color = 'var(--c0)';
  statusEl.textContent = 'Fetch fmarket (bo qua TCBS)...';
  try {
    const res = await fetch(`${API_BASE}/api/admin/fetch-nav`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({skip_tcbs:true})});
    const d = await res.json();
    statusEl.style.color = d.ok ? 'var(--buy)' : 'var(--sell)';
    statusEl.textContent = d.ok ? 'Dang fetch fmarket trong nen.' : 'Loi: '+(d.error||'?');
    if (_histCode) setTimeout(()=>loadHistChart(_histCode), 4000);
  } catch(e) { statusEl.textContent = 'Loi: '+e.message; }
}'''

rep(OLD_NAV_JS, NEW_NAV_JS, 'navAddRow/navSubmitImport replaced with full nav import system')

# ══════════════════════════════════════════════════════════════════════════════
# 5. Update triggerFetchAllNav to use hist-auto-status if available
# ══════════════════════════════════════════════════════════════════════════════
rep(
    '''async function triggerFetchAllNav(){
  const statusEl = document.getElementById('token-status');
  statusEl.style.color = 'var(--c0)';
  statusEl.textContent = 'Dang kich hoat fetch NAV tat ca quy...';
  try {
    const res = await fetch(`${API_BASE}/api/admin/fetch-nav`, {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
    const d = await res.json();
    if (d.ok) {
      statusEl.style.color = 'var(--buy)';
      statusEl.textContent = 'Dang fetch NAV trong nen. Doi 1-2 phut roi lam moi app.';
    } else {
      statusEl.style.color = 'var(--sell)';
      statusEl.textContent = 'Loi: ' + (d.error || 'unknown');
    }
  } catch(e) {
    statusEl.style.color = 'var(--sell)';
    statusEl.textContent = 'Loi ket noi: ' + e.message;
  }
}''',
    '''async function triggerFetchAllNav(){
  const statusEl = document.getElementById('token-status') || document.getElementById('hist-auto-status');
  if (statusEl) { statusEl.style.color='var(--c0)'; statusEl.textContent='Dang kich hoat fetch NAV tat ca quy...'; }
  try {
    const res = await fetch(`${API_BASE}/api/admin/fetch-nav`, {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
    const d = await res.json();
    if (statusEl) {
      statusEl.style.color = d.ok ? 'var(--buy)' : 'var(--sell)';
      statusEl.textContent = d.ok ? 'Dang fetch NAV trong nen. Doi 1-2 phut roi lam moi app.' : 'Loi: '+(d.error||'unknown');
    }
  } catch(e) {
    if (statusEl) { statusEl.style.color='var(--sell)'; statusEl.textContent='Loi ket noi: '+e.message; }
  }
}''',
    'triggerFetchAllNav updated'
)

# ══════════════════════════════════════════════════════════════════════════════
# 6. miniapp_server.py — add skip_tcbs support to fetch-nav endpoint
# ══════════════════════════════════════════════════════════════════════════════
SRV = os.path.join(ROOT, 'telegram-bot', 'miniapp_server.py')
srv = open(SRV, encoding='utf-8').read()

OLD_FETCH_NAV = '        elif path == "/api/admin/fetch-nav":\n            self._api_admin_fetch_nav(data)'
NEW_FETCH_NAV = '        elif path == "/api/admin/fetch-nav":\n            self._api_admin_fetch_nav(data)'

# Find and update _api_admin_fetch_nav to support skip_tcbs
# Also improve to return token_expired error
OLD_SRV_FN = '    def _api_admin_fetch_nav(self, data):'
if OLD_SRV_FN in srv:
    ok.append('miniapp_server.py: _api_admin_fetch_nav found (check manually for skip_tcbs support)')
else:
    fail.append('miniapp_server.py: _api_admin_fetch_nav NOT found')

# ══════════════════════════════════════════════════════════════════════════════
# Write HTML
# ══════════════════════════════════════════════════════════════════════════════
open(HTML, 'w', encoding='utf-8').write(c)

print('OK:', ok)
print('FAIL:', fail if fail else 'none')
