// ── Config ──────────────────────────────────────────────────────────────────
const API_BASE = window.location.origin;
const qs = new URLSearchParams(location.search);
const USER_ID   = qs.get('user_id') || '';
const USER_NAME = qs.get('name') || '';
const IS_DEV    = qs.get('dev') === '1' || location.hash === '#dev';

// ── State ────────────────────────────────────────────────────────────────────
let _me = null, _signals = null, _goldData = null, _allFunds = {}, _watchedSet = new Set();
let _tradeType = 'buy', _goldType = 'buy', _goldUnit = 'chi', _goldPredType = 'buy';
let _dcaStyle = 'dca', _tradeLog = [], _marketFilter = 'all', _marketData = null;
let _navChart = null, _homeChart = null, _discBenefitType = 'discount_pct', _discRequiresPurchase = true;
let _selectedPlan = 'm1', _toastTimer;

// ── Dev mock data ─────────────────────────────────────────────────────────────
const MOCK_ME = {
  name: 'Harvey Nguyen', telegram_id: 111111111, tier: 'pro', is_admin: true,
  pro_expires_at: '2027-01-01T00:00:00',
  portfolio: {
    total_cost: 85203600, total_value: 103522225, total_pnl: 18318625, total_pnl_pct: 21.5,
    items: [
      {code:'VHIZ',  nav:18450, units:850.5,  avg_cost:15200, cost:12943600, value:15691725, pnl:2748125,  pnl_pct:21.2, chg_pct:0.12,  signal:'MUA MANH'},
      {code:'VESAF', nav:22100, units:1200,   avg_cost:19500, cost:23400000, value:26520000, pnl:3120000,  pnl_pct:13.3, chg_pct:-0.05, signal:'MUA'},
      {code:'VCBFTBF',nav:14320,units:2000,  avg_cost:14100, cost:28200000, value:28640000, pnl:440000,   pnl_pct:1.6,  chg_pct:0.08,  signal:'TRUNG LAP'},
      {code:'VFMVF1',nav:31200, units:500,   avg_cost:28000, cost:14000000, value:15600000, pnl:1600000,  pnl_pct:11.4, chg_pct:0.22,  signal:'MUA'},
      {code:'VFMVSF',nav:16800, units:360,   avg_cost:18500, cost:6660000,  value:6048000,  pnl:-612000,  pnl_pct:-9.2, chg_pct:-0.33, signal:'BAN MANH'},
    ]
  }
};
const MOCK_GOLD = {
  portfolio: {
    total_luong: 3.5, total_cost: 280000000, current_value: 303800000, pnl: 23800000, pnl_pct: 8.5,
    by_product: {
      'SJC_1L':        {label:'Vang mieng SJC 9999', luong:2.0, avg_cost:72000000, price_buy:87000000, value:174000000, pnl:30000000, pnl_pct:20.8, price_missing:false},
      'DOJI_NHAN_9999':{label:'Nhan tron DOJI 9999',  luong:1.5, avg_cost:72800000, price_buy:86600000, value:129900000, pnl:20700000, pnl_pct:18.9, price_missing:false},
    }
  },
  prices: {'VANGTODAYAPI:SJC_1L':87000000,'VANGTODAYAPI:DOJI_NHAN_9999':86600000}
};
const MOCK_SIGNALS = {
  VHIZ:    {nav:18450, chg_pct:0.12,  rsi:38, bb_pct:22, macd:0.03,  score:4,  signal:'MUA MANH',  has_position:true},
  VESAF:   {nav:22100, chg_pct:-0.05, rsi:52, bb_pct:48, macd:-0.01, score:2,  signal:'MUA',       has_position:true},
  VCBFTBF: {nav:14320, chg_pct:0.08,  rsi:50, bb_pct:51, macd:0.0,   score:0,  signal:'TRUNG LAP', has_position:true},
  VFMVF1:  {nav:31200, chg_pct:0.22,  rsi:62, bb_pct:67, macd:0.05,  score:3,  signal:'MUA',       has_position:true},
  VFMVSF:  {nav:16800, chg_pct:-0.33, rsi:72, bb_pct:81, macd:-0.04, score:-4, signal:'BAN MANH',  has_position:true},
  MAFBAL:  {nav:25600, chg_pct:0.15,  rsi:44, bb_pct:35, macd:0.02,  score:3,  signal:'MUA',       has_position:false},
  TCEF:    {nav:18900, chg_pct:-0.08, rsi:58, bb_pct:62, macd:-0.02, score:-1, signal:'TRUNG LAP', has_position:false},
  SSIBF1:  {nav:12100, chg_pct:0.05,  rsi:41, bb_pct:28, macd:0.01,  score:2,  signal:'MUA',       has_position:false},
  BVBF:    {nav:21300, chg_pct:-0.11, rsi:65, bb_pct:73, macd:-0.03, score:-2, signal:'BAN',       has_position:false},
  VNDBF:   {nav:10250, chg_pct:0.03,  rsi:49, bb_pct:45, macd:0.0,   score:1,  signal:'TRUNG LAP', has_position:false},
};
const MOCK_HISTORY = [
  {id:1, asset_type:'ccq', fund_code:'VHIZ',  trade_type:'buy', amount:12943600, nav:15200, units:851.6,  trade_date:'2024-03-15', note:''},
  {id:2, asset_type:'ccq', fund_code:'VESAF', trade_type:'buy', amount:23400000, nav:19500, units:1200.0, trade_date:'2024-05-20', note:''},
  {id:3, asset_type:'gold',gold_product:'SJC_1L', trade_type:'buy', units:2.0, price:72000000, trade_date:'2024-06-10', name:''},
  {id:4, asset_type:'ccq', fund_code:'VFMVF1',trade_type:'buy', amount:14000000, nav:28000, units:500.0,  trade_date:'2024-08-01', note:''},
];
const MOCK_DISCOUNTS = [
  {code:'WELCOME30', benefit_type:'discount_pct', benefit_value:30, is_active:true, requires_purchase:false, uses_count:5, max_uses:null, valid_until:null, note:'Welcome promo'},
  {code:'BETA50',    benefit_type:'free_days',    benefit_value:50, is_active:true, requires_purchase:false, uses_count:2, max_uses:10,   valid_until:'2026-12-31T00:00:00', note:'Beta users'},
];

const GOLD_PRODUCTS = [
  {value:'SJC_1L',         label:'Vang mieng SJC 9999 - 1 luong'},
  {value:'DOJI_NHAN_9999', label:'Nhan tron DOJI 9999 (HN)'},
  {value:'DOJI_NHAN_HCM',  label:'Nhan tron DOJI 9999 (HCM)'},
  {value:'DOJI_JEWELRY',   label:'DOJI Jewelry'},
  {value:'SJC_NHAN',       label:'Nhan tron SJC 9999'},
  {value:'PNJ_HN',         label:'PNJ Ha Noi'},
  {value:'PNJ_24K',        label:'Nhan 24K PNJ 9999'},
  {value:'BAOTINNGUYEN',   label:'Vang nhan Bao Tin 9999'},
  {value:'BAOTINSJC',      label:'Vang SJC tai Bao Tin'},
  {value:'OTHER',          label:'Vang khac'},
];

const PRO_PLANS = {
  m1:  {label:'1 thang',  stars:99,  days:30,  vnd:49000,  discount:0},
  m3:  {label:'3 thang',  stars:249, days:90,  vnd:129000, discount:12},
  y1:  {label:'1 nam',    stars:849, days:365, vnd:429000, discount:27},
};

const DCA_DESCS = {
  dca:  '<b>DCA (Dollar Cost Averaging)</b> — Dau tu co dinh moi ky. Don gian, hieu qua lau dai, khong can phan tich.',
  vca:  '<b>VCA (Value Cost Averaging)</b> — Dau tu nhieu hon khi gia thap, it hon khi gia cao. Toi uu hon DCA thuong.',
  ca:   '<b>CA (Cost Averaging)</b> — Mua them de ha gia von trung binh. Phu hop khi quy dang giam.',
  lump: '<b>LUMP SUM</b> — Dau tu mot lan toan bo von. Hieu qua nhat khi thi truong dang o day thap.',
  smart:'<b>SMART (AI Mix)</b> — Ket hop VCA + tin hieu RSI/MACD. Phan bo theo diem tin hieu moi quy.',
};

// ── Utils ────────────────────────────────────────────────────────────────────
const fmt   = n => n == null ? '—' : Number(n).toLocaleString('vi-VN');
const fmtP  = p => (p >= 0 ? '+' : '') + Number(p).toFixed(2) + '%';
const pnlC  = p => p > 0.01 ? 'pos' : p < -0.01 ? 'neg' : 'zero';
const sigC  = s => { if (!s || s === 'N/A') return 'na'; const u = s.toUpperCase(); if (u.includes('MUA')) return 'buy'; if (u.includes('BAN')) return 'sell'; return 'hold'; };
const sigLabel = s => s ? s.replace(/[🟢🔴⚪]/g,'').trim() : 'N/A';
const renderErr = msg => `<div class="card" style="color:var(--sell);text-align:center;padding:20px">${msg}</div>`;
const spin = () => '<div class="loading"><div class="spinner"></div></div>';
function parseDecimal(s) {
  if (!s && s !== 0) return NaN;
  s = String(s).trim();
  if (s.includes(',')) return parseFloat(s.replace(/\./g,'').replace(',','.'));
  const m = s.match(/\.(\d+)$/);
  if (m && m[1].length <= 2) return parseFloat(s);
  return parseFloat(s.replace(/\./g,''));
}
function _todayISO() { return new Date().toISOString().slice(0,10); }

// ── API ───────────────────────────────────────────────────────────────────────
function _authHeaders() { return {'Content-Type':'application/json'}; }
async function apiFetch(path, ms=12000) {
  const sep = path.includes('?') ? '&' : '?';
  let qs2 = USER_ID ? sep+'user_id='+USER_ID : '';
  if (USER_ID && USER_NAME) qs2 += '&name='+encodeURIComponent(USER_NAME);
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(API_BASE+path+qs2, {headers:_authHeaders(), signal:ctrl.signal});
    clearTimeout(tid);
    if (!r.ok) { const e=await r.json().catch(()=>({})); const err=new Error(e.error||r.status); err.body=e; err.status=r.status; throw err; }
    return r.json();
  } catch(e) { clearTimeout(tid); throw e.name==='AbortError' ? new Error('Timeout') : e; }
}
async function apiPost(path, body, ms=12000) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(API_BASE+path, {method:'POST', headers:_authHeaders(), body:JSON.stringify(body), signal:ctrl.signal});
    clearTimeout(tid);
    if (!r.ok) { const e=await r.json().catch(()=>({})); const err=new Error(e.error||r.status); err.body=e; err.status=r.status; throw err; }
    return r.json();
  } catch(e) { clearTimeout(tid); throw e.name==='AbortError' ? new Error('Timeout') : e; }
}
async function apiDelete(path, body={}, ms=12000) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(API_BASE+path, {method:'DELETE', headers:_authHeaders(), body:JSON.stringify(body), signal:ctrl.signal});
    clearTimeout(tid);
    if (!r.ok) { const e=await r.json().catch(()=>({})); const err=new Error(e.error||r.status); err.body=e; err.status=r.status; throw err; }
    return r.json();
  } catch(e) { clearTimeout(tid); throw e.name==='AbortError' ? new Error('Timeout') : e; }
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg, dur=2500) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.style.display = 'block';
  clearTimeout(_toastTimer); _toastTimer = setTimeout(() => el.style.display='none', dur);
}

// ── Navigation ────────────────────────────────────────────────────────────────
const TAB_TITLES = {home:'TRANG CHỦ', trade:'GIAO DỊCH', user:'TÀI KHOẢN', admin:'QUẢN TRỊ'};
function goTab(name, btn) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  btn.classList.add('active');
  const titleEl = document.getElementById('header-title');
  if (titleEl) titleEl.textContent = TAB_TITLES[name] || name.toUpperCase();
  if (name === 'home')  { if (!_me) loadMe(); if (!_marketData) loadMarket(); }
  if (name === 'trade') { if (!_signals) loadSignals(); loadUnifiedHistory(); setDcaStyle(_dcaStyle); }
  if (name === 'user')  loadAccountTab();
  if (name === 'admin') loadAdminTab();
}

function showSubtab(page, sub, el) {
  const prefix = {trade:'trade-sub-'}[page];
  if (!prefix) return;
  document.querySelectorAll(`[id^="${prefix}"]`).forEach(d => d.style.display = 'none');
  document.getElementById(prefix+sub).style.display = 'block';
  el.closest('.subtab-bar').querySelectorAll('.subtab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  if (page==='trade' && sub==='signals' && !_signals) loadSignals();
  if (page==='trade' && sub==='dca') { setDcaStyle(_dcaStyle); }
}

function showOrderSub(sub, el) {
  ['ccq','gold','history'].forEach(s => document.getElementById('order-sub-'+s).style.display = s===sub?'block':'none');
  el.closest('.tab-bar').querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  if (sub==='history') loadUnifiedHistory();
  if (sub==='gold') _refreshGoldProductSelect();
  if (sub==='ccq') _updateTradeFundOptions();
}

// ── Tier bar ──────────────────────────────────────────────────────────────────
function renderTierBar(me) {
  if (!me) return;
  const tier = me.tier||'free', isAdmin = me.is_admin||false;
  const nameEl = document.getElementById('tier-name');
  if (nameEl) nameEl.textContent = me.name||'';
  const avatarEl = document.getElementById('user-avatar-letter');
  if (avatarEl && me.name) avatarEl.textContent = me.name.charAt(0).toUpperCase();
  let chip='', right='';
  if (isAdmin) {
    chip = `<span class="tier-chip admin">&#x1F527; ADMIN</span>`;
  } else if (tier==='pro') {
    const exp = me.pro_expires_at ? new Date(me.pro_expires_at) : null;
    const expStr = exp ? exp.toLocaleDateString('vi-VN',{day:'2-digit',month:'2-digit',year:'numeric'}) : '';
    chip = `<span class="tier-chip pro">&#x2B50; PRO</span>${expStr?`<span class="tier-exp">den ${expStr}</span>`:''}`;
  } else {
    chip = `<span class="tier-chip free">MIEN PHI</span>`;
    right = `<span class="tier-upgrade-hint" onclick="showUpgradeModal({})">Nang cap &rarr;</span>`;
  }
  const rightEl = document.getElementById('tier-right');
  if (rightEl) rightEl.innerHTML = `<span style="display:flex;align-items:center;gap:6px">${chip}${right}</span>`;
  const bar = document.getElementById('tier-bar');
  if (bar) bar.classList.add('visible');
  if (isAdmin) { const na=document.getElementById('nav-admin'); if(na) na.style.display=''; }
}

// ── Portfolio ─────────────────────────────────────────────────────────────────
async function loadMe() {
  if (IS_DEV) { _me = MOCK_ME; _goldData = MOCK_GOLD; renderTierBar(_me); renderPortfolio(_me); return; }
  if (!USER_ID) { document.getElementById('pf-sub-ccq').innerHTML=renderErr('Can user_id. Mo tu Telegram bot hoac them ?user_id=... vao URL.'); return; }
  try {
    _me = await apiFetch('/api/me');
    renderTierBar(_me);
    apiFetch(`/api/gold?user_id=${USER_ID}`).then(d=>{_goldData=d;renderPfBanner();renderPfAlloc();renderPfGoldSub();}).catch(()=>{});
    renderPortfolio(_me);
  } catch(e) { document.getElementById('pf-sub-ccq').innerHTML=renderErr('Loi tai: '+e.message); }
}

function renderPfBanner() {
  const pf=_me?.portfolio, gp=_goldData?.portfolio;
  const ccqVal=pf?.total_value||0, goldVal=gp?.current_value||0, total=ccqVal+goldVal;
  const totalCost=(pf?.total_cost||0)+(gp?.total_cost||0);
  const totalPnl=total-totalCost, totalPnlPct=totalCost>0?(totalPnl/totalCost*100):0;
  document.getElementById('pf-date').textContent='cap nhat '+new Date().toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'});
  document.getElementById('pf-banner').innerHTML=`<div class="total-banner">
    <div class="total-lbl">Tong tai san (CCQ + Vang)</div>
    <div class="total-val">${fmt(total)} d</div>
    <div class="total-pnl pnl ${pnlC(totalPnlPct)}">${fmtP(totalPnlPct)} &middot; ${totalPnl>=0?'+':''}${fmt(Math.round(totalPnl))} d</div>
  </div>`;
}

function renderPfAlloc() {
  const ccqVal=_me?.portfolio?.total_value||0, goldVal=_goldData?.portfolio?.current_value||0, total=ccqVal+goldVal;
  if (!total) return;
  const ccqPct=Math.round(ccqVal/total*100), goldPct=100-ccqPct;
  document.getElementById('pf-alloc').innerHTML=`<div class="alloc-wrap">
    <div style="font-size:11px;color:var(--txt2);margin-bottom:2px">Phan bo tai san</div>
    <div class="alloc-track">
      <div class="alloc-ccq" style="width:${ccqPct}%"></div>
      <div class="alloc-gold" style="width:${goldPct}%"></div>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:11px;font-family:var(--mono)">
      <span style="color:var(--c0)">CCQ ${ccqPct}% &mdash; ${(ccqVal/1e6).toFixed(1)}M</span>
      <span style="color:#fbbf24">Vang ${goldPct}% &mdash; ${(goldVal/1e6).toFixed(1)}M</span>
    </div>
  </div>`;
}

function toggleSumDetail(id, rowEl) {
  const el=document.getElementById(id); if(!el) return;
  const open=el.style.display==='none'; el.style.display=open?'flex':'none';
  rowEl?.querySelector('.sum-chevron')?.classList.toggle('open',open);
}

function renderPortfolio(me) {
  renderPfBanner(); renderPfAlloc();
  const pf=me.portfolio;
  let html='';
  if (!pf.items.length) {
    html=`<div class="card" style="text-align:center;color:var(--txt2);padding:24px">Chua co giao dich CCQ.<br>Them o tab Giao dich.</div>`;
  } else {
    html='<div class="card">';
    for (const h of pf.items) {
      const chg=h.chg_pct||0;
      html+=`<div class="fund-row" onclick="openResearch('${h.code}')">
        <div class="fund-info">
          <div class="fund-top">
            <span class="fund-code">${h.code}</span>
            <span class="fund-nav">${fmt(h.nav)} d</span>
            <span class="pnl ${pnlC(chg)}" style="font-size:11px">${fmtP(chg)}</span>
          </div>
          <div class="fund-sub"><span>${fmt(h.units)} CCQ</span><span style="opacity:.4">&middot;</span><span>Gia von ${fmt(h.avg_cost)} d</span></div>
        </div>
        <div class="fund-right">
          <div class="badge ${sigC(h.signal)}">${sigLabel(h.signal)}</div>
          <div class="pnl ${pnlC(h.pnl_pct)}" style="font-size:12px">${fmtP(h.pnl_pct)}</div>
          <div style="font-size:11px;color:var(--txt2)">${h.pnl>=0?'+':''}${fmt(h.pnl)}</div>
        </div>
      </div>`;
    }
    html+='</div>';
    const costDetail=pf.items.map(h=>{const pct=pf.total_cost?(h.cost/pf.total_cost*100):0;return`<div class="sum-detail-row"><span>${h.code}</span><span>${fmt(h.cost)} d <span class="sum-detail-pct">(${pct.toFixed(1)}%)</span></span></div>`;}).join('');
    const valueDetail=pf.items.map(h=>{const pct=pf.total_value?(h.value/pf.total_value*100):0;return`<div class="sum-detail-row"><span>${h.code}</span><span class="pnl ${pnlC(h.pnl_pct)}">${fmt(h.value)} d <span class="sum-detail-pct">(${pct.toFixed(1)}%)</span></span></div>`;}).join('');
    html+=`<div class="card">
      <div class="sum-row sum-row-toggle" onclick="toggleSumDetail('sd-cost',this)"><span class="sum-label">Von CCQ <span class="sum-chevron">&#9660;</span></span><span class="sum-val">${fmt(pf.total_cost)} d</span></div>
      <div id="sd-cost" class="sum-detail" style="display:none">${costDetail}</div>
      <div class="sum-row sum-row-toggle" onclick="toggleSumDetail('sd-value',this)"><span class="sum-label">Gia tri hien tai <span class="sum-chevron">&#9660;</span></span><span class="sum-val">${fmt(pf.total_value)} d</span></div>
      <div id="sd-value" class="sum-detail" style="display:none">${valueDetail}</div>
      <div class="sum-row"><span class="sum-label">Lai/lo CCQ</span><span class="sum-val pnl ${pnlC(pf.total_pnl_pct)}">${pf.total_pnl>=0?'+':''}${fmt(pf.total_pnl)} d</span></div>
    </div>`;
  }
  document.getElementById('pf-sub-ccq').innerHTML=html;
}

function renderPfGoldSub() {
  const el=document.getElementById('pf-sub-gold');
  if (!_goldData) { el.innerHTML=spin(); return; }
  const pf=_goldData.portfolio;
  if (!pf||pf.total_luong===0) { el.innerHTML='<div class="card" style="text-align:center;color:var(--txt2);padding:24px">Chua co danh muc vang.<br>Them o Giao dich -> Vang.</div>'; return; }
  const pnlSign=pf.pnl>=0?'+':'';
  let html=`<div class="card">
    <div class="sum-row"><span class="sum-label">Tong so luong</span><span class="sum-val" style="color:var(--c0)">${pf.total_luong} luong</span></div>
    <div class="sum-row"><span class="sum-label">Gia tri hien tai</span><span class="sum-val">${fmt(pf.current_value)} d</span></div>
    <div class="sum-row"><span class="sum-label">Von</span><span class="sum-val">${fmt(pf.total_cost)} d</span></div>
    <div class="sum-row"><span class="sum-label">Lai/lo</span><span class="sum-val pnl ${pnlC(pf.pnl)}">${pnlSign}${fmt(pf.pnl)} d (${fmtP(pf.pnl_pct)})</span></div>
  </div>`;
  for (const [prod,pp] of Object.entries(pf.by_product||{})) {
    if (pp.price_missing) {
      html+=`<div class="card" style="border-color:#854d0e"><div class="card-title">${pp.label||prod}</div>
        <div class="sum-row"><span class="sum-label">So luong</span><span class="sum-val" style="color:var(--c0)">${pp.luong} luong</span></div>
        <div style="font-size:11px;color:#facc15;margin-top:4px">&#9888; Chua co gia thi truong</div></div>`;
      continue;
    }
    const ppnl=pp.pnl||0, ppnlSign=ppnl>=0?'+':'';
    html+=`<div class="card"><div class="card-title">${pp.label||prod}</div>
      <div class="sum-row"><span class="sum-label">So luong</span><span class="sum-val" style="color:var(--c0)">${pp.luong} luong</span></div>
      <div class="sum-row"><span class="sum-label">Gia mua TB</span><span class="sum-val">${fmt(pp.avg_cost)} d/luong</span></div>
      <div class="sum-row"><span class="sum-label">Gia hien tai</span><span class="sum-val">${fmt(pp.price_buy||pp.price)} d/luong</span></div>
      <div class="sum-row"><span class="sum-label">Lai/lo</span><span class="sum-val pnl ${pnlC(ppnl)}">${ppnlSign}${fmt(ppnl)} d (${fmtP(pp.pnl_pct||0)})</span></div>
    </div>`;
  }
  el.innerHTML=html;
}

// ── Market (Fund Board) ───────────────────────────────────────────────────────
async function loadMarket() {
  document.getElementById('market-content').innerHTML=spin();
  if (IS_DEV) { _marketData=MOCK_SIGNALS; renderMarket(); return; }
  try {
    const d = await apiFetch('/api/signals');
    _marketData = d.signals||d;
    _watchedSet = new Set(Object.keys(_marketData).filter(k=>_marketData[k].has_position));
    renderMarket();
  } catch(e) { document.getElementById('market-content').innerHTML=renderErr('Loi tai thi truong: '+e.message); }
}

function renderMarket() {
  if (!_marketData) return;
  const search=(document.getElementById('market-search').value||'').toUpperCase();
  const codes=Object.keys(_marketData).filter(code=>{
    if (search && !code.includes(search)) return false;
    const s=_marketData[code]; const sc=sigC(s.signal);
    if (_marketFilter==='buy') return sc==='buy';
    if (_marketFilter==='sell') return sc==='sell';
    if (_marketFilter==='hold') return sc==='hold';
    if (_marketFilter==='held') return s.has_position;
    return true;
  });
  if (!codes.length) { document.getElementById('market-content').innerHTML='<div style="text-align:center;color:var(--txt2);padding:20px">Khong co quy nao.</div>'; return; }
  let html='<div class="card">';
  for (const code of codes) {
    const s=_marketData[code];
    const rsi=s.rsi??50, bb=s.bb_pct??50, chg=s.chg_pct||0;
    const rsiC=rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--hold)';
    const bbC=bb<20?'var(--buy)':bb>80?'var(--sell)':'var(--hold)';
    html+=`<div class="sig-row" onclick="selectFundChart('${code}')" data-code="${code}">
      <div>
        <div style="display:flex;align-items:baseline;gap:6px">
          <span class="sig-code">${code}</span>
          <span class="pnl ${pnlC(chg)}" style="font-size:11px">${fmtP(chg)}</span>
          ${s.has_position?'<span style="font-size:9px;color:var(--c0);font-family:var(--mono)">&#x2022;NAM</span>':''}
        </div>
        <div style="font-size:11px;color:var(--txt2)">${fmt(s.nav)} d</div>
      </div>
      <div class="sig-meters">
        <div class="meter"><div class="meter-lbl">RSI</div><div class="meter-bar"><div class="meter-fill" style="width:${rsi}%;background:${rsiC}"></div></div><div class="meter-val">${rsi.toFixed?rsi.toFixed(0):rsi}</div></div>
        <div class="meter"><div class="meter-lbl">BB%</div><div class="meter-bar"><div class="meter-fill" style="width:${bb}%;background:${bbC}"></div></div><div class="meter-val">${bb.toFixed?bb.toFixed(0):bb}</div></div>
        <div class="meter"><div class="meter-lbl">SCR</div><div class="meter-val" style="font-size:11px;color:${(s.score||0)>=3?'var(--buy)':(s.score||0)<=-3?'var(--sell)':'var(--txt)'}">${(s.score>=0?'+':'')}${s.score||0}</div></div>
      </div>
      <div style="text-align:right"><div class="badge ${sigC(s.signal)}">${sigLabel(s.signal)}</div></div>
    </div>`;
  }
  html+='</div>';
  document.getElementById('market-content').innerHTML=html;
}

function filterMarket() { renderMarket(); }
function setMarketFilter(f, el) {
  _marketFilter=f;
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  renderMarket();
}

// ── Fund Chart Column (home right col) ───────────────────────────────────────
async function selectFundChart(code) {
  // highlight selected row
  document.querySelectorAll('#market-content .sig-row').forEach(r =>
    r.style.background = r.dataset.code === code ? 'rgba(0,229,255,.06)' : '');
  const el = document.getElementById('chart-col-content');
  el.innerHTML = '<div class="loading"><div class="spinner"></div>Đang tải...</div>';
  const titleEl = document.getElementById('chart-col-title');
  const subEl = document.getElementById('chart-col-sub');
  if (titleEl) titleEl.textContent = 'BIỂU ĐỒ — ' + code;
  if (subEl) subEl.textContent = 'Đang phân tích...';
  if (IS_DEV) {
    const s = MOCK_SIGNALS[code] || {nav:0,rsi:50,bb_pct:50,score:0,signal:'N/A',chg_pct:0,macd:0};
    renderFundChart({code, name:code+' (dev)', signal:s.signal, nav:s.nav, chg_pct:s.chg_pct,
      rsi:s.rsi, bb:s.bb_pct, macd:s.macd||0, score:s.score,
      schools:[], conclusion:'Dev mode — không có dữ liệu thật.', nav_history:[]});
    return;
  }
  try {
    const d = await apiFetch(`/api/research/${code}`);
    renderFundChart(d);
  } catch(e) { el.innerHTML = renderErr('Lỗi: ' + e.message); }
}

function renderFundChart(d) {
  const el = document.getElementById('chart-col-content');
  if (!el) return;
  const sc = sigC(d.signal);
  const navHist = d.nav_history || [];
  const labels = navHist.map(p => p.date || p[0] || '');
  const vals   = navHist.map(p => p.nav  || p[1] || 0);
  const titleEl = document.getElementById('chart-col-title');
  const subEl   = document.getElementById('chart-col-sub');
  if (titleEl) titleEl.textContent = d.code + (d.name ? ' — ' + d.name.slice(0,22) : '');
  if (subEl)   subEl.textContent   = `NAV: ${fmt(d.nav)} đ  ·  ${fmtP(d.chg_pct||0)}`;
  const rsi=d.rsi||50, bb=d.bb||50;
  const rsiC=rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--hold)';
  const bbC =bb<20 ?'var(--buy)':bb >80?'var(--sell)':'var(--hold)';
  const scrC=(d.score||0)>=3?'var(--buy)':(d.score||0)<=-3?'var(--sell)':'var(--txt)';
  let schoolsHtml='';
  for (const s of (d.schools||[])) {
    const ssc=sigC(s.signal);
    schoolsHtml+=`<div class="school-card ${ssc}" onclick="this.classList.toggle('open')">
      <div class="school-hdr"><div style="flex:1"><div class="school-title">${s.name||''}</div>
      <div class="school-summary">${s.summary||''}</div></div>
      <span class="badge ${ssc}" style="flex-shrink:0;margin:0 6px">${sigLabel(s.signal)}</span>
      <span class="school-chevron">&#9660;</span></div>
      <div class="school-detail"><div class="school-body">${s.analysis||''}</div>
      <div class="school-action ${ssc}">${s.action||''}</div></div></div>`;
  }
  el.innerHTML=`<div style="padding:12px 14px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
      <div>
        <div style="font-family:var(--mono);font-size:20px;font-weight:700">${fmt(d.nav)} đ</div>
        <div class="pnl ${pnlC(d.chg_pct||0)}" style="font-size:12px;margin-top:2px">${fmtP(d.chg_pct||0)}</div>
      </div>
      <div class="badge ${sc}" style="font-size:13px;padding:5px 12px">${sigLabel(d.signal)}</div>
    </div>
    <div style="display:flex;gap:10px;margin-bottom:10px">
      <div style="flex:1;background:var(--bg3);border-radius:6px;padding:6px 8px">
        <div class="meter-lbl" style="margin-bottom:4px">RSI</div>
        <div class="meter-bar" style="width:100%;margin-bottom:4px"><div class="meter-fill" style="width:${rsi}%;background:${rsiC}"></div></div>
        <div style="font-family:var(--mono);font-size:11px;color:${rsiC}">${rsi.toFixed?rsi.toFixed(1):rsi}</div>
      </div>
      <div style="flex:1;background:var(--bg3);border-radius:6px;padding:6px 8px">
        <div class="meter-lbl" style="margin-bottom:4px">BB%</div>
        <div class="meter-bar" style="width:100%;margin-bottom:4px"><div class="meter-fill" style="width:${bb}%;background:${bbC}"></div></div>
        <div style="font-family:var(--mono);font-size:11px;color:${bbC}">${bb.toFixed?bb.toFixed(1):bb}</div>
      </div>
      <div style="flex:1;background:var(--bg3);border-radius:6px;padding:6px 8px;text-align:center">
        <div class="meter-lbl" style="margin-bottom:4px">SCORE</div>
        <div style="font-family:var(--mono);font-size:18px;font-weight:700;color:${scrC}">${(d.score||0)>=0?'+':''}${d.score||0}</div>
      </div>
    </div>
    ${navHist.length?`<div style="height:160px;margin-bottom:10px;position:relative"><canvas id="home-nav-chart"></canvas></div>`:'<div style="height:60px;display:flex;align-items:center;justify-content:center;color:var(--txt2);font-size:11px">Chưa có lịch sử NAV</div>'}
    ${d.conclusion?`<div class="conclusion" style="margin-bottom:10px;font-size:12px">${d.conclusion}</div>`:''}
    ${schoolsHtml}
  </div>`;
  if (navHist.length) {
    if (_homeChart) { _homeChart.destroy(); _homeChart=null; }
    const ctx=document.getElementById('home-nav-chart').getContext('2d');
    const lineColor=sc==='buy'?'#4ade80':sc==='sell'?'#f87171':'#facc15';
    _homeChart=new Chart(ctx,{type:'line',data:{labels,datasets:[{data:vals,borderColor:lineColor,borderWidth:2,
      fill:true,backgroundColor:lineColor+'22',tension:0.3,pointRadius:0}]},
      options:{responsive:true,maintainAspectRatio:false,
        plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>fmt(c.parsed.y)+' đ'}}},
        scales:{x:{display:false},y:{display:true,grid:{color:'#1e3050'},
          ticks:{color:'#94a3b8',font:{family:'IBM Plex Mono',size:10},
                 callback:v=>v>=1e6?(v/1e6).toFixed(1)+'M':(v/1000).toFixed(0)+'K'}}}}});
  }
}

// ── Signals (watched) ─────────────────────────────────────────────────────────
async function loadSignals() {
  document.getElementById('sig-content').innerHTML=spin();
  if (IS_DEV) { _signals=MOCK_SIGNALS; renderSignals(_signals); return; }
  try {
    const d=await apiFetch('/api/signals');
    _signals=d.signals||d;
    renderSignals(_signals);
  } catch(e) { document.getElementById('sig-content').innerHTML=renderErr('Loi: '+e.message); }
}

function renderSignals(sigs) {
  const watched=Object.fromEntries(Object.entries(sigs).filter(([,s])=>s.has_position||s.watched));
  const codes=Object.keys(watched);
  if (!codes.length) { document.getElementById('sig-content').innerHTML='<div style="text-align:center;color:var(--txt2);padding:24px">Chua co quy theo doi.<br>Mua CCQ o tab Giao dich.</div>'; return; }
  let html='<div class="card">';
  for (const code of codes) {
    const s=sigs[code]; const rsi=s.rsi??50,bb=s.bb_pct??50,chg=s.chg_pct||0;
    const rsiC=rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--hold)';
    const bbC=bb<20?'var(--buy)':bb>80?'var(--sell)':'var(--hold)';
    html+=`<div class="sig-row" onclick="openResearch('${code}')">
      <div>
        <div style="display:flex;align-items:baseline;gap:6px"><span class="sig-code">${code}</span><span class="pnl ${pnlC(chg)}" style="font-size:11px">${fmtP(chg)}</span></div>
        <div style="font-size:11px;color:var(--txt2)">${fmt(s.nav)} d</div>
      </div>
      <div class="sig-meters">
        <div class="meter"><div class="meter-lbl">RSI</div><div class="meter-bar"><div class="meter-fill" style="width:${rsi}%;background:${rsiC}"></div></div><div class="meter-val">${rsi.toFixed?rsi.toFixed(0):rsi}</div></div>
        <div class="meter"><div class="meter-lbl">BB%</div><div class="meter-bar"><div class="meter-fill" style="width:${bb}%;background:${bbC}"></div></div><div class="meter-val">${bb.toFixed?bb.toFixed(0):bb}</div></div>
      </div>
      <div style="text-align:right"><div class="badge ${sigC(s.signal)}">${sigLabel(s.signal)}</div></div>
    </div>`;
  }
  html+='</div>';
  document.getElementById('sig-content').innerHTML=html;
}

// ── Research Modal ────────────────────────────────────────────────────────────
function setModalTitle(code,name) {
  document.getElementById('modal-title-code').textContent=name?code+' —':code;
  const nameEl=document.getElementById('modal-title-name'); nameEl.textContent=name||''; nameEl.classList.remove('marquee'); nameEl.style.removeProperty('--marquee-dist');
  if (!name) return;
  requestAnimationFrame(()=>{
    const wrap=document.getElementById('modal-title-name-wrap');
    const overflow=nameEl.scrollWidth-wrap.clientWidth;
    if (overflow>8) { nameEl.style.setProperty('--marquee-dist',(-overflow-6)+'px'); nameEl.classList.add('marquee'); }
  });
}

function closeModal(e) { if(e.target===document.getElementById('modal')) closeModalBtn(); }
function closeModalBtn() { document.getElementById('modal').classList.remove('open'); if(_navChart){_navChart.destroy();_navChart=null;} }

async function openResearch(code) {
  document.getElementById('modal').classList.add('open');
  document.getElementById('modal-body').innerHTML=spin();
  setModalTitle(code,'');
  if (IS_DEV) {
    const s=MOCK_SIGNALS[code]||{nav:0,rsi:50,bb_pct:50,score:0,signal:'N/A',chg_pct:0};
    renderResearch({code, name:code+' (dev)', signal:s.signal, nav:s.nav, chg_pct:s.chg_pct, rsi:s.rsi, bb:s.bb_pct, macd:s.macd||0, score:s.score, schools:[], conclusion:'Dev mode - khong co du lieu that.', nav_history:[]});
    return;
  }
  try {
    const d=await apiFetch(`/api/research/${code}`);
    renderResearch(d);
  } catch(e) { document.getElementById('modal-body').innerHTML=renderErr('Loi: '+e.message); }
}

function renderResearch(d) {
  setModalTitle(d.code, d.name);
  const rsi=d.rsi??50, bb=d.bb??50, chg=d.chg_pct||0;
  const rsiC=rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--hold)';
  const bbC=bb<20?'var(--buy)':bb>80?'var(--sell)':'var(--hold)';
  let html=`<div class="section">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <div>
        <span class="fund-nav" style="font-size:18px">${fmt(d.nav)} d</span>
        <span class="pnl ${pnlC(chg)}" style="font-size:13px;margin-left:8px">${fmtP(chg)}</span>
      </div>
      <div class="badge ${sigC(d.signal)}" style="font-size:13px">${sigLabel(d.signal)}</div>
    </div>
    <div style="display:flex;gap:16px;font-size:12px;font-family:var(--mono)">
      <div><div class="meter-lbl">RSI</div><div class="meter-bar" style="width:80px;height:6px;margin:4px 0"><div class="meter-fill" style="width:${rsi}%;background:${rsiC}"></div></div><div>${rsi.toFixed?rsi.toFixed(1):rsi}</div></div>
      <div><div class="meter-lbl">BB%</div><div class="meter-bar" style="width:80px;height:6px;margin:4px 0"><div class="meter-fill" style="width:${bb}%;background:${bbC}"></div></div><div>${bb.toFixed?bb.toFixed(1):bb}</div></div>
      <div><div class="meter-lbl">SCORE</div><div style="font-size:16px;font-weight:700;color:${(d.score||0)>=3?'var(--buy)':(d.score||0)<=-3?'var(--sell)':'var(--txt)'}">${d.score>=0?'+':''}${d.score||0}</div></div>
    </div>
  </div>`;
  if (d.nav_history && d.nav_history.length>1) {
    html+=`<div class="section"><div class="section-hdr"><span>LICH SU NAV</span></div><div class="chart-wrap"><canvas id="modal-nav-chart"></canvas></div></div>`;
  }
  if (d.conclusion) html+=`<div class="section"><div class="conclusion">${d.conclusion}</div></div>`;
  if (d.schools && d.schools.length) {
    html+='<div class="section"><div class="section-hdr"><span>5 TRUONG PHAI</span></div>';
    for (const sc of d.schools) {
      html+=`<div class="school-card ${sigC(sc.signal)}" onclick="this.classList.toggle('open')">
        <div class="school-hdr"><span class="school-title">${sc.name}</span><span class="badge ${sigC(sc.signal)}" style="font-size:10px">${sigLabel(sc.signal)}</span><span class="school-chevron">&#9660;</span></div>
        <div class="school-summary">${sc.summary||''}</div>
        <div class="school-detail"><div class="school-body">${sc.detail||''}</div>
          ${sc.action?`<div class="school-action ${sigC(sc.signal)}">${sc.action}</div>`:''}
        </div>
      </div>`;
    }
    html+='</div>';
  }
  document.getElementById('modal-body').innerHTML=html;
  if (d.nav_history && d.nav_history.length>1) {
    const ctx=document.getElementById('modal-nav-chart').getContext('2d');
    if (_navChart) _navChart.destroy();
    _navChart=new Chart(ctx,{type:'line',data:{labels:d.nav_history.map(r=>r.date),datasets:[{data:d.nav_history.map(r=>r.nav),borderColor:'#00e5ff',borderWidth:1.5,pointRadius:0,fill:true,backgroundColor:'rgba(0,229,255,.08)'}]},options:{plugins:{legend:{display:false}},scales:{x:{display:false},y:{display:false}},animation:{duration:400}}});
  }
}

// ── Trades ────────────────────────────────────────────────────────────────────
function setTradeType(type, el) {
  _tradeType=type;
  el.closest('.type-toggle').querySelectorAll('.type-btn').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  const btn=document.getElementById('trade-ccq-btn');
  const amtLbl=document.getElementById('trade-amount-label');
  const navLbl=document.getElementById('trade-nav-label');
  if (type==='buy')  { btn.textContent='XAC NHAN MUA'; btn.className='btn btn-buy'; amtLbl.textContent='So tien (d)'; navLbl.textContent='NAV tai ngay mua (d)'; }
  if (type==='sell') { btn.textContent='XAC NHAN BAN'; btn.className='btn btn-sell'; amtLbl.textContent='So tien ban (d)'; navLbl.textContent='NAV tai ngay ban (d)'; }
  if (type==='div')  { btn.textContent='XAC NHAN LOI TUC'; btn.className='btn btn-primary'; amtLbl.textContent='So tien loi tuc (d)'; navLbl.textContent='NAV tai ngay (d)'; }
}
function setGoldType(type) {
  _goldType=type;
  document.querySelectorAll('#order-sub-gold .type-btn').forEach(b=>b.classList.remove('active'));
  document.querySelector(`#order-sub-gold .type-btn.${type}`).classList.add('active');
  const btn=document.getElementById('gold-trade-btn');
  document.getElementById('gold-price-label').textContent=type==='buy'?'Gia mua (d/luong)':'Gia ban (d/luong)';
  btn.textContent=type==='buy'?'XAC NHAN MUA':'XAC NHAN BAN';
  btn.className=type==='buy'?'btn btn-buy':'btn btn-sell';
}

function _updateTradeFundOptions() {
  const sel=document.getElementById('trade-fund-select');
  const held=(_me?.portfolio?.items||[]).map(h=>h.code);
  const all=Object.keys(_marketData||_signals||{});
  const codes=[...new Set([...held,...all])].sort();
  sel.innerHTML='<option value="">-- Chon quy --</option>'+codes.map(c=>`<option value="${c}">${c}</option>`).join('');
}

function _refreshGoldProductSelect() {
  const sel=document.getElementById('gold-product-select');
  sel.innerHTML=GOLD_PRODUCTS.map(p=>`<option value="${p.value}">${p.label}</option>`).join('');
}

async function submitCCQTrade() {
  if (IS_DEV) { toast('DEV MODE: Khong gui API. Data: '+_tradeType+' '+document.getElementById('trade-fund-select').value); return; }
  const fund=document.getElementById('trade-fund-select').value;
  const amount=parseDecimal(document.getElementById('trade-amount').value);
  const nav=parseDecimal(document.getElementById('trade-nav-input').value);
  const date=document.getElementById('trade-date').value||_todayISO();
  const note=document.getElementById('trade-note').value;
  const st=document.getElementById('trade-status');
  if (!fund) { st.style.color='var(--sell)'; st.textContent='Chua chon quy'; return; }
  if (!amount||amount<=0) { st.style.color='var(--sell)'; st.textContent='So tien khong hop le'; return; }
  st.style.color='var(--txt2)'; st.textContent='Dang luu...';
  try {
    await apiPost('/api/trade',{telegram_id:USER_ID, fund_code:fund, trade_type:_tradeType, amount, nav:nav||null, trade_date:date, note});
    st.style.color='var(--buy)'; st.textContent='&#x2713; Da luu giao dich!';
    _me=null; setTimeout(()=>loadMe(),800);
  } catch(e) { st.style.color='var(--sell)'; st.textContent='Loi: '+(e.body?.error||e.message); }
}

async function submitGoldTrade() {
  if (IS_DEV) { toast('DEV: gold '+_goldType+' '+document.getElementById('gold-product-select').value); return; }
  const product=document.getElementById('gold-product-select').value;
  const units=parseDecimal(document.getElementById('gold-units').value);
  const price=parseDecimal(document.getElementById('gold-price').value);
  const date=document.getElementById('gold-date').value||_todayISO();
  const name=document.getElementById('gold-name').value;
  const st=document.getElementById('gold-trade-status');
  if (!units||units<=0) { st.style.color='var(--sell)'; st.textContent='So luong khong hop le'; return; }
  st.style.color='var(--txt2)'; st.textContent='Dang luu...';
  try {
    await apiPost('/api/gold/trade',{telegram_id:USER_ID, product, trade_type:_goldType, units, price:price||null, trade_date:date, name});
    st.style.color='var(--buy)'; st.textContent='&#x2713; Da luu!';
    _goldData=null; setTimeout(()=>loadMe(),800);
  } catch(e) { st.style.color='var(--sell)'; st.textContent='Loi: '+(e.body?.error||e.message); }
}

async function loadUnifiedHistory() {
  const el=document.getElementById('history-content'); el.innerHTML=spin();
  if (IS_DEV) { renderHistory(MOCK_HISTORY); return; }
  try {
    const d=await apiFetch('/api/history');
    renderHistory(d.trades||d);
  } catch(e) { el.innerHTML=renderErr('Loi: '+e.message); }
}

function renderHistory(trades) {
  const el=document.getElementById('history-content');
  if (!trades||!trades.length) { el.innerHTML='<div style="text-align:center;color:var(--txt2);padding:24px">Chua co giao dich nao.</div>'; return; }
  let html='';
  for (const t of trades) {
    const isGold=t.asset_type==='gold';
    const code=isGold?(t.gold_product||'VANG'):t.fund_code;
    const typeC=t.trade_type==='buy'?'var(--buy)':t.trade_type==='sell'?'var(--sell)':'var(--c0)';
    const amt=isGold?`${t.units}L @ ${fmt(t.price)}`:`${fmt(t.amount)} d`;
    html+=`<div class="tlog-row">
      <div class="tlog-left">
        <div class="tlog-code">${code} <span style="font-size:11px;color:${typeC}">${t.trade_type.toUpperCase()}</span></div>
        <div class="tlog-meta">${t.trade_date} &middot; ${amt}</div>
        ${t.note||t.name?`<div class="tlog-meta">${t.note||t.name}</div>`:''}
      </div>
    </div>`;
  }
  el.innerHTML=html;
}

// ── DCA ────────────────────────────────────────────────────────────────────────
function setDcaStyle(style, el) {
  _dcaStyle=style;
  document.querySelectorAll('.style-btn').forEach(b=>b.classList.remove('active'));
  if (el) el.classList.add('active');
  else document.querySelector(`.style-btn[onclick*="'${style}'"]`)?.classList.add('active');
  document.getElementById('dca-style-desc').innerHTML=DCA_DESCS[style]||'';
}

async function calcDCA() {
  const budget=parseDecimal(document.getElementById('dca-budget').value);
  if (!budget||budget<=0) { toast('Nhap ngan sach hop le'); return; }
  const el=document.getElementById('dca-content'); el.innerHTML=spin();
  if (IS_DEV) {
    const sigs=MOCK_SIGNALS; const total=budget;
    const items=Object.entries(sigs).filter(([,s])=>s.has_position).map(([code,s])=>({code,score:s.score||0,nav:s.nav,signal:s.signal}));
    const totalScore=items.reduce((a,b)=>a+Math.max(0,b.score+5),0)||1;
    let html='<div class="card">';
    for (const it of items) {
      const w=Math.max(0,it.score+5)/totalScore;
      const amt=Math.round(total*w);
      const units=(it.nav?amt/it.nav:0).toFixed(2);
      html+=`<div class="dca-fund"><div class="dca-fund-row"><span class="fund-code">${it.code}</span><span style="font-family:var(--mono);font-size:12px">${fmt(amt)} d</span><span class="badge ${sigC(it.signal)}" style="font-size:10px">${Math.round(w*100)}%</span></div><div class="dca-bar-wrap"><div class="dca-bar" style="width:${Math.round(w*100)}%;background:var(--c0)"></div></div><div class="dca-reason">~ ${units} CCQ tai NAV ${fmt(it.nav)} d</div></div>`;
    }
    html+='</div>'; el.innerHTML=html; return;
  }
  try {
    const d=await apiPost('/api/dca',{telegram_id:USER_ID, budget, style:_dcaStyle});
    renderDCA(d);
  } catch(e) { el.innerHTML=renderErr('Loi: '+e.message); }
}

function renderDCA(data) {
  const el=document.getElementById('dca-content');
  const items=data.allocations||data.items||[];
  if (!items.length) { el.innerHTML='<div style="text-align:center;color:var(--txt2);padding:16px">Khong co de xuat.</div>'; return; }
  let html='<div class="card">';
  for (const it of items) {
    html+=`<div class="dca-fund"><div class="dca-fund-row"><span class="fund-code">${it.code}</span><span style="font-family:var(--mono);font-size:12px">${fmt(it.amount)} d</span><span class="badge ${sigC(it.signal)}" style="font-size:10px">${it.pct||0}%</span></div><div class="dca-bar-wrap"><div class="dca-bar" style="width:${it.pct||0}%;background:var(--c0)"></div></div><div class="dca-reason">${it.reason||''}</div></div>`;
  }
  html+='</div>'; el.innerHTML=html;
}

function setGoldPredType(type, el) {
  _goldPredType=type;
  document.querySelectorAll('#gold-pred-buy,#gold-pred-sell').forEach(b=>b.classList.remove('gp-active'));
  el.classList.add('gp-active');
}
function setGoldUnit(unit, el) {
  _goldUnit=unit;
  document.querySelectorAll('#gold-pred-chi,#gold-pred-luong').forEach(b=>b.classList.remove('gp-active'));
  el.classList.add('gp-active');
}
async function calcGoldDCA() {
  const el=document.getElementById('gold-dca-content'); el.innerHTML=spin();
  if (IS_DEV) {
    const divider=_goldUnit==='chi'?10:1;
    const basePrice=_goldPredType==='buy'?87000000:86200000;
    el.innerHTML=`<div class="card"><div class="card-title">DU BAO GIA VANG (DEV)</div>
      <div class="sum-row"><span class="sum-label">Hom nay</span><span class="sum-val">${fmt(Math.round(basePrice/divider))} d/${_goldUnit}</span></div>
      <div class="sum-row"><span class="sum-label">T+1 (du bao)</span><span class="sum-val pnl pos">${fmt(Math.round((basePrice*1.005)/divider))} d/${_goldUnit}</span></div>
      <div class="sum-row"><span class="sum-label">T+7</span><span class="sum-val pnl pos">${fmt(Math.round((basePrice*1.02)/divider))} d/${_goldUnit}</span></div>
    </div>`; return;
  }
  try {
    const d=await apiFetch(`/api/gold/predict?type=${_goldPredType}&unit=${_goldUnit}`);
    el.innerHTML=`<div class="card">${(d.predictions||[]).map(p=>`<div class="sum-row"><span class="sum-label">${p.label}</span><span class="sum-val pnl ${pnlC(p.change_pct||0)}">${fmt(p.price)} d/${_goldUnit}</span></div>`).join('')}</div>`;
  } catch(e) { el.innerHTML=renderErr('Loi: '+e.message); }
}

// ── Account ───────────────────────────────────────────────────────────────────
async function loadAccountTab() {
  await loadUserProfile();
  loadReferralCode();
}

async function loadUserProfile() {
  const el=document.getElementById('user-profile-card'); el.innerHTML=spin();
  if (IS_DEV) {
    const me=MOCK_ME, tier=me.tier, isAdmin=me.is_admin;
    el.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:flex-start">
      <div><div style="font-size:16px;font-weight:700">${me.name}</div><div style="font-size:12px;color:var(--txt2);margin-top:2px">ID: ${me.telegram_id}</div></div>
      <span class="tier-chip ${isAdmin?'admin':tier}">${isAdmin?'ADMIN':tier.toUpperCase()}</span>
    </div>`;
    if (!isAdmin && tier!=='pro') document.getElementById('acc-upgrade-section').innerHTML=`<button class="btn btn-primary" onclick="showUpgradeModal({})">&#x2B50; NANG CAP PRO NGAY</button>`;
    return;
  }
  if (!_me) { try { _me=await apiFetch('/api/me'); renderTierBar(_me); } catch(e){} }
  const me=_me; if (!me) { el.innerHTML=renderErr('Loi tai user'); return; }
  const tier=me.tier||'free', isAdmin=me.is_admin;
  const exp=me.pro_expires_at?new Date(me.pro_expires_at).toLocaleDateString('vi-VN',{day:'2-digit',month:'2-digit',year:'numeric'}):'';
  el.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div><div style="font-size:16px;font-weight:700">${me.name||''}</div><div style="font-size:12px;color:var(--txt2);margin-top:2px">ID: ${me.telegram_id}</div>${exp?`<div style="font-size:11px;color:var(--txt2)">Pro den ${exp}</div>`:''}</div>
    <span class="tier-chip ${isAdmin?'admin':tier}">${isAdmin?'ADMIN':tier.toUpperCase()}</span>
  </div>`;
  if (!isAdmin && tier!=='pro') document.getElementById('acc-upgrade-section').innerHTML=`<button class="btn btn-primary" onclick="showUpgradeModal({})">&#x2B50; NANG CAP PRO NGAY</button>`;
}

async function loadReferralCode() {
  const box=document.getElementById('referral-code-box'), st=document.getElementById('referral-stats');
  if (IS_DEV) {
    box.innerHTML=`<div style="flex:1;font-family:var(--mono);font-size:15px;font-weight:700;color:var(--c0);background:var(--bg);border:1px solid var(--bdr);border-radius:8px;padding:8px 10px">HARVEY2024</div><button class="btn btn-primary" style="width:auto;margin:0;padding:0 14px" onclick="navigator.clipboard?.writeText('HARVEY2024').then(()=>toast('Da sao chep!'))">Sao chep</button>`;
    st.textContent='&#x2713; Da co 3 nguoi dung ma cua ban'; return;
  }
  if (!USER_ID) { box.innerHTML='<div style="font-size:12px;color:var(--txt2)">Can user_id de lay ma gioi thieu.</div>'; return; }
  try {
    const d=await apiFetch('/api/referral/mine');
    box.innerHTML=`<div style="flex:1;font-family:var(--mono);font-size:15px;font-weight:700;color:var(--c0);background:var(--bg);border:1px solid var(--bdr);border-radius:8px;padding:8px 10px;letter-spacing:.05em">${d.code}</div><button class="btn btn-primary" style="width:auto;margin:0;padding:0 14px" onclick="navigator.clipboard?.writeText('${d.code}').then(()=>toast('Da sao chep!'))">Sao chep</button>`;
    st.textContent=d.uses_count>0?`&#x2713; Da co ${d.uses_count} nguoi dung ma cua ban`:'Chua co ai dung ma cua ban';
  } catch(e) { box.innerHTML=`<div style="font-size:12px;color:var(--sell)">Loi: ${e.message}</div>`; }
}

async function redeemPromoCode(ctx='modal') {
  const inputId=ctx==='acc'?'acc-promo-input':'promo-code-input';
  const statusId=ctx==='acc'?'acc-promo-status':'promo-code-status';
  const code=(document.getElementById(inputId).value||'').trim().toUpperCase();
  const st=document.getElementById(statusId);
  if (!code) { st.style.color='var(--sell)'; st.textContent='Vui long nhap ma'; return; }
  if (IS_DEV) { st.style.color='var(--buy)'; st.textContent='&#x2713; DEV: Ma '+code+' da duoc ap dung!'; return; }
  if (!USER_ID) { st.style.color='var(--sell)'; st.textContent='Can user_id'; return; }
  st.style.color='var(--txt2)'; st.textContent='Dang ap dung...';
  try {
    const d=await apiPost('/api/promo/redeem',{telegram_id:USER_ID, code});
    st.style.color='var(--buy)';
    st.textContent=d.kind==='referral'?`&#x2713; Da ghi nhan ma gioi thieu!`:`&#x2713; Da cong +${d.days} ngay Pro!`;
    document.getElementById(inputId).value='';
    _me=null;
  } catch(e) { st.style.color='var(--sell)'; st.textContent='&#x26A0; '+(e.body?.error||e.message); }
}

// ── Upgrade Modal ─────────────────────────────────────────────────────────────
function showUpgradeModal(info) {
  document.getElementById('upgrade-reason').textContent=info?.limit?`Ban da dat gioi han ${info.limit} ma. Nang cap Pro de theo doi khong gioi han.`:'Tinh nang nay chi danh cho tai khoan Pro.';
  document.getElementById('promo-code-status').textContent='';
  renderPlanCards();
  document.getElementById('upgrade-modal').classList.add('open');
}
function closeUpgradeModal(e) { if(e.target===document.getElementById('upgrade-modal')) closeUpgradeModalBtn(); }
function closeUpgradeModalBtn() { document.getElementById('upgrade-modal').classList.remove('open'); }
function renderPlanCards() {
  document.getElementById('plan-cards').innerHTML=Object.entries(PRO_PLANS).map(([key,p])=>{
    const sel=key===_selectedPlan;
    return `<div onclick="_selectedPlan='${key}';renderPlanCards()" style="cursor:pointer;position:relative;border:1px solid ${sel?'var(--c0)':'var(--bdr)'};background:${sel?'rgba(0,229,255,.08)':'var(--bg3)'};border-radius:10px;padding:10px 8px;text-align:center">
      ${key==='y1'?'<div style="position:absolute;top:-8px;left:50%;transform:translateX(-50%);font-size:9px;font-family:var(--mono);background:var(--c0);color:#000;padding:1px 6px;border-radius:99px;white-space:nowrap">TIET KIEM NHAT</div>':''}
      <div style="font-size:12px;color:var(--txt2);margin-top:${key==='y1'?'6':'0'}px">${p.label}</div>
      <div style="font-family:var(--mono);font-weight:700;font-size:15px;color:${sel?'var(--c0)':'var(--txt)'};margin-top:4px">${p.stars} &#x2B50;</div>
      <div style="font-size:10px;color:var(--txt2);margin-top:2px">${p.discount?`-${p.discount}%`:''}</div>
    </div>`;
  }).join('');
}
async function startUpgrade() {
  if (IS_DEV) { toast('DEV: Mo invoice Stars cho plan '+_selectedPlan); closeUpgradeModalBtn(); return; }
  const btn=document.getElementById('upgrade-cta-btn'); btn.disabled=true; btn.textContent='Dang tao invoice...';
  try {
    const d=await apiPost('/api/payment/stars/create',{plan:_selectedPlan});
    if (!d.invoice_link) throw new Error('Khong nhan duoc invoice link');
    closeUpgradeModalBtn();
    window.open(d.invoice_link,'_blank');
  } catch(e) { toast('Loi: '+e.message); }
  finally { btn.disabled=false; btn.textContent='&#x2B50; NANG CAP PRO NGAY'; }
}

// ── Admin ─────────────────────────────────────────────────────────────────────
function loadAdminTab() {
  loadDiscountList(); loadAdminNavPending(); loadAdminSummary(); loadAdminAudit();
  _buildBookmarklet();
}

function _buildBookmarklet() {
  const slot=document.getElementById('bm-slot'); if(!slot) return;
  const code='(function(){var t=null,k=null,n=localStorage.length;for(var i=0;i<n;i++){var _k=localStorage.key(i);var _v=localStorage.getItem(_k);if(_v&&_v.length>100&&/^eyJ/.test(_v)){t=_v;k=_k;break;}}if(t){if(window.opener){window.opener.postMessage({type:"tcbs_token",token:t,key:k},"*");window.close();}else{navigator.clipboard.writeText(t).then(function(){alert("Copied! Key: "+k);});}}else{alert("Khong tim thay JWT. Hay dang nhap TCInvest truoc.");}})();';
  const a=document.createElement('a'); a.href='javascript:'+code; a.textContent='[ Keo bookmarklet nay vao thanh cong cu ]';
  a.style.cssText='display:inline-block;padding:8px 12px;background:#001a33;border:1px solid var(--c0);border-radius:8px;color:var(--c0);font-family:var(--mono);font-size:11px;text-decoration:none;cursor:move';
  slot.innerHTML='<div style="margin-bottom:6px;font-size:11px;color:var(--txt2)">1. Keo link nay vao Bookmarks Bar / 2. Mo TCInvest, dang nhap / 3. Nhan vao bookmark</div>';
  slot.appendChild(a);
  window.addEventListener('message', e=>{if(e.data?.type==='tcbs_token'){document.getElementById('admin-token-input').value=e.data.token;toast('&#x2713; Token da tu dong dien vao o nhap!',4000);}});
}

function openTCInvest() {
  const w=window.open('https://tcinvest.tcbs.com.vn','tcbs_login','width=1024,height=700');
  if (!w) toast('Cho phep popup de mo TCInvest!');
}

async function adminUpdateToken() {
  const token=(document.getElementById('admin-token-input').value||'').trim();
  const st=document.getElementById('admin-token-status');
  if (!token) { st.style.color='var(--sell)'; st.textContent='Chua nhap token'; return; }
  if (IS_DEV) { st.style.color='var(--buy)'; st.textContent='&#x2713; DEV: Token da luu (gia lap)'; return; }
  st.style.color='var(--txt2)'; st.textContent='Dang luu token...';
  try {
    await apiPost('/api/admin/settoken',{admin_id:USER_ID, token});
    st.style.color='var(--buy)'; st.textContent='&#x2713; Token moi da luu vao he thong.';
  } catch(e) { st.style.color='var(--sell)'; st.textContent='&#x26A0; '+(e.body?.error||e.message); }
}

async function adminFetchAll() {
  const st=document.getElementById('admin-fetch-status');
  st.style.color='var(--txt2)'; st.textContent='Dang fetch tat ca quy...';
  if (IS_DEV) { st.style.color='var(--buy)'; st.textContent='&#x2713; DEV: Fetch started (gia lap)'; return; }
  try { const d=await apiPost('/api/admin/fetch-nav',{telegram_id:USER_ID}); st.style.color='var(--buy)'; st.textContent=`&#x2713; ${d.msg||'Fetch started'}`; }
  catch(e) { st.style.color='var(--sell)'; st.textContent='&#x26A0; '+(e.body?.error||e.message); }
}

async function adminFetchFmarket() {
  const st=document.getElementById('admin-fetch-status');
  st.style.color='var(--txt2)'; st.textContent='Dang fetch fmarket...';
  if (IS_DEV) { st.style.color='var(--buy)'; st.textContent='&#x2713; DEV: Fmarket fetch started'; return; }
  try { const d=await apiPost('/api/admin/fetch-nav',{telegram_id:USER_ID,skip_tcbs:true}); st.style.color='var(--buy)'; st.textContent=`&#x2713; ${d.msg||'Fetch started (fmarket only)'}`; }
  catch(e) { st.style.color='var(--sell)'; st.textContent='&#x26A0; '+(e.body?.error||e.message); }
}

async function loadDiscountList() {
  const el=document.getElementById('admin-discount-list'); el.innerHTML='<div style="font-size:12px;color:var(--txt2)">Dang tai...</div>';
  const list=IS_DEV?MOCK_DISCOUNTS:(await apiFetch('/api/admin/discount/list?user_id='+(USER_ID||'')).then(d=>d.codes||[]).catch(()=>[]));
  if (!list.length) { el.innerHTML='<div style="font-size:12px;color:var(--txt2)">Chua co ma giam gia nao.</div>'; return; }
  el.innerHTML=list.map(c=>`<div style="border-bottom:1px solid var(--bdr);padding:8px 0;display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
    <div><div style="font-family:var(--mono);font-size:12px;font-weight:700;color:var(--c0)">${c.code}</div>
    <div style="font-size:11px;color:var(--txt2)">${c.benefit_type==='discount_pct'?c.benefit_value+'% giam':c.benefit_value+' ngay'} &middot; ${c.uses_count||0}/${c.max_uses||'∞'} luot${c.note?' &middot; '+c.note:''}</div></div>
    <button onclick="toggleDiscount('${c.code}',${!c.is_active})" style="padding:3px 10px;border-radius:6px;border:none;font-size:11px;font-family:var(--mono);font-weight:700;cursor:pointer;background:${c.is_active?'#052e1a':'var(--bg3)'};color:${c.is_active?'var(--buy)':'var(--txt2)'}">${c.is_active?'BAT':'TAT'}</button>
  </div>`).join('');
}

async function createDiscount() {
  const code=(document.getElementById('disc-new-code').value||'').trim().toUpperCase();
  const value=parseDecimal(document.getElementById('disc-new-value').value);
  const until=document.getElementById('disc-new-until').value||null;
  const maxUses=document.getElementById('disc-new-maxuses').value||null;
  const note=document.getElementById('disc-new-note').value;
  const channel=document.getElementById('disc-new-channel')?.value||'';
  const st=document.getElementById('disc-create-status');
  if (!code) { st.style.color='var(--sell)'; st.textContent='Chua nhap ma'; return; }
  if (!value||value<=0) { st.style.color='var(--sell)'; st.textContent='Gia tri khong hop le'; return; }
  if (!until && !maxUses) { st.style.color='var(--sell)'; st.textContent='Can co it nhat 1 gioi han (thoi gian hoac so luot)'; return; }
  if (IS_DEV) { st.style.color='var(--buy)'; st.textContent='&#x2713; DEV: Ma '+code+' da tao (gia lap)'; return; }
  st.style.color='var(--txt2)'; st.textContent='Dang tao...';
  try {
    await apiPost('/api/admin/discount/create',{telegram_id:USER_ID, code, benefit_type:_discBenefitType, benefit_value:value, requires_purchase:_discRequiresPurchase, valid_until:until, max_uses:maxUses?parseInt(maxUses):null, note, channel});
    st.style.color='var(--buy)'; st.textContent='&#x2713; Da tao ma '+code;
    document.getElementById('disc-new-code').value=''; document.getElementById('disc-new-value').value='';
    loadDiscountList();
  } catch(e) { st.style.color='var(--sell)'; st.textContent='&#x26A0; '+(e.body?.error||e.message); }
}

async function toggleDiscount(code, activate) {
  if (IS_DEV) { toast('DEV: '+code+' -> '+(activate?'BAT':'TAT')); return; }
  const path=activate?'/api/admin/discount/activate':'/api/admin/discount/deactivate';
  try { await apiPost(path,{telegram_id:USER_ID, code}); loadDiscountList(); }
  catch(e) { toast('Loi: '+e.message); }
}

function _discSetBenefitType(type) { _discBenefitType=type; const on={borderColor:'var(--c0)',background:'#001a33',color:'var(--c0)'},off={borderColor:'var(--bdr)',background:'var(--bg3)',color:'var(--txt2)'}; const apply=(id,st)=>{const el=document.getElementById(id);el.style.borderColor=st.borderColor;el.style.background=st.background;el.style.color=st.color;}; apply('disc-type-pct-btn',type==='discount_pct'?on:off); apply('disc-type-days-btn',type==='free_days'?on:off); }
function _discSetRequiresPurchase(val) { _discRequiresPurchase=val; const on={borderColor:'var(--c0)',background:'#001a33',color:'var(--c0)'},off={borderColor:'var(--bdr)',background:'var(--bg3)',color:'var(--txt2)'}; const apply=(id,st)=>{const el=document.getElementById(id);el.style.borderColor=st.borderColor;el.style.background=st.background;el.style.color=st.color;}; apply('disc-req-yes',val?on:off); apply('disc-req-no',!val?on:off); }

async function loadAdminNavPending() {
  const el=document.getElementById('admin-nav-confirm-list'); el.innerHTML='<div style="font-size:12px;color:var(--txt2)">Dang tai...</div>';
  if (IS_DEV) { el.innerHTML='<div style="font-size:12px;color:var(--txt2)">&#x2713; Khong co NAV nao can xac nhan (DEV)</div>'; return; }
  try {
    const d=await apiFetch('/api/admin/nav/pending'); const list=d.pending||[];
    if (!list.length) { el.innerHTML='<div style="font-size:12px;color:var(--txt2)">&#x2713; Khong co NAV nao can xac nhan</div>'; return; }
    el.innerHTML=list.map(it=>`<div style="border:1px solid #3a2000;border-radius:8px;padding:10px;margin-bottom:8px;background:#0e0800">
      <div style="font-family:var(--mono);font-size:12px;font-weight:700;color:#facc15;margin-bottom:6px">${it.fund_code} &middot; ${it.nav_date}</div>
      <div style="font-size:11px;color:var(--txt2);margin-bottom:8px">Thu cong: <b style="color:var(--txt)">${Number(it.manual_nav).toLocaleString('vi-VN')}</b> &middot; Fetch: <b style="color:var(--txt)">${Number(it.fetch_nav).toLocaleString('vi-VN')}</b></div>
      <div style="display:flex;gap:8px">
        <button onclick="adminNavConfirm('${it.fund_code}','${it.nav_date}','manual')" style="flex:1;padding:8px;background:#001a10;color:var(--buy);border:1px solid var(--buy);border-radius:6px;font-size:12px;font-weight:700;cursor:pointer">&#x2713; Thu cong</button>
        <button onclick="adminNavConfirm('${it.fund_code}','${it.nav_date}','fetch')" style="flex:1;padding:8px;background:#001020;color:var(--c0);border:1px solid var(--c0);border-radius:6px;font-size:12px;font-weight:700;cursor:pointer">&#x2713; Fetch</button>
      </div></div>`).join('');
  } catch(e) { el.innerHTML=`<div style="font-size:12px;color:var(--sell)">Loi: ${e.message}</div>`; }
}

async function adminNavConfirm(fundCode, navDate, choice) {
  try { const d=await apiPost('/api/admin/nav/confirm',{telegram_id:String(USER_ID||''),fund_code:fundCode,nav_date:navDate,choice}); if(d.ok) loadAdminNavPending(); else alert('Loi: '+(d.error||'unknown')); }
  catch(e) { alert('&#x26A0; '+(e.body?.error||e.message)); }
}

async function loadAdminSummary() {
  const el=document.getElementById('admin-summary-box'); el.innerHTML='<div style="font-size:12px;color:var(--txt2)">Dang tai...</div>';
  if (IS_DEV) { el.innerHTML='<div style="font-size:12px">&#x1F465; <b>42</b> user (<span style="color:var(--buy)">8 pro</span> / 34 free)<br>&#x1F3AF; MAPE: arima 3.2% / xgb 2.8% / ensemble 2.1%<br>&#x26A0; 3 quy chua co NAV hom nay</div>'; return; }
  try {
    const d=await apiFetch('/api/admin/summary'); const u=d.users||{};
    let html=`<div style="margin-bottom:8px">&#x1F465; <b>${u.total??'-'}</b> user (<span style="color:var(--buy)">${u.pro??'-'} pro</span> / ${u.free??'-'} free)</div>`;
    html+=`<div style="color:#6b7280;margin-bottom:4px">&#x1F3AF; MAPE (7 ngay):</div>`;
    for (const m of d.model_mape||[]) html+=`<div style="padding:2px 0">${m.model_version}: <b style="color:${(m.mape_7d??99)>8?'var(--sell)':'var(--buy)'}">${m.mape_7d??'-'}%</b></div>`;
    html+=`<div style="margin-top:8px;color:#6b7280">&#x26A0; Chua co NAV hom nay: <b>${(d.funds_missing_today||[]).length}</b></div>`;
    el.innerHTML=html;
  } catch(e) { el.innerHTML=`<div style="color:var(--sell)">Loi: ${e.message}</div>`; }
}

async function loadAdminAudit() {
  const el=document.getElementById('admin-audit-list'); el.innerHTML='Dang tai...';
  if (IS_DEV) { el.innerHTML='<div style="color:var(--txt2)">DEV: Khong co audit log.</div>'; return; }
  try {
    const d=await apiFetch('/api/admin/audit?limit=50'); const list=d.log||[];
    if (!list.length) { el.innerHTML='<div style="color:var(--txt2)">Chua co log nao</div>'; return; }
    el.innerHTML=list.map(row=>{const t=row.created_at?new Date(row.created_at).toLocaleString('vi-VN',{hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit'}):'';return`<div style="border-bottom:1px solid var(--bdr);padding:5px 0"><span style="color:#6b7280">${t}</span> &middot; <span style="color:var(--c0);font-weight:700">${row.action}</span>${row.note?' &middot; <span style="color:var(--txt2)">'+row.note+'</span>':''}</div>`;}).join('');
  } catch(e) { el.innerHTML=`<div style="color:var(--sell)">Loi: ${e.message}</div>`; }
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setDcaStyle('dca');
  _refreshGoldProductSelect();
  const td = document.getElementById('trade-date'); if (td) td.value = _todayISO();
  const gd = document.getElementById('gold-date');  if (gd) gd.value  = _todayISO();
  loadMe();
  loadMarket();
});
