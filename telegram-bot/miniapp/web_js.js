// ── Config ──────────────────────────────────────────────────────────────────
const API_BASE = window.location.origin;
const qs = new URLSearchParams(location.search);
const IS_DEV  = qs.get('dev') === '1' || location.hash === '#dev';
const IS_BETA = qs.get('beta') === '1';

// Telegram WebApp auth — ưu tiên Telegram SDK, fallback web session, fallback URL params
const _tg = window.Telegram?.WebApp;
const _tgUser = _tg?.initDataUnsafe?.user;
const _INIT_DATA = _tg?.initData || '';  // dùng làm X-Init-Data header

// Web session (standalone browser mode — sau khi login qua Telegram Login Widget)
const _WEB_SESSION_LS = 'ftp_web_session';
const _UID_LS = 'ftp_uid';
const _NAME_LS = 'ftp_name';
let _webSession = localStorage.getItem(_WEB_SESSION_LS) || '';

// USER_ID: Telegram > localStorage từ web login > URL param (dev only)
const USER_ID   = String(_tgUser?.id   || localStorage.getItem(_UID_LS)  || qs.get('user_id')  || '');
const USER_NAME = String(_tgUser?.first_name || localStorage.getItem(_NAME_LS) || qs.get('name') || '');

function _saveWebSession(token, uid, name) {
  localStorage.setItem(_WEB_SESSION_LS, token);
  localStorage.setItem(_UID_LS, String(uid));
  localStorage.setItem(_NAME_LS, String(name));
  _webSession = token;
}
function _clearWebSession() {
  localStorage.removeItem(_WEB_SESSION_LS);
  localStorage.removeItem(_UID_LS);
  localStorage.removeItem(_NAME_LS);
  _webSession = '';
}

if (_tg) { _tg.ready(); _tg.expand(); }

// ── Web standalone login (Telegram Login Widget) ──────────────────────────────
// Chỉ dùng khi mở trong browser thường (không phải Telegram Mini App).
// Flow: user click "Đăng nhập với Telegram" → widget popup → callback _onTelegramLogin
// → POST /api/auth/telegram-login → nhận token → lưu localStorage → reload app.

function _needsWebLogin() {
  // Cần login nếu: không phải Telegram Mini App, không có session, không phải IS_DEV
  return !_tg && !_webSession && !IS_DEV && !USER_ID;
}

function _showLoginScreen() {
  const el = document.getElementById('login-overlay');
  if (el) el.style.display = 'flex';
}

function _hideLoginScreen() {
  const el = document.getElementById('login-overlay');
  if (el) el.style.display = 'none';
}

// Được gọi bởi Telegram Login Widget sau khi user xác thực thành công
async function _onTelegramLogin(data) {
  try {
    const res = await fetch(API_BASE + '/api/auth/telegram-login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    if (!res.ok) { const e = await res.json().catch(()=>{}); alert('Đăng nhập thất bại: ' + (e?.error||res.status)); return; }
    const json = await res.json();
    if (json.token) {
      _saveWebSession(json.token, json.telegram_id || data.id, json.name || data.first_name);
      _hideLoginScreen();
      location.reload();  // reload để USER_ID được set đúng từ localStorage
    } else {
      alert('Lỗi: server không trả về token');
    }
  } catch(e) {
    alert('Lỗi kết nối: ' + e.message);
  }
}

function logoutWeb() {
  _clearWebSession();
  location.reload();
}

function _loadTelegramWidget() {
  // Inject Telegram Login Widget script — bot username lấy từ /api/me hoặc config
  // Widget gọi window._onTelegramLogin(data) khi user xác thực xong
  const wrap = document.getElementById('login-widget-wrap');
  if (!wrap) return;
  wrap.innerHTML = '<div style="color:var(--txt2);font-size:12px">Đang tải widget Telegram...</div>';
  fetch(API_BASE + '/health').then(r=>r.json()).then(cfg => {
    const botUsername = cfg.bot_username || '';
    if (!botUsername) { wrap.innerHTML = '<div style="color:var(--sell);font-size:12px">Chưa cấu hình bot username. Liên hệ admin.</div>'; return; }
    const s = document.createElement('script');
    s.src = 'https://telegram.org/js/telegram-widget.js?22';
    s.setAttribute('data-telegram-login', botUsername);
    s.setAttribute('data-size', 'large');
    s.setAttribute('data-onauth', '_onTelegramLogin(user)');
    s.setAttribute('data-request-access', 'write');
    s.async = true;
    wrap.innerHTML = '';
    wrap.appendChild(s);
  }).catch(() => {
    wrap.innerHTML = '<div style="color:var(--sell);font-size:12px">Không kết nối được server. Thử lại sau.</div>';
  });
}

// ── State ────────────────────────────────────────────────────────────────────
let _me = null, _signals = null, _goldData = null, _allFunds = {}, _watchedSet = new Set();
let _tradeType = 'buy', _goldType = 'buy', _goldUnit = 'chi', _goldPredType = 'buy';
let _dcaStyle = 'dca', _tradeLog = [], _goldTrades = [], _marketFilter = 'all', _marketData = null;
let _navChart = null, _homeChart = null, _discBenefitType = 'discount_pct', _discRequiresPurchase = true;
let _selectedPlan = 'm1', _toastTimer;
let _navHistoryFull = {}, _chartRange = '1Y', _currentChartCanvas = 'home-inline-chart';
// Edit modal state
let _editTradeType = 'buy', _editGoldType = 'buy';
// History filter state
let _histFilterAsset = 'all', _histFilterCode = '', _histFilterFrom = '', _histFilterTo = '';
// Watch modal state
let _allFundsList = {}, _watchToggleSet = new Set();
// Gold DCA school state
let _goldSchool = 'dca';
// History page state
let _histPageCode = '', _histPageData = null, _histPageChart = null;
// Payment state
let _paymentMethod = 'stars', _sepayRef = null, _sepayTimer = null;
// Easter egg state
let _tapCount = 0, _tapTimer = null;

// Crosshair plugin cho Chart.js
const _crosshairPlugin = {
  id: 'crosshair',
  afterDraw(chart) {
    if (!chart.tooltip._active?.length) return;
    const ctx = chart.ctx, x = chart.tooltip._active[0].element.x, y = chart.scales;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(x, y.y.top);
    ctx.lineTo(x, y.y.bottom);
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(0,229,255,.25)';
    ctx.setLineDash([4, 3]);
    ctx.stroke();
    ctx.restore();
  }
};

// ── Mock NAV history generator ────────────────────────────────────────────────
function _mockNavHistory(baseNav, days=120) {
  const pts=[];
  let nav=baseNav*(0.80+Math.random()*0.08);
  for(let i=days;i>=0;i--){
    const d=new Date();d.setDate(d.getDate()-i);
    if(d.getDay()===0||d.getDay()===6) continue; // skip weekends
    nav*=(1+(Math.random()-0.46)*0.007);
    nav=Math.max(nav,baseNav*0.65);
    pts.push({date:d.toISOString().slice(0,10),nav:Math.round(nav)});
  }
  // Nudge last point close to baseNav
  if(pts.length) pts[pts.length-1].nav=Math.round(baseNav*(0.98+Math.random()*0.04));
  return pts;
}

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
  dca:  '<b>DCA (Dollar Cost Averaging)</b> — Đầu tư cố định mỗi kỳ. Đơn giản, hiệu quả lâu dài, không cần phân tích.',
  vca:  '<b>VCA (Value Cost Averaging)</b> — Đầu tư nhiều hơn khi giá thấp, ít hơn khi giá cao. Tối ưu hơn DCA thường.',
  ca:   '<b>CA (Cost Averaging)</b> — Mua thêm để hạ giá vốn trung bình. Phù hợp khi quỹ đang giảm.',
  lump: '<b>LUMP SUM</b> — Đầu tư một lần toàn bộ vốn. Hiệu quả nhất khi thị trường đang ở đáy thấp.',
  smart:'<b>SMART (AI Mix)</b> — Kết hợp VCA + tín hiệu RSI/MACD. Phân bổ theo điểm tín hiệu mỗi quỹ.',
};

// ── Utils ────────────────────────────────────────────────────────────────────
const fmt   = n => n == null ? '—' : Number(n).toLocaleString('vi-VN');
const fmtP  = p => (p >= 0 ? '+' : '') + Number(p).toFixed(2) + '%';
const pnlC  = p => p > 0.01 ? 'pos' : p < -0.01 ? 'neg' : 'zero';
const sigC  = s => { if (!s || s === 'N/A') return 'na'; const u = s.toUpperCase(); if (u.includes('MUA')) return 'buy'; if (u.includes('BAN') || u.includes('BÁN')) return 'sell'; return 'hold'; };
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
function _authHeaders() {
  const h = {'Content-Type':'application/json'};
  if (_INIT_DATA) h['X-Init-Data'] = _INIT_DATA;
  else if (_webSession) h['X-Web-Session'] = _webSession;
  return h;
}
async function apiFetch(path, ms=12000) {
  const sep = path.includes('?') ? '&' : '?';
  let qs2 = USER_ID ? sep+'user_id='+USER_ID : '';
  if (USER_ID && USER_NAME) qs2 += '&name='+encodeURIComponent(USER_NAME);
  if (IS_BETA) qs2 += '&beta=1';
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(API_BASE+path+qs2, {headers:_authHeaders(), signal:ctrl.signal});
    clearTimeout(tid);
    if (r.status === 401 && !_tg && !IS_DEV) { _clearWebSession(); _showLoginScreen(); throw new Error('Phiên hết hạn'); }
    if (!r.ok) { const e=await r.json().catch(()=>({})); const err=new Error(e.error||r.status); err.body=e; err.status=r.status; throw err; }
    return r.json();
  } catch(e) { clearTimeout(tid); throw e.name==='AbortError' ? new Error('Timeout') : e; }
}
async function apiPost(path, body, ms=12000) {
  if (IS_BETA && body && typeof body === 'object') body = {...body, beta: true};
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
const TAB_TITLES = {home:'TRANG CHỦ', trade:'GIAO DỊCH', history:'LỊCH SỬ NAV', user:'TÀI KHOẢN'};
function goTab(name, btn) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  const page = document.getElementById('page-'+name);
  if (page) page.classList.add('active');
  if (btn) btn.classList.add('active');
  const titleEl = document.getElementById('header-title');
  if (titleEl) titleEl.textContent = TAB_TITLES[name] || name.toUpperCase();
  const searchEl = document.getElementById('market-search')?.closest('.header-search');
  if (searchEl) searchEl.style.display = name === 'home' ? '' : 'none';
  if (name === 'home')    { if (!_me) loadMe(); if (!_marketData) loadMarket(); }
  if (name === 'trade')   { if (!_signals) loadSignals(); loadUnifiedHistory(); setDcaStyle(_dcaStyle); }
  if (name === 'history') loadHistoryPage();
  if (name === 'user')    loadAccountTab();
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
  if (isAdmin) { const as=document.getElementById('admin-section'); if(as) as.style.display=''; loadAdminTab(); }
}

// ── Portfolio ─────────────────────────────────────────────────────────────────
async function loadMe() {
  if (IS_DEV) { _me = MOCK_ME; _goldData = MOCK_GOLD; renderTierBar(_me); renderPortfolio(_me); return; }
  if (_needsWebLogin()) { _showLoginScreen(); return; }
  if (!USER_ID) { document.getElementById('pf-sub-ccq').innerHTML=renderErr('Cần user_id. Mở từ Telegram bot hoặc thêm ?user_id=... vào URL.'); return; }
  try {
    _me = await apiFetch('/api/me');
    renderTierBar(_me);
    apiFetch(`/api/gold?user_id=${USER_ID}`).then(d=>{_goldData=d;renderPfBanner();renderPfAlloc();renderPfGoldSub();}).catch(()=>{});
    renderPortfolio(_me);
  } catch(e) { document.getElementById('pf-sub-ccq').innerHTML=renderErr('Lỗi tải: '+e.message); }
}

function renderPfBanner() {
  const pf=_me?.portfolio, gp=_goldData?.portfolio;
  const ccqVal=pf?.total_value||0, goldVal=gp?.current_value||0, total=ccqVal+goldVal;
  const totalCost=(pf?.total_cost||0)+(gp?.total_cost||0);
  const totalPnl=total-totalCost, totalPnlPct=totalCost>0?(totalPnl/totalCost*100):0;
  document.getElementById('pf-date').textContent='cập nhật '+new Date().toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'});
  document.getElementById('pf-banner').innerHTML=`<div class="total-banner">
    <div class="total-lbl">Tổng tài sản (CCQ + Vàng)</div>
    <div class="total-val">${fmt(total)} đ</div>
    <div class="total-pnl pnl ${pnlC(totalPnlPct)}">${fmtP(totalPnlPct)} &middot; ${totalPnl>=0?'+':''}${fmt(Math.round(totalPnl))} đ</div>
  </div>`;
}

function renderPfAlloc() {
  const ccqVal=_me?.portfolio?.total_value||0, goldVal=_goldData?.portfolio?.current_value||0, total=ccqVal+goldVal;
  if (!total) return;
  const ccqPct=Math.round(ccqVal/total*100), goldPct=100-ccqPct;
  document.getElementById('pf-alloc').innerHTML=`<div class="alloc-wrap">
    <div style="font-size:11px;color:var(--txt2);margin-bottom:2px">Phân bổ tài sản</div>
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
  // #2: School summary card
  if (pf.items.length) {
    const summEl=document.getElementById('pf-school-summary');
    if (summEl) summEl.innerHTML=renderSchoolSummary(pf.items);
  }
  if (!pf.items.length) {
    html=`<div class="card" style="text-align:center;color:var(--txt2);padding:24px">Chưa có giao dịch CCQ.<br>Thêm ở tab Giao Dịch.</div>`;
  } else {
    html='<div class="card">';
    for (const h of pf.items) {
      const chg=h.chg_pct||0;
      const navSrc = h.nav_source || '';
      const navBadgeTxt = navSrc==='provisional'?'est':navSrc==='pending_confirm'?'pend':navSrc==='confirmed'?'conf':navSrc==='fixed'?'fix':navSrc==='manual'?'man':'';
      const navBadgeCol = (navSrc==='confirmed'||navSrc==='fixed')?'var(--buy)':navSrc==='pending_confirm'?'#fbbf24':'var(--txt2)';
      const navBadge = navBadgeTxt ? `<span style="font-size:9px;color:${navBadgeCol};border:1px solid ${navBadgeCol};border-radius:3px;padding:0 3px;margin-left:4px;font-family:var(--mono)">${navBadgeTxt}</span>` : '';
      html+=`<div class="fund-row" onclick="openResearch('${h.code}')">
        <div class="fund-info">
          <div class="fund-top">
            <span class="fund-code">${h.code}</span>
            <span class="fund-nav">${fmt(h.nav)} đ${navBadge}</span>
            <span class="pnl ${pnlC(chg)}" style="font-size:11px">${fmtP(chg)}</span>
          </div>
          <div class="fund-sub"><span>${fmt(h.units)} CCQ</span><span style="opacity:.4">&middot;</span><span>Giá vốn ${fmt(h.avg_cost)} đ</span></div>
        </div>
        <div class="fund-right">
          <div class="badge ${sigC(h.signal)}">${sigLabel(h.signal)}</div>
          <div class="pnl ${pnlC(h.pnl_pct)}" style="font-size:12px">${fmtP(h.pnl_pct)}</div>
          <div style="font-size:11px;color:var(--txt2)">${h.pnl>=0?'+':''}${fmt(h.pnl)}</div>
        </div>
      </div>`;
    }
    html+='</div>';
    const costDetail=pf.items.map(h=>{const pct=pf.total_cost?(h.cost/pf.total_cost*100):0;return`<div class="sum-detail-row"><span>${h.code}</span><span>${fmt(h.cost)} đ <span class="sum-detail-pct">(${pct.toFixed(1)}%)</span></span></div>`;}).join('');
    const valueDetail=pf.items.map(h=>{const pct=pf.total_value?(h.value/pf.total_value*100):0;return`<div class="sum-detail-row"><span>${h.code}</span><span class="pnl ${pnlC(h.pnl_pct)}">${fmt(h.value)} đ <span class="sum-detail-pct">(${pct.toFixed(1)}%)</span></span></div>`;}).join('');
    html+=`<div class="card">
      <div class="sum-row sum-row-toggle" onclick="toggleSumDetail('sd-cost',this)"><span class="sum-label">Vốn CCQ <span class="sum-chevron">&#9660;</span></span><span class="sum-val">${fmt(pf.total_cost)} đ</span></div>
      <div id="sd-cost" class="sum-detail" style="display:none">${costDetail}</div>
      <div class="sum-row sum-row-toggle" onclick="toggleSumDetail('sd-value',this)"><span class="sum-label">Giá trị hiện tại <span class="sum-chevron">&#9660;</span></span><span class="sum-val">${fmt(pf.total_value)} đ</span></div>
      <div id="sd-value" class="sum-detail" style="display:none">${valueDetail}</div>
      <div class="sum-row"><span class="sum-label">Lãi/lỗ CCQ</span><span class="sum-val pnl ${pnlC(pf.total_pnl_pct)}">${pf.total_pnl>=0?'+':''}${fmt(pf.total_pnl)} đ</span></div>
    </div>`;
  }
  document.getElementById('pf-sub-ccq').innerHTML=html;
}

function renderPfGoldSub() {
  const el=document.getElementById('pf-sub-gold');
  if (!_goldData) { el.innerHTML=spin(); return; }
  const pf=_goldData.portfolio;
  if (!pf||pf.total_luong===0) { el.innerHTML='<div class="card" style="text-align:center;color:var(--txt2);padding:24px">Chưa có danh mục vàng.<br>Thêm ở Giao Dịch → Vàng.</div>'; return; }
  const pnlSign=pf.pnl>=0?'+':'';
  let html=`<div class="card">
    <div class="sum-row"><span class="sum-label">Tổng số lượng</span><span class="sum-val" style="color:var(--c0)">${pf.total_luong} lượng</span></div>
    <div class="sum-row"><span class="sum-label">Giá trị hiện tại</span><span class="sum-val">${fmt(pf.current_value)} đ</span></div>
    <div class="sum-row"><span class="sum-label">Vốn</span><span class="sum-val">${fmt(pf.total_cost)} đ</span></div>
    <div class="sum-row"><span class="sum-label">Lãi/lỗ</span><span class="sum-val pnl ${pnlC(pf.pnl)}">${pnlSign}${fmt(pf.pnl)} đ (${fmtP(pf.pnl_pct)})</span></div>
  </div>`;
  for (const [prod,pp] of Object.entries(pf.by_product||{})) {
    if (pp.price_missing) {
      html+=`<div class="card" style="border-color:#854d0e"><div class="card-title">${pp.label||prod}</div>
        <div class="sum-row"><span class="sum-label">Số lượng</span><span class="sum-val" style="color:var(--c0)">${pp.luong} lượng</span></div>
        <div style="font-size:11px;color:#facc15;margin-top:4px">&#9888; Chưa có giá thị trường</div></div>`;
      continue;
    }
    const ppnl=pp.pnl||0, ppnlSign=ppnl>=0?'+':'';
    const hasSubItems = prod==='OTHER' && pp.sub_items?.length;
    const subBreakdown = hasSubItems ? pp.sub_items.map((s,si)=>`<div class="sum-detail-row"><span style="color:var(--txt2)">${s.name||'Vàng khác'}</span><span style="font-family:var(--mono);font-size:11px">${s.luong} lượng</span></div>`).join('') : '';
    html+=`<div class="card">
      <div class="card-title" ${hasSubItems?`style="cursor:pointer;display:flex;align-items:center;gap:6px" onclick="_toggleOtherGoldBreakdown(this.parentElement)"`:''}>
        ${pp.label||prod}${hasSubItems?'<span class="other-gold-chevron" style="font-size:10px;color:var(--txt2);margin-left:auto;transition:transform .2s">▼</span>':''}
      </div>
      ${hasSubItems?`<div class="other-gold-breakdown" style="display:none;background:var(--bg2);border-radius:6px;padding:6px 10px;margin:4px 0">${subBreakdown}</div>`:''}
      <div class="sum-row"><span class="sum-label">Số lượng</span><span class="sum-val" style="color:var(--c0)">${pp.luong} lượng</span></div>
      <div class="sum-row"><span class="sum-label">Giá mua TB</span><span class="sum-val">${fmt(pp.avg_cost)} đ/lượng</span></div>
      <div class="sum-row"><span class="sum-label">Giá hiện tại</span><span class="sum-val">${fmt(pp.price_buy||pp.price)} đ/lượng</span></div>
      <div class="sum-row"><span class="sum-label">Lãi/lỗ</span><span class="sum-val pnl ${pnlC(ppnl)}">${ppnlSign}${fmt(ppnl)} đ (${fmtP(pp.pnl_pct||0)})</span></div>
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
  } catch(e) { document.getElementById('market-content').innerHTML=renderErr('Lỗi tải thị trường: '+e.message); }
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
  if (!codes.length) { document.getElementById('market-content').innerHTML='<div style="text-align:center;color:var(--txt2);padding:20px">Không có quỹ nào.</div>'; return; }
  let html='<div class="card">';
  for (const code of codes) {
    const s=_marketData[code];
    const rsi=s.rsi??50, bb=s.bb_pct??50, chg=s.chg_pct||0;
    const rsiC=rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--hold)';
    const bbC=bb<20?'var(--buy)':bb>80?'var(--sell)':'var(--hold)';
    const alertIcon = (s.data_stale||s.nav_stale||s.alert||s.nav_jump_anomaly)
      ? `<span title="${s.alert||'Dữ liệu hoặc NAV có thể chưa cập nhật'}" style="color:#facc15;font-size:9px;line-height:1">⚠</span>` : '';
    const isWatched = (_me?.watched_funds||[]).includes(code);
    html+=`<div class="sig-row" onclick="openResearch('${code}')" data-code="${code}">
      <div>
        <div style="display:flex;align-items:center;gap:5px">
          <span class="sig-code">${code}</span>
          <span class="pnl ${pnlC(chg)}" style="font-size:11px">${fmtP(chg)}</span>
          ${s.has_position?'<span style="font-size:9px;color:var(--c0);font-family:var(--mono)">&#x2022;NẮM</span>':''}
          ${alertIcon}
        </div>
        <div style="font-size:11px;color:var(--txt2)">${fmt(s.nav)} đ</div>
      </div>
      <div class="sig-meters">
        <div class="meter"><div class="meter-lbl">RSI</div><div class="meter-bar"><div class="meter-fill" style="width:${rsi}%;background:${rsiC}"></div></div><div class="meter-val">${rsi.toFixed?rsi.toFixed(0):rsi}</div></div>
        <div class="meter"><div class="meter-lbl">BB%</div><div class="meter-bar"><div class="meter-fill" style="width:${bb}%;background:${bbC}"></div></div><div class="meter-val">${bb.toFixed?bb.toFixed(0):bb}</div></div>
        <div class="meter"><div class="meter-lbl">SCR</div><div class="meter-val" style="font-size:11px;color:${(s.score||0)>=3?'var(--buy)':(s.score||0)<=-3?'var(--sell)':'var(--txt)'}">${(s.score>=0?'+':'')}${s.score||0}</div></div>
      </div>
      <div style="text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:3px">
        <div class="badge ${sigC(s.signal)}">${sigLabel(s.signal)}</div>
        <span class="watch-star" onclick="event.stopPropagation();_quickWatch('${code}',event)" title="${isWatched?'Bỏ theo dõi':'Thêm theo dõi'}" style="cursor:pointer;font-size:13px;color:${isWatched?'var(--c0)':'var(--txt3)'}">${isWatched?'★':'☆'}</span>
      </div>
    </div>`;
  }
  html+='</div>';
  document.getElementById('market-content').innerHTML=html;
  // WEB-015: stale NAV banner
  const allMarketCodes = Object.keys(_marketData||{});
  const staleCodes = allMarketCodes.filter(c=>_marketData[c].nav_stale||_marketData[c].data_stale);
  const staleBanner = document.getElementById('market-stale-banner');
  if(staleBanner) {
    if(staleCodes.length) {
      staleBanner.style.display='block';
      staleBanner.innerHTML=`<div style="background:rgba(250,204,21,.08);border-left:3px solid #facc15;padding:7px 12px;margin:0 0 2px;font-size:11px;color:#facc15;display:flex;align-items:center;gap:8px">
        <span style="font-size:13px">⚠</span>
        <span>${staleCodes.length} quỹ chưa cập nhật NAV hôm nay:
        <span style="font-family:var(--mono)">${staleCodes.slice(0,5).join(', ')}${staleCodes.length>5?`…+${staleCodes.length-5}`:''}</span></span>
      </div>`;
    } else {
      staleBanner.style.display='none';
      staleBanner.innerHTML='';
    }
  }
  // WEB-010: auto-select first held fund on initial load so chart-col is never empty
  const colEl = document.getElementById('chart-col-content');
  if (colEl && !colEl.children.length) {
    const autoCode = codes.find(c => _marketData[c]?.has_position) || codes[0];
    if (autoCode) setTimeout(()=>openResearch(autoCode), 80);
  }
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
      schools:[], conclusion:'Dev mode — không có dữ liệu thật.', nav_history:_mockNavHistory(s.nav||15000,120)});
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
  if (!codes.length) { document.getElementById('sig-content').innerHTML='<div style="text-align:center;color:var(--txt2);padding:24px">Chưa có quỹ theo dõi.<br>Mua CCQ ở tab Giao Dịch.</div>'; return; }
  let html='<div class="card">';
  for (const code of codes) {
    const s=sigs[code]; const rsi=s.rsi??50,bb=s.bb_pct??50,chg=s.chg_pct||0;
    const rsiC=rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--hold)';
    const bbC=bb<20?'var(--buy)':bb>80?'var(--sell)':'var(--hold)';
    html+=`<div class="sig-row" onclick="openResearch('${code}')">
      <div>
        <div style="display:flex;align-items:baseline;gap:6px"><span class="sig-code">${code}</span><span class="pnl ${pnlC(chg)}" style="font-size:11px">${fmtP(chg)}</span></div>
        <div style="font-size:11px;color:var(--txt2)">${fmt(s.nav)} đ</div>
      </div>
      <div class="sig-meters">
        <div class="meter"><div class="meter-lbl">RSI</div><div class="meter-bar"><div class="meter-fill" style="width:${rsi}%;background:${rsiC}"></div></div><div class="meter-val">${rsi.toFixed?rsi.toFixed(0):rsi}</div></div>
        <div class="meter"><div class="meter-lbl">BB%</div><div class="meter-bar"><div class="meter-fill" style="width:${bb}%;background:${bbC}"></div></div><div class="meter-val">${bb.toFixed?bb.toFixed(0):bb}</div></div>
      </div>
      <div style="text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:4px">
        <div class="badge ${sigC(s.signal)}">${sigLabel(s.signal)}</div>
        <button onclick="event.stopPropagation();openAlertModal('${code}')" style="background:none;border:1px solid var(--bdr);color:var(--txt2);border-radius:5px;padding:2px 6px;font-size:10px;cursor:pointer">🔔</button>
      </div>
    </div>`;
  }
  html+='</div>';
  document.getElementById('sig-content').innerHTML=html;
  // Auto-hiển thị chart quỹ đang nắm đầu tiên (xóa empty state)
  if (codes.length && !_researchCode) { setTimeout(()=>openResearch(codes[0]),100); }
}

// ── Research Modal ────────────────────────────────────────────────────────────
let _researchCode = null;
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

// ── Time range filter ─────────────────────────────────────────────────────────
async function setChartRange(range, btn) {
  _chartRange = range;
  document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  if (!_researchCode) return;
  // For ALL: try to fetch complete history if we only have a subset
  if (range === 'ALL' && !_navHistoryFull[_researchCode + '_fullFetched'] && !IS_DEV) {
    try {
      const d = await apiFetch(`/api/nav_history/${_researchCode}`);
      const h = Array.isArray(d) ? d : (d.history || []);
      if (h.length > (_navHistoryFull[_researchCode]?.length || 0)) {
        _navHistoryFull[_researchCode] = h;
      }
    } catch(e) { /* use cached data */ }
    _navHistoryFull[_researchCode + '_fullFetched'] = true;
  }
  const hist = _navHistoryFull[_researchCode];
  if (hist?.length) _redrawNavChart(_filterByRange(hist, range));
}

function _filterByRange(history, range) {
  if (!history?.length || range === 'ALL') return history;
  const months = {'1M':1,'3M':3,'1Y':12,'3Y':36};
  const m = months[range] || 12;
  const cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - m);
  const cutoffStr = cutoff.toISOString().slice(0,10);
  const filtered = history.filter(r => r.date >= cutoffStr);
  return filtered.length > 1 ? filtered : history;
}

function _redrawNavChart(history, canvasId) {
  canvasId = canvasId || _currentChartCanvas;
  if (!canvasId) return;
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  // Destroy any existing Chart.js instance on this canvas (including those not in _navChart)
  const existing = Chart.getChart(canvas);
  if (existing) existing.destroy();
  if (_navChart) { _navChart.destroy(); _navChart = null; }
  const ctx = canvas.getContext('2d');
  _navChart = new Chart(ctx, {
    type: 'line',
    plugins: [_crosshairPlugin],
    data: {
      labels: history.map(r => r.date),
      datasets: [{
        data: history.map(r => r.nav),
        borderColor: '#00e5ff',
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: '#00e5ff',
        fill: true,
        backgroundColor: 'rgba(0,229,255,.07)',
        tension: 0.3
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: true,
          backgroundColor: '#0d1520',
          borderColor: 'rgba(0,229,255,.3)',
          borderWidth: 1,
          titleFont: { family: 'IBM Plex Mono', size: 10 },
          bodyFont: { family: 'IBM Plex Mono', size: 11 },
          callbacks: {
            title: ctx => ctx[0]?.label?.slice(0,10) || '',
            label: ctx => `NAV: ${fmt(ctx.raw)} đ`
          }
        }
      },
      scales: {
        x: { display: false },
        y: {
          grid: { color: 'rgba(255,255,255,.04)' },
          ticks: { font: { family: 'IBM Plex Mono', size: 10 }, color: '#7a9ab8', maxTicksLimit: 4 }
        }
      },
      animation: { duration: 200 }
    }
  });
}

async function openResearch(code) {
  _researchCode = code;
  const homeActive  = document.getElementById('page-home')?.classList.contains('active');
  const tradeActive = document.getElementById('page-trade')?.classList.contains('active');

  let targetEl = null;
  let canvasId = null;

  if (homeActive) {
    targetEl = document.getElementById('chart-col-content');
    canvasId = 'home-inline-chart';
    const titleEl = document.getElementById('chart-col-title');
    if (titleEl) titleEl.textContent = code;
    if (targetEl) targetEl.innerHTML = spin();
    if (_navChart) { _navChart.destroy(); _navChart = null; }
    const rangeBar = document.getElementById('chart-range-bar');
    if (rangeBar) rangeBar.style.display = 'flex';
  } else if (tradeActive) {
    targetEl = document.getElementById('trade-signal-research');
    canvasId = 'trade-inline-chart';
    if (targetEl) { targetEl.style.display = ''; targetEl.innerHTML = spin(); }
    if (_navChart) { _navChart.destroy(); _navChart = null; }
  } else {
    document.getElementById('modal').classList.add('open');
    document.getElementById('modal-body').innerHTML = spin();
    setModalTitle(code, '');
    canvasId = 'modal-nav-chart';
  }
  _currentChartCanvas = canvasId;

  if (IS_DEV) {
    const s = MOCK_SIGNALS[code] || {nav:0,rsi:50,bb_pct:50,score:0,signal:'N/A',chg_pct:0};
    const d = {code, name:code+' (dev)', signal:s.signal, nav:s.nav, chg_pct:s.chg_pct, rsi:s.rsi, bb:s.bb_pct, macd:s.macd||0, score:s.score, schools:[], conclusion:'Dev mode.', nav_history:_mockNavHistory(s.nav||15000,120)};
    if (targetEl) renderResearchInline(d, targetEl, canvasId);
    else renderResearch(d);
    return;
  }
  try {
    const d = await apiFetch(`/api/research/${code}`);
    if (d.nav_history?.length) _navHistoryFull[code] = d.nav_history;
    if (targetEl) renderResearchInline(d, targetEl, canvasId);
    else renderResearch(d);
  } catch(e) {
    const errHtml = renderErr('Lỗi: '+e.message);
    if (targetEl) targetEl.innerHTML = errHtml;
    else document.getElementById('modal-body').innerHTML = errHtml;
  }
}

function _computeSchools(d) {
  const rsi = d.rsi ?? 50, bb = d.bb ?? 50, macd = d.macd || 0, score = d.score || 0, chg = d.chg_pct || 0;
  const r = rsi.toFixed(1), b = bb.toFixed(1), m = typeof macd === 'number' ? macd.toFixed(4) : macd;

  // Technical — BÁN khi RSI>70 hoặc BB%>85 (cực kỳ overbought)
  let ts, tt, td, ta;
  if (rsi > 70 || bb > 85) {
    ts='BÁN'; tt='Quỹ đang trong vùng mua quá mức — áp lực bán đang tăng.';
    td=`RSI=${r}${rsi>70?' >70 (mua quá mức)':''}, BB%=${b}${bb>85?' >85 (overbought cực đoan trên Bollinger)':' cận dải trên'}, MACD=${m}. Rủi ro điều chỉnh ngắn hạn cao.`;
    ta='⚠ Cân nhắc chốt lời một phần, không mua thêm lúc này';
  } else if (rsi < 35 && bb < 25) {
    ts='MUA'; tt='Quỹ đang bị bán quá mức — cơ hội tích lũy theo phân tích kỹ thuật.';
    td=`RSI=${r} <35 (bán quá mức), BB%=${b} <25 (gần dải dưới), MACD=${m}. Tín hiệu phục hồi kỹ thuật có thể xuất hiện sớm.`;
    ta='✓ Có thể mua thêm theo phương pháp kỹ thuật';
  } else {
    ts='TRUNG LẬP'; tt='Chỉ số kỹ thuật ở vùng trung tính, chưa có tín hiệu mạnh.';
    td=`RSI=${r}, BB%=${b}, MACD=${m}. Thị trường đang tích lũy. Chờ RSI xuống <35 hoặc lên >70 để có tín hiệu rõ hơn.`;
    ta='→ Theo dõi thêm, chưa vào lệnh mới';
  }

  // Value (Buffett/Graham)
  let vs, vt, vd, va;
  if (score <= -3) {
    vs='MUA'; vt='Thị trường đang bi quan thái quá — cơ hội tích lũy cho nhà đầu tư giá trị dài hạn.';
    vd=`Score=${score}. Theo Warren Buffett: "Hãy tham lam khi người khác sợ hãi." Mức bi quan hiện tại tạo cơ hội mua với giá tốt. Phù hợp horizon ≥3 năm.`;
    va='✓ Tích lũy từng đợt, không đặt tất cả cùng lúc';
  } else if (score >= 3) {
    vs='TRUNG LẬP'; vt='Thị trường đang lạc quan — nhà đầu tư giá trị thận trọng, cân nhắc chốt lời từng phần.';
    vd=`Score=${score}. Khi mọi người đang tham lam, đây là lúc đánh giá lại tỷ trọng. Không bán hết vì xu hướng dài hạn chưa đổi, nhưng giảm exposure là hợp lý.`;
    va='→ Chốt lời 20–30% nếu đang có lãi ≥15%';
  } else {
    vs='TRUNG LẬP'; vt='Chưa đủ tín hiệu định giá cực đoan. DCA đều đặn là chiến lược phù hợp nhất.';
    vd=`Score=${score}. Không phải vùng mua mạnh cũng không phải đỉnh. Tiếp tục kế hoạch DCA hàng tháng, không bị ảnh hưởng bởi biến động ngắn hạn.`;
    va='→ Giữ nguyên danh mục, DCA theo lịch';
  }

  // Momentum
  let ms, mt, md, ma;
  if (macd > 0 && chg >= 0) {
    ms='MUA'; mt='MACD dương và NAV tăng — động lượng ngắn hạn đang thuận chiều mua.';
    md=`MACD Hist=${m} (dương), NAV ${chg>=0?'+':''}${chg.toFixed(2)}% hôm nay. Xu hướng tăng ngắn hạn rõ ràng. Momentum trader thường mua khi MACD vừa cắt lên.`;
    ma='✓ Xu hướng tăng — phù hợp mua theo đà momentum';
  } else if (macd < 0 && chg < 0) {
    ms='BÁN'; mt='MACD âm và NAV giảm — xu hướng đang bất lợi, thận trọng.';
    md=`MACD Hist=${m} (âm), NAV ${chg.toFixed(2)}%. Momentum giảm. Chờ MACD cắt lên đường tín hiệu mới cân nhắc mua.`;
    ma='⚠ Chờ MACD đảo chiều trước khi mua thêm';
  } else {
    ms='TRUNG LẬP'; mt='Tín hiệu xu hướng lẫn lộn — thị trường đang chuyển giai đoạn.';
    md=`MACD Hist=${m}, NAV ${chg>=0?'+':''}${chg.toFixed(2)}%. Một trong hai chỉ số đang nghịch chiều, cần xác nhận thêm vài phiên.`;
    ma='→ Chờ tín hiệu đồng thuận giữa MACD và giá';
  }

  // DCA (Dalio style — all-weather)
  let ds, dt, dd, da;
  if (rsi < 40) {
    ds='MUA'; dt='Giá đang thấp hơn trung bình — thời điểm tốt để tăng lượng DCA kỳ này.';
    dd=`RSI=${r} <40. Theo nguyên tắc DCA: mua nhiều hơn khi giá thấp để hạ giá vốn bình quân. Nếu DCA thường lệ 1 triệu/tháng, kỳ này có thể tăng lên 1.5 triệu.`;
    da='✓ Tăng 150% DCA kỳ này';
  } else if (rsi > 70) {
    ds='TRUNG LẬP'; dt='Giá đang cao — giảm DCA kỳ này để tiết kiệm ngân sách mua ở vùng thấp hơn.';
    dd=`RSI=${r} >70. Giảm DCA 50% kỳ này (VD: từ 1 triệu xuống 500k). Số tiền tiết kiệm dùng để tăng DCA khi RSI quay về <40.`;
    da='→ Giảm 50% DCA, dành tiền cho lần giá thấp';
  } else {
    ds='TRUNG LẬP'; dt='Giá đang trung tính — tiếp tục DCA theo kế hoạch, không điều chỉnh đặc biệt.';
    dd=`RSI=${r} — vùng trung tính. Duy trì lịch DCA cố định 2–4 tuần/lần. Nguyên tắc Dalio: phân bổ đều đặn, không cố đoán đỉnh/đáy.`;
    da='✓ DCA đều đặn theo kế hoạch cố định';
  }

  // Risk (Markowitz)
  let rs, rt, rd, ra;
  if (bb > 85) {
    rs='BÁN'; rt='Biến động cao bất thường — giảm vị thế để kiểm soát rủi ro danh mục.';
    rd=`BB%=${b} >85 — Bollinger Bands đang rất rộng, biến động cao. Theo lý thuyết Markowitz, khi volatility tăng, tỷ trọng tối ưu của tài sản này nên giảm xuống.`;
    ra='⚠ Không tăng vị thế khi biến động cao — cân nhắc giảm 20%';
  } else if (bb < 15) {
    rs='MUA'; rt='Biến động rất thấp — tín hiệu bình yên trước giai đoạn bứt phá.';
    rd=`BB%=${b} <15 — Bollinger Bands co hẹp. Thường báo hiệu sắp có biến động lớn (có thể tăng hoặc giảm). Markowitz: biến động thấp = môi trường tốt để tích lũy.`;
    ra='✓ Biến động thấp — phù hợp tích lũy dần';
  } else {
    rs='TRUNG LẬP'; rt='Mức biến động bình thường — rủi ro danh mục đang ở mức có thể chấp nhận.';
    rd=`BB%=${b}, Score=${score}. Volatility bình thường. Đảm bảo quỹ này không chiếm quá 30–40% tổng danh mục. Đa dạng hóa giữa CCQ trái phiếu và cổ phiếu.`;
    ra='→ Duy trì tỷ trọng hiện tại, đảm bảo đa dạng hóa';
  }

  return [
    { name:'Kỹ thuật',  signal:ts, summary:tt, detail:td, action:ta },
    { name:'Giá trị',   signal:vs, summary:vt, detail:vd, action:va },
    { name:'Xu hướng',  signal:ms, summary:mt, detail:md, action:ma },
    { name:'DCA',       signal:ds, summary:dt, detail:dd, action:da },
    { name:'Rủi ro',    signal:rs, summary:rt, detail:rd, action:ra },
  ];
}

function _schoolCards(schools) {
  if (!schools?.length) return '';
  const names = ['Graham','Buffett','Momentum','Dalio','Markowitz'];
  let html = '<div class="section"><div class="section-hdr"><span>5 TRƯỜNG PHÁI ĐẦU TƯ</span></div>';
  schools.forEach((sc, i) => {
    const displayName = names[i] || sc.name || `Trường phái ${i+1}`;
    html += `<div class="school-card ${sigC(sc.signal)}" onclick="this.classList.toggle('open')">
      <div class="school-hdr">
        <div>
          <div class="school-title">${displayName}</div>
          <div class="school-subtitle">${sc.name||''}</div>
        </div>
        <span class="badge ${sigC(sc.signal)}" style="font-size:10px">${sigLabel(sc.signal)}</span>
        <span class="school-chevron">▼</span>
      </div>
      <div class="school-summary">${sc.summary||''}</div>
      <div class="school-detail">
        <div class="school-body">${sc.detail||''}</div>
        ${sc.action?`<div class="school-action ${sigC(sc.signal)}">${sc.action}</div>`:''}
      </div>
    </div>`;
  });
  return html + '</div>';
}

function renderResearch(d) {
  setModalTitle(d.code, d.name);
  const chg=d.chg_pct||0;
  const hasHistory = d.nav_history?.length > 1;
  let html=`<div class="section" style="padding-bottom:0">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <div>
        <div class="res-nav">${fmt(d.nav)} đ</div>
        <div class="pnl ${pnlC(chg)}" style="font-size:12px;margin-top:2px">${fmtP(chg)}</div>
      </div>
      <div class="badge ${sigC(d.signal)}" style="font-size:13px;padding:7px 12px">${sigLabel(d.signal)}</div>
    </div>
  </div>`;
  html += _resIndicators(d);
  html += _t2PredHtml(d);
  if (hasHistory) html+=`<div class="section"><div class="section-hdr"><span>LỊCH SỬ NAV</span></div><div style="height:180px;position:relative"><canvas id="modal-nav-chart"></canvas></div></div>`;
  if (d.conclusion) html+=`<div class="section"><div class="conclusion">${d.conclusion}</div></div>`;
  html += _schoolCards(d.schools?.length ? d.schools : _computeSchools(d));
  html += `<div style="padding:0 14px 8px"><button onclick="openAlertModal('${d.code}')" style="width:100%;padding:9px;background:var(--bg3);border:1px solid var(--bdr);color:var(--txt2);border-radius:8px;cursor:pointer;font-size:12px">🔔 Đặt cảnh báo giá</button></div>`;
  document.getElementById('modal-body').innerHTML = html;
  if (hasHistory) {
    const filtered = _filterByRange(d.nav_history, _chartRange);
    _redrawNavChart(filtered, 'modal-nav-chart');
  }
}

function _resIndicators(d) {
  const rsi=d.rsi??50, bb=d.bb??50, macd=d.macd||0, score=d.score||0;
  const rsiC=rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--hold)';
  const bbC=bb<20?'var(--buy)':bb>80?'var(--sell)':'var(--hold)';
  const scoreC=score>=3?'var(--buy)':score<=-3?'var(--sell)':'var(--txt)';
  const macdC=macd>0?'var(--buy)':macd<0?'var(--sell)':'var(--txt2)';
  const rsiLbl=rsi>70?'Mua quá mức':rsi<35?'Bán quá mức':'Trung tính';
  const bbLbl=bb>80?'Cận dải trên':bb<20?'Cận dải dưới':'Trung tính';
  const macdLbl=macd>0?'Xu hướng tăng':macd<0?'Xu hướng giảm':'Đi ngang';
  return `<div class="res-inds">
    <div class="res-ind">
      <div class="res-ind-lbl">RSI</div>
      <div class="meter-bar" style="margin-bottom:4px"><div class="meter-fill" style="width:${Math.min(rsi,100)}%;background:${rsiC}"></div></div>
      <div class="res-ind-val" style="color:${rsiC}">${rsi.toFixed?rsi.toFixed(1):rsi}</div>
      <div class="res-ind-desc">${rsiLbl}</div>
    </div>
    <div class="res-ind">
      <div class="res-ind-lbl">BB%</div>
      <div class="meter-bar" style="margin-bottom:4px"><div class="meter-fill" style="width:${Math.min(bb,100)}%;background:${bbC}"></div></div>
      <div class="res-ind-val" style="color:${bbC}">${bb.toFixed?bb.toFixed(1):bb}</div>
      <div class="res-ind-desc">${bbLbl}</div>
    </div>
    <div class="res-ind">
      <div class="res-ind-lbl">MACD</div>
      <div style="font-size:20px;line-height:1.2;color:${macdC}">${macd>0?'▲':macd<0?'▼':'▬'}</div>
      <div class="res-ind-val" style="color:${macdC};font-size:12px">${macd>0?'+':''}${typeof macd==='number'?macd.toFixed(2):macd}</div>
      <div class="res-ind-desc">${macdLbl}</div>
    </div>
    <div class="res-score">
      <div class="res-ind-lbl">SCORE</div>
      <div class="res-score-val" style="color:${scoreC}">${score>=0?'+':''}${score}</div>
      <div class="res-ind-desc">${score>=3?'Mua mạnh':score<=-3?'Bán mạnh':score>0?'Hơi tích cực':score<0?'Hơi tiêu cực':'Trung lập'}</div>
    </div>
  </div>`;
}

function renderResearchInline(d, el, canvasId) {
  canvasId = canvasId || 'home-inline-chart';
  const chg=d.chg_pct||0;
  const subEl = document.getElementById('chart-col-sub');
  if (subEl) subEl.textContent = d.name || d.code;
  const hasHistory = d.nav_history?.length > 1;
  let html=`<div class="res-header">
    <div>
      <div class="res-nav">${fmt(d.nav)} đ</div>
      <div class="pnl ${pnlC(chg)}" style="font-size:12px;margin-top:2px">${fmtP(chg)}</div>
    </div>
    <div class="badge ${sigC(d.signal)}" style="font-size:12px;padding:6px 10px">${sigLabel(d.signal)}</div>
  </div>`;
  html += _resIndicators(d);
  html += _t2PredHtml(d);
  if (hasHistory) html+=`<div style="padding:8px 14px 10px;height:190px;position:relative"><canvas id="${canvasId}"></canvas></div>`;
  if (d.conclusion) html+=`<div class="res-conclusion">${d.conclusion}</div>`;
  html += _schoolCards(d.schools?.length ? d.schools : _computeSchools(d));
  html += `<div style="padding:4px 14px 8px"><button onclick="openAlertModal('${d.code}')" style="width:100%;padding:8px;background:var(--bg3);border:1px solid var(--bdr);color:var(--txt2);border-radius:8px;cursor:pointer;font-size:12px">🔔 Đặt cảnh báo giá</button></div>`;
  el.innerHTML = html;
  if (hasHistory) {
    const filtered = _filterByRange(d.nav_history, _chartRange);
    _redrawNavChart(filtered, canvasId);
    _currentChartCanvas = canvasId;
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
  if (type==='buy')  { btn.textContent='XÁC NHẬN MUA'; btn.className='btn btn-buy'; amtLbl.textContent='Số tiền (đ)'; navLbl.textContent='NAV tại ngày mua (đ)'; }
  if (type==='sell') { btn.textContent='XÁC NHẬN BÁN'; btn.className='btn btn-sell'; amtLbl.textContent='Số tiền bán (đ)'; navLbl.textContent='NAV tại ngày bán (đ)'; }
  if (type==='div')  { btn.textContent='XÁC NHẬN LỢI TỨC'; btn.className='btn btn-primary'; amtLbl.textContent='Số tiền lợi tức (đ)'; navLbl.textContent='NAV tại ngày (đ)'; }
}
function setGoldType(type) {
  _goldType=type;
  document.querySelectorAll('#order-sub-gold .type-btn').forEach(b=>b.classList.remove('active'));
  document.querySelector(`#order-sub-gold .type-btn.${type}`).classList.add('active');
  const btn=document.getElementById('gold-trade-btn');
  document.getElementById('gold-price-label').textContent=type==='buy'?'Giá mua (đ/lượng)':'Giá bán (đ/lượng)';
  btn.textContent=type==='buy'?'XÁC NHẬN MUA':'XÁC NHẬN BÁN';
  btn.className=type==='buy'?'btn btn-buy':'btn btn-sell';
  _refreshGoldProductSelect(); // #7: filter to held products on sell
}

function _updateTradeFundOptions() {
  const sel=document.getElementById('trade-fund-select');
  const held=(_me?.portfolio?.items||[]).map(h=>h.code);
  const all=Object.keys(_marketData||_signals||{});
  const codes=[...new Set([...held,...all])].sort();
  sel.innerHTML='<option value="">-- Chọn quỹ --</option>'+codes.map(c=>`<option value="${c}">${c}</option>`).join('')+'<option value="__new__">+ Nhập mã mới...</option>';
  sel.onchange=()=>{
    if(sel.value==='__new__'){
      const code=(prompt('Nhập mã quỹ (vd: VHIZ, VESAF):','')?.trim().toUpperCase()||'');
      if(code){const opt=document.createElement('option');opt.value=code;opt.textContent=code;sel.insertBefore(opt,sel.lastElementChild);sel.value=code;}
      else sel.value='';
    }
    checkNavMismatch();
  };
}

let _goldUnitMode = 'luong'; // 'luong' | 'chi' | 'gram'

function setGoldUnitMode(mode, el) {
  _goldUnitMode = mode;
  ['luong','chi','gram'].forEach(u => {
    const b = document.getElementById('gold-unit-'+u);
    if (b) b.classList.toggle('active', u === mode);
  });
  const lbl = {luong:'lượng', chi:'chỉ', gram:'gram'}[mode];
  const priceLbl = document.getElementById('gold-price-label');
  if (priceLbl) priceLbl.textContent = (_goldType==='buy'?'Giá mua':'Giá bán') + ` (₫/${lbl})`;
}

function _onGoldProductChange(val) {
  const row = document.getElementById('gold-other-name-row');
  if (row) row.style.display = val === 'OTHER' ? '' : 'none';
  if (val !== 'OTHER') {
    const np = GOLD_PRODUCTS.find(p => p.value === val);
    if (np && !document.getElementById('gold-name').value) {
      document.getElementById('gold-name').value = np.label;
    }
  }
}

function _refreshGoldProductSelect() {
  const sel=document.getElementById('gold-product-select');
  let products=GOLD_PRODUCTS;
  // #7: on sell, only show held gold products
  if (_goldType==='sell' && _goldData?.portfolio?.by_product) {
    const held=Object.keys(_goldData.portfolio.by_product);
    if (held.length) {
      const filtered=GOLD_PRODUCTS.filter(p=>held.some(k=>k===p.value||k.startsWith(p.value+':')));
      const others=held.filter(k=>!GOLD_PRODUCTS.some(p=>p.value===k||k.startsWith(p.value+':')));
      products=[...filtered, ...others.map(k=>({value:k,label:k}))];
      if (!products.length) products=GOLD_PRODUCTS;
    }
  }
  sel.innerHTML=products.map(p=>`<option value="${p.value}">${p.label}</option>`).join('');
  sel.onchange = () => _onGoldProductChange(sel.value);
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
  if (!amount||amount<=0) { st.style.color='var(--sell)'; st.textContent='Số tiền không hợp lệ'; return; }
  st.style.color='var(--txt2)'; st.textContent='Dang luu...';
  try {
    await apiPost('/api/trade',{telegram_id:USER_ID, fund_code:fund, trade_type:_tradeType, amount, nav:nav||null, trade_date:date, note});
    st.style.color='var(--buy)'; st.textContent='&#x2713; Da luu giao dich!';
    _me=null; setTimeout(()=>loadMe(),800);
  } catch(e) { st.style.color='var(--sell)'; st.textContent='Loi: '+(e.body?.error||e.message); }
}

async function submitGoldTrade() {
  if (IS_DEV) { toast('DEV: gold '+_goldType+' '+document.getElementById('gold-product-select').value); return; }
  let product=document.getElementById('gold-product-select').value;
  const rawUnits=parseDecimal(document.getElementById('gold-units').value);
  // Convert to lượng for storage
  const unitFactor = _goldUnitMode==='chi' ? 0.1 : _goldUnitMode==='gram' ? (1/37.5) : 1;
  const units = rawUnits * unitFactor;
  const price=parseDecimal(document.getElementById('gold-price').value);
  const date=document.getElementById('gold-date').value||_todayISO();
  const otherName=document.getElementById('gold-other-name')?.value?.trim();
  const name=(product==='OTHER'&&otherName) ? otherName : (document.getElementById('gold-name').value||undefined);
  if (product==='OTHER' && otherName) product = 'OTHER:'+otherName;
  const st=document.getElementById('gold-trade-status');
  if (!units||units<=0) { st.style.color='var(--sell)'; st.textContent='Số lượng không hợp lệ'; return; }
  st.style.color='var(--txt2)'; st.textContent='Dang luu...';
  try {
    await apiPost('/api/gold/trade',{telegram_id:USER_ID, product, trade_type:_goldType, units, price:price||null, trade_date:date, name});
    st.style.color='var(--buy)'; st.textContent='&#x2713; Da luu!';
    _goldData=null; setTimeout(()=>loadMe(),800);
  } catch(e) { st.style.color='var(--sell)'; st.textContent='Loi: '+(e.body?.error||e.message); }
}

async function loadUnifiedHistory() {
  const el=document.getElementById('history-content'); el.innerHTML=spin();
  if (IS_DEV) { _tradeLog=MOCK_HISTORY.filter(t=>t.asset_type==='ccq'); _goldTrades=MOCK_HISTORY.filter(t=>t.asset_type==='gold'); renderUnifiedHistory(); return; }
  try {
    const d=await apiFetch('/api/history');
    const all=d.trades||d||[];
    _tradeLog=all.filter(t=>!t.asset_type||t.asset_type==='ccq');
    _goldTrades=all.filter(t=>t.asset_type==='gold');
    renderUnifiedHistory();
  } catch(e) { el.innerHTML=renderErr('Lỗi: '+e.message); }
}

function toggleHistFilter() {
  const fp=document.getElementById('hist-filter-panel');
  if (fp) fp.style.display = fp.style.display==='none' ? '' : 'none';
}

function applyHistFilter() { renderUnifiedHistory(); }

function _buildHistFilterCodes() {
  const codes=new Set(['GOLD']);
  _tradeLog.forEach(t=>{ if(t.fund_code) codes.add(t.fund_code); });
  const sel=document.getElementById('hist-filter-code'); if(!sel) return;
  const cur=sel.value;
  sel.innerHTML='<option value="">Tất cả</option><option value="GOLD">Vàng</option>';
  [...codes].filter(c=>c!=='GOLD').forEach(c=>{ const o=document.createElement('option'); o.value=c; o.textContent=c; sel.appendChild(o); });
  if(cur) sel.value=cur;
}

function renderUnifiedHistory() {
  const el=document.getElementById('history-content'); if(!el) return;
  const assetF=document.getElementById('hist-filter-asset')?.value||_histFilterAsset||'all';
  const codeF=document.getElementById('hist-filter-code')?.value||_histFilterCode||'';
  const fromF=document.getElementById('hist-filter-from')?.value||_histFilterFrom||'';
  const toF=document.getElementById('hist-filter-to')?.value||_histFilterTo||'';
  _buildHistFilterCodes();
  let all=[];
  if(assetF!=='gold') _tradeLog.forEach((t,i)=>all.push({...t,_asset:'ccq',_idx:i}));
  if(assetF!=='ccq')  _goldTrades.forEach((t,i)=>all.push({...t,_asset:'gold',_idx:i}));
  all=all.filter(t=>{
    if(codeF==='GOLD'&&t._asset!=='gold') return false;
    if(codeF&&codeF!=='GOLD'&&t.fund_code!==codeF) return false;
    if(fromF&&(t.trade_date||t.date)<fromF) return false;
    if(toF&&(t.trade_date||t.date)>toF) return false;
    return true;
  });
  all.sort((a,b)=>(b.trade_date||b.date||'').localeCompare(a.trade_date||a.date||''));
  if(!all.length) { el.innerHTML='<div style="text-align:center;color:var(--txt2);padding:24px">Không có giao dịch nào.</div>'; return; }
  let html='';
  for (const t of all) {
    const isGold=t._asset==='gold';
    const code=isGold?(t.gold_product||'VÀNG'):t.fund_code||'';
    const date=t.trade_date||t.date||'';
    const typeLabel=t.trade_type==='buy'?'MUA':t.trade_type==='sell'?'BÁN':t.trade_type==='dividend'?'LỢI TỨC':(t.trade_type||'').toUpperCase();
    const typeC=t.trade_type==='buy'?'var(--buy)':t.trade_type==='sell'?'var(--sell)':'var(--c0)';
    const amt=isGold?`${t.units||t.qty||0}L × ${fmt(t.price||t.price_per_luong)}`:`${fmt(t.amount)} đ`;
    const isVirtual=!!t._virtual;
    const mismatch=(!isGold&&!t.trade_type?.includes('dividend')&&t.nav_mismatch)?'<div style="font-size:10px;color:#facc15;margin-top:2px">⚠ Giá lệch NAV DB</div>':'';
    const navInfo=(!isGold&&t.nav&&t.trade_type!=='dividend')?`<span style="font-family:var(--mono);font-size:10px;color:var(--txt2)"> · NAV ${fmt(t.nav)}</span>`:'';
    const virtualBadge=isVirtual?`<span style="font-size:9px;color:var(--txt2);border:1px solid var(--bdr);border-radius:3px;padding:0 3px;margin-left:4px">Nhập từ Bot</span>`:'';
    const actions=isVirtual
      ? `<div class="tlog-actions"><span style="font-size:10px;color:var(--txt2)">—</span></div>`
      : isGold
        ? `<div class="tlog-actions"><button class="tlog-btn" onclick="openEditGoldModal(${t.id||t._idx})" title="Sửa">✏️</button><button class="tlog-btn tlog-del" onclick="confirmDeleteGoldTrade(${t.id||t._idx})" title="Xoá">🗑️</button></div>`
        : `<div class="tlog-actions"><button class="tlog-btn" onclick="openEditModal(${t.id||t._idx})" title="Sửa">✏️</button><button class="tlog-btn tlog-del" onclick="confirmDeleteTrade(${t.id||t._idx})" title="Xoá">🗑️</button></div>`;
    html+=`<div class="tlog-row">
      <div class="tlog-left">
        <div class="tlog-code">${code}${virtualBadge} <span style="font-size:11px;color:${typeC}">${typeLabel}</span></div>
        <div class="tlog-meta">${date} · ${amt}${navInfo}</div>
        ${t.note||t.name?`<div class="tlog-meta" style="color:var(--txt2)">${t.note||t.name}</div>`:''}
        ${mismatch}
      </div>
      ${actions}
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
      const t2NavDev=it.nav?Math.round(it.nav*(1+it.score*0.0012)):0;
      const t2BadgeDev=t2NavDev?`<span style="font-size:9px;font-family:var(--mono);color:var(--hold);border:1px solid var(--bdr);border-radius:3px;padding:1px 4px;margin-left:4px">T+2:${fmt(t2NavDev)}</span>`:'';
      html+=`<div class="dca-fund"><div class="dca-fund-row"><span class="fund-code">${it.code}${t2BadgeDev}</span><span style="font-family:var(--mono);font-size:12px">${fmt(amt)} đ</span><span class="badge ${sigC(it.signal)}" style="font-size:10px">${Math.round(w*100)}%</span></div><div class="dca-bar-wrap"><div class="dca-bar" style="width:${Math.round(w*100)}%;background:var(--c0)"></div></div><div class="dca-reason">~ ${units} CCQ tại NAV ${fmt(it.nav)} đ</div></div>`;
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
  if (!items.length) { el.innerHTML='<div style="text-align:center;color:var(--txt2);padding:16px">Không có đề xuất.</div>'; return; }
  let html='<div class="card">';
  for (const it of items) {
    const t2Nav=it.t2_nav||it.t2_prediction?.nav;
    const t2Badge=t2Nav?`<span style="font-size:9px;font-family:var(--mono);color:var(--hold);border:1px solid var(--bdr);border-radius:3px;padding:1px 4px;margin-left:4px">T+2:${fmt(t2Nav)}</span>`:'';
    html+=`<div class="dca-fund"><div class="dca-fund-row"><span class="fund-code">${it.code}${t2Badge}</span><span style="font-family:var(--mono);font-size:12px">${fmt(it.amount)} đ</span><span class="badge ${sigC(it.signal)}" style="font-size:10px">${it.pct||0}%</span></div><div class="dca-bar-wrap"><div class="dca-bar" style="width:${it.pct||0}%;background:var(--c0)"></div></div><div class="dca-reason">${it.reason||''}</div></div>`;
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
function setGoldSchool(school, el) {
  _goldSchool = school;
  document.querySelectorAll('.gp-school-btn').forEach(b=>b.classList.remove('gp-active'));
  el.classList.add('gp-active');
  runGoldPrediction();
}
async function autoFillMarketData() {
  const prices = _goldData?.prices || {};
  const sjcKey = Object.keys(prices).find(k=>k.includes('SJC_1L')||k.includes('VANGTODAYAPI'));
  if (sjcKey) {
    const sjcVal = prices[sjcKey];
    const usd = typeof sjcVal==='object' ? sjcVal.extra?.usd_vnd || sjcVal.usd_vnd : null;
    if (usd) { const el=document.getElementById('gp-usd'); if(el) el.value=Math.round(usd); }
  }
  const sjcPrice = _goldData?.signal?.sjc_sell || _goldData?.prices?.['VANGTODAYAPI:SJC_1L'] || 87000000;
  const xauEl = document.getElementById('gp-xau'); if(xauEl) xauEl.value = Math.round(sjcPrice / 37.5 / 1000 * 1.0862 * 1000);
  // Try Binance for BTC
  try {
    const r = await fetch('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT');
    const d = await r.json(); if(d.price) { const el=document.getElementById('gp-btc'); if(el) el.value=Number(d.price).toFixed(0); }
  } catch(e) {}
  toast('✓ Đã điền dữ liệu thị trường');
  runGoldPrediction();
}
function runGoldPrediction() {
  const el=document.getElementById('gold-dca-content'); if(!el) return;
  const divider=_goldUnit==='chi'?10:1;
  const sjcRaw = _goldData?.signal?.sjc_sell || _goldData?.prices?.['VANGTODAYAPI:SJC_1L'] || 87000000;
  const sjcPrice = sjcRaw / divider;
  const inf = parseDecimal(document.getElementById('gp-inflation')?.value) || 4;
  const xauUSD = parseDecimal(document.getElementById('gp-xau')?.value) || 3100;
  const usdVND = parseDecimal(document.getElementById('gp-usd')?.value) || 25000;
  const fedRate = parseDecimal(document.getElementById('gp-fed')?.value) || 4.5;
  const intlVND = xauUSD * usdVND / 37.5 / divider;
  const premiumPct = intlVND > 0 ? (sjcPrice - intlVND) / intlVND * 100 : 0;

  if (_goldSchool === 'short') {
    const entry1 = sjcPrice*0.99, entry2 = sjcPrice*0.975;
    const tp1 = sjcPrice*1.015, tp2 = sjcPrice*1.03;
    const sl = sjcPrice*0.96;
    el.innerHTML=`<div class="card">
      <div class="card-title">LƯỚT SÓNG NGẮN HẠN</div>
      <div class="sum-row"><span class="sum-label">Điểm vào 1</span><span class="sum-val pnl pos">${fmt(Math.round(entry1))} đ</span></div>
      <div class="sum-row"><span class="sum-label">Điểm vào 2 (đáy)</span><span class="sum-val pnl pos">${fmt(Math.round(entry2))} đ</span></div>
      <div class="sum-row"><span class="sum-label">Chốt lời 1 (+1.5%)</span><span class="sum-val pnl pos">↑ ${fmt(Math.round(tp1))} đ</span></div>
      <div class="sum-row"><span class="sum-label">Chốt lời 2 (+3%)</span><span class="sum-val pnl pos">↑ ${fmt(Math.round(tp2))} đ</span></div>
      <div class="sum-row"><span class="sum-label">Cắt lỗ (-4%)</span><span class="sum-val pnl neg">↓ ${fmt(Math.round(sl))} đ</span></div>
      <div style="font-size:11px;color:var(--txt2);margin-top:8px">Tỷ lệ RR ≈ 1:2. Phù hợp giao dịch 1–7 ngày.</div>
    </div>`;
  } else if (_goldSchool === 'dca') {
    const t1y = sjcPrice*(1+inf/100);
    const t3y = sjcPrice*Math.pow(1+inf/100,3);
    const t5y = sjcPrice*Math.pow(1+inf/100,5);
    const monthly = sjcPrice*0.08; // 8%/năm => ~mục tiêu chi/tháng
    el.innerHTML=`<div class="card">
      <div class="card-title">DCA DÀI HẠN</div>
      <div class="sum-row"><span class="sum-label">Mục tiêu 1 năm (+${inf}%)</span><span class="sum-val pnl pos">${fmt(Math.round(t1y))} đ</span></div>
      <div class="sum-row"><span class="sum-label">Mục tiêu 3 năm</span><span class="sum-val pnl pos">${fmt(Math.round(t3y))} đ</span></div>
      <div class="sum-row"><span class="sum-label">Mục tiêu 5 năm</span><span class="sum-val pnl pos">${fmt(Math.round(t5y))} đ</span></div>
      <div style="border-top:1px solid var(--bdr);margin:8px 0"></div>
      <div class="sum-row"><span class="sum-label">DCA tham khảo/tháng</span><span class="sum-val" style="color:var(--c0)">${fmt(Math.round(monthly))} đ/${_goldUnit==='chi'?'chỉ':'lượng'}</span></div>
      <div style="font-size:11px;color:var(--txt2);margin-top:8px">Lạm phát giả định ${inf}%/năm. Mua đều mỗi tháng.</div>
    </div>`;
  } else { // value / phân kỳ
    const fairVal = intlVND * 1.08; // SJC target ~8% premium vs intl
    const isCheap = premiumPct < 5;
    el.innerHTML=`<div class="card">
      <div class="card-title">PHÂN TÍCH GIÁ TRỊ</div>
      <div class="sum-row"><span class="sum-label">SJC hiện tại</span><span class="sum-val">${fmt(Math.round(sjcPrice))} đ</span></div>
      <div class="sum-row"><span class="sum-label">Giá quốc tế (XAU→VND)</span><span class="sum-val">${fmt(Math.round(intlVND))} đ</span></div>
      <div class="sum-row"><span class="sum-label">Phí bù SJC</span><span class="sum-val" style="color:${premiumPct>15?'var(--sell)':premiumPct<5?'var(--buy)':'var(--hold)'}">${premiumPct.toFixed(1)}%</span></div>
      <div class="sum-row"><span class="sum-label">Giá hợp lý (8% premium)</span><span class="sum-val" style="color:var(--c0)">${fmt(Math.round(fairVal))} đ</span></div>
      <div style="border-top:1px solid var(--bdr);margin:8px 0"></div>
      <div class="sum-row"><span class="sum-label">Fed Rate</span><span class="sum-val">${fedRate}%</span></div>
      <div class="sum-row"><span class="sum-label">Nhận định</span><span class="sum-val" style="color:${isCheap?'var(--buy)':'var(--sell)'}">${isCheap?'✓ Đang rẻ so với quốc tế':'⚠ Đang đắt — phí bù cao'}</span></div>
    </div>`+_goldSchoolCards(sjcPrice, xauUSD, usdVND, premiumPct, fedRate, inf);
  }
}
async function calcGoldDCA() {
  const el=document.getElementById('gold-dca-content'); el.innerHTML=spin();
  if (IS_DEV) { runGoldPrediction(); return; }
  try {
    const d=await apiFetch(`/api/gold/predict?type=${_goldPredType}&unit=${_goldUnit}`);
    if (d.predictions?.length) {
      el.innerHTML=`<div class="card">${d.predictions.map(p=>`<div class="sum-row"><span class="sum-label">${p.label}</span><span class="sum-val pnl ${pnlC(p.change_pct||0)}">${fmt(p.price)} đ/${_goldUnit}</span></div>`).join('')}</div>`;
    } else { runGoldPrediction(); }
  } catch(e) { runGoldPrediction(); }
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
    if (!isAdmin && tier!=='pro') document.getElementById('acc-upgrade-section').innerHTML=`<button class="btn btn-primary" onclick="showUpgradeModal({})">&#x2B50; NÂNG CẤP PRO NGAY</button>`;
    else document.getElementById('acc-upgrade-section').innerHTML=`<div style="color:var(--buy);font-size:13px;padding:4px 0">✓ ${isAdmin?'Tài khoản Admin — toàn quyền truy cập':'Pro đang hoạt động'}</div>`;
    return;
  }
  if (!_me) { try { _me=await apiFetch('/api/me'); renderTierBar(_me); } catch(e){} }
  const me=_me; if (!me) { el.innerHTML=renderErr('Lỗi tải user'); return; }
  const tier=me.tier||'free', isAdmin=me.is_admin;
  const exp=me.pro_expires_at?new Date(me.pro_expires_at).toLocaleDateString('vi-VN',{day:'2-digit',month:'2-digit',year:'numeric'}):'';
  el.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div><div style="font-size:16px;font-weight:700">${me.name||''}</div><div style="font-size:12px;color:var(--txt2);margin-top:2px">ID: ${me.telegram_id}</div>${exp?`<div style="font-size:11px;color:var(--txt2)">Pro đến ${exp}</div>`:''}</div>
    <span class="tier-chip ${isAdmin?'admin':tier}">${isAdmin?'ADMIN':tier.toUpperCase()}</span>
  </div>`;
  if (!isAdmin && tier!=='pro') document.getElementById('acc-upgrade-section').innerHTML=`<button class="btn btn-primary" onclick="showUpgradeModal({})">&#x2B50; NÂNG CẤP PRO NGAY</button>`;
  else document.getElementById('acc-upgrade-section').innerHTML=`<div style="color:var(--buy);font-size:13px;padding:4px 0">✓ ${isAdmin?'Tài khoản Admin — toàn quyền truy cập':`Pro đang hoạt động${exp?' (đến '+exp+')':''}`}</div>`;
}

async function loadReferralCode() {
  const box=document.getElementById('referral-code-box'), st=document.getElementById('referral-stats');
  if (IS_DEV) {
    box.innerHTML=`<div style="flex:1;font-family:var(--mono);font-size:15px;font-weight:700;color:var(--c0);background:var(--bg);border:1px solid var(--bdr);border-radius:8px;padding:8px 10px">HARVEY2024</div><button class="btn btn-primary" style="width:auto;margin:0;padding:0 14px;white-space:nowrap" onclick="navigator.clipboard?.writeText('HARVEY2024').then(()=>toast('Đã sao chép!'))">Sao chép</button>`;
    st.textContent='✓ Đã có 3 người dùng mã của bạn'; return;
  }
  if (!USER_ID) { box.innerHTML='<div style="font-size:12px;color:var(--txt2)">Cần user_id để lấy mã giới thiệu.</div>'; return; }
  try {
    const d=await apiFetch('/api/referral/mine');
    box.innerHTML=`<div style="flex:1;font-family:var(--mono);font-size:15px;font-weight:700;color:var(--c0);background:var(--bg);border:1px solid var(--bdr);border-radius:8px;padding:8px 10px;letter-spacing:.05em">${d.code}</div><button class="btn btn-primary" style="width:auto;margin:0;padding:0 14px;white-space:nowrap" onclick="navigator.clipboard?.writeText('${d.code}').then(()=>toast('Đã sao chép!'))">Sao chép</button>`;
    st.textContent=d.uses_count>0?`&#x2713; Đã có ${d.uses_count} người dùng mã của bạn`:'Chưa có ai dùng mã của bạn';
  } catch(e) { box.innerHTML=`<div style="font-size:12px;color:var(--sell)">Loi: ${e.message}</div>`; }
}

async function redeemPromoCode(ctx='modal') {
  const inputId=ctx==='acc'?'acc-promo-input':'promo-code-input';
  const statusId=ctx==='acc'?'acc-promo-status':'promo-code-status';
  const code=(document.getElementById(inputId).value||'').trim().toUpperCase();
  const st=document.getElementById(statusId);
  if (!code) { st.style.color='var(--sell)'; st.textContent='Vui long nhap ma'; return; }
  if (IS_DEV) { st.style.color='var(--buy)'; st.textContent='&#x2713; DEV: Ma '+code+' da duoc ap dung!'; return; }
  if (!USER_ID) { st.style.color='var(--sell)'; st.textContent='Cần user_id'; return; }
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
  document.getElementById('upgrade-reason').textContent=info?.limit?`Bạn đã đạt giới hạn ${info.limit} mã. Nâng cấp Pro để theo dõi không giới hạn.`:'Tính năng này chỉ dành cho tài khoản Pro.';
  document.getElementById('promo-code-status').textContent='';
  renderPlanCards();
  document.getElementById('upgrade-modal').classList.add('open');
}
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
  loadDiscountList(); loadAdminNavPending(); loadAdminSummary(); loadAdminAudit(); loadAdminUsers(); loadAdminPayments();
  _buildBookmarklet();
}

let _adminUserQ = '';
async function loadAdminUsers(q) {
  if (q !== undefined) _adminUserQ = q;
  const el = document.getElementById('admin-user-list');
  if (!el) return;
  el.innerHTML = '<div style="font-size:12px;color:var(--txt2)">Đang tải...</div>';
  if (IS_DEV) {
    el.innerHTML = renderAdminUsers([{telegram_id:1,name:'Harvey',tier:'pro',is_admin:1,trade_count:5,created_at:'2025-01-01'}]);
    return;
  }
  try {
    const url = `/api/admin/users${_adminUserQ ? '?q='+encodeURIComponent(_adminUserQ) : ''}`;
    const d = await apiFetch(url);
    el.innerHTML = renderAdminUsers(d.users || []);
  } catch(e) { el.innerHTML = renderErr('Lỗi: '+e.message); }
}
function renderAdminUsers(users) {
  if (!users.length) return '<div style="font-size:12px;color:var(--txt2);padding:12px">Không có user nào.</div>';
  const TIER = {pro:'<span style="color:var(--buy);font-family:var(--mono);font-size:10px">PRO</span>', free:'<span style="color:var(--txt2);font-family:var(--mono);font-size:10px">FREE</span>'};
  const rows = users.map(u=>`
    <tr class="au-row">
      <td class="au-id">${u.telegram_id}</td>
      <td class="au-name">${u.name||'—'}${u.is_admin?'<span class="au-badge-admin">ADMIN</span>':''}</td>
      <td>${TIER[u.tier]||u.tier}</td>
      <td style="text-align:right;font-family:var(--mono);font-size:11px">${u.trade_count||0}</td>
      <td style="font-size:10px;color:var(--txt2)">${(u.created_at||'').slice(0,10)}</td>
    </tr>`).join('');
  return `<table class="au-table"><thead><tr><th>ID</th><th>Tên</th><th>Gói</th><th style="text-align:right">GD</th><th>Tham gia</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function _buildBookmarklet() {
  const slot=document.getElementById('bm-slot'); if(!slot) return;
  // Scan localStorage + sessionStorage + cookies for JWT-like tokens
  const code='(function(){var t=null,k=null,stores=[localStorage,sessionStorage];for(var si=0;si<stores.length&&!t;si++){var st=stores[si];for(var i=0;i<st.length;i++){var _k=st.key(i),_v=st.getItem(_k);if(_v&&_v.length>80&&(/^eyJ/.test(_v)||/^eyJ/.test((function(){try{return JSON.parse(_v);}catch(e){return {}}}())?.access_token||""))){t=/^eyJ/.test(_v)?_v:JSON.parse(_v).access_token;k=_k;break;}}}if(!t){document.cookie.split(";").forEach(function(c){var p=c.trim().split("="),v=p.slice(1).join("=");if(v&&v.length>80&&/^eyJ/.test(v)){t=v;k=p[0].trim();}});}if(t){var tgt=t.length>500?t:t;if(window.opener){window.opener.postMessage({type:"tcbs_token",token:tgt,key:k},"*");window.close();}else{navigator.clipboard.writeText(tgt).then(function(){alert("Copied! Key: "+k+" ("+tgt.length+" chars)");}).catch(function(){alert("Token: "+tgt.slice(0,40)+"...\nKey: "+k);});}}else{var keys=[];for(var i=0;i<localStorage.length;i++)keys.push(localStorage.key(i));alert("Khong tim thay JWT trong localStorage/sessionStorage/cookies.\nCac key trong localStorage: "+keys.slice(0,10).join(", ")+"\nHay dang nhap TCInvest truoc roi thu lai.");}})();';
  const a=document.createElement('a'); a.href='javascript:'+code; a.textContent='[ Kéo bookmarklet này vào thanh công cụ ]';
  a.style.cssText='display:inline-block;padding:8px 12px;background:#001a33;border:1px solid var(--c0);border-radius:8px;color:var(--c0);font-family:var(--mono);font-size:11px;text-decoration:none;cursor:move';
  slot.innerHTML='<div style="margin-bottom:6px;font-size:11px;color:var(--txt2)">1. Kéo link này vào Bookmarks Bar &nbsp;/&nbsp; 2. Mở TCInvest, đăng nhập &nbsp;/&nbsp; 3. Nhấn vào bookmark &nbsp;/&nbsp; 4. Token tự điền vào ô bên trên</div>';
  slot.appendChild(a);
  if (!slot._msgListening) {
    slot._msgListening = true;
    window.addEventListener('message', e=>{
      if(e.data?.type==='tcbs_token'){
        document.getElementById('admin-token-input').value=e.data.token;
        toast('✓ Token đã tự động điền! Nhấn Lưu Token để áp dụng.',5000);
      }
    });
  }
}

function openTCInvest() {
  const w=window.open('https://tcinvest.tcbs.com.vn','tcbs_login','width=1024,height=700');
  if (!w) toast('Cho phep popup de mo TCInvest!');
}

async function adminUpdateToken() {
  const token=(document.getElementById('admin-token-input').value||'').trim();
  const st=document.getElementById('admin-token-status');
  if (!token) { st.style.color='var(--sell)'; st.textContent='Chưa nhập token'; return; }
  if (IS_DEV) { st.style.color='var(--buy)'; st.textContent='✓ DEV: Token đã lưu (giả lập)'; return; }
  st.style.color='var(--txt2)'; st.textContent='Đang lưu token...';
  try {
    const d=await apiPost('/api/admin/settoken',{admin_id:USER_ID, token});
    st.style.color='var(--buy)'; st.textContent='✓ '+(d.msg||'Token mới đã lưu vào hệ thống.');
  } catch(e) { st.style.color='var(--sell)'; st.textContent='⚠ '+(e.body?.error||e.message); }
}

async function adminFetchAll() {
  const st=document.getElementById('admin-fetch-status');
  st.style.color='var(--txt2)'; st.textContent='Đang fetch tất cả quỹ...';
  if (IS_DEV) { st.style.color='var(--buy)'; st.textContent='✓ DEV: Fetch started (giả lập)'; return; }
  try { const d=await apiPost('/api/admin/fetch-nav',{telegram_id:USER_ID}); st.style.color='var(--buy)'; st.textContent=`✓ Đang fetch trong nền. NAV sẽ cập nhật sau 1–2 phút.`; }
  catch(e) { st.style.color='var(--sell)'; st.textContent='⚠ '+(e.body?.error||e.message); }
}

async function adminFetchFmarket() {
  const st=document.getElementById('admin-fetch-status');
  st.style.color='var(--txt2)'; st.textContent='Đang fetch fmarket...';
  if (IS_DEV) { st.style.color='var(--buy)'; st.textContent='✓ DEV: Fmarket fetch started'; return; }
  try { const d=await apiPost('/api/admin/fetch-nav',{telegram_id:USER_ID,skip_tcbs:true}); st.style.color='var(--buy)'; st.textContent=`✓ Đang fetch fmarket trong nền. NAV cập nhật sau ~1 phút.`; }
  catch(e) { st.style.color='var(--sell)'; st.textContent='⚠ '+(e.body?.error||e.message); }
}

async function loadDiscountList() {
  const el=document.getElementById('admin-discount-list'); el.innerHTML='<div style="font-size:12px;color:var(--txt2)">Đang tải...</div>';
  const list=IS_DEV?MOCK_DISCOUNTS:(await apiFetch('/api/admin/discount/list?user_id='+(USER_ID||'')).then(d=>d.codes||[]).catch(()=>[]));
  if (!list.length) { el.innerHTML='<div style="font-size:12px;color:var(--txt2)">Chưa có mã giảm giá nào.</div>'; return; }
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
  if (!value||value<=0) { st.style.color='var(--sell)'; st.textContent='Giá trị không hợp lệ'; return; }
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
  const el=document.getElementById('admin-nav-confirm-list'); el.innerHTML='<div style="font-size:12px;color:var(--txt2)">Đang tải...</div>';
  if (IS_DEV) { el.innerHTML='<div style="font-size:12px;color:var(--txt2)">&#x2713; Không có NAV nào cần xác nhận (DEV)</div>'; return; }
  try {
    const d=await apiFetch('/api/admin/nav/pending'); const list=d.pending||[];
    if (!list.length) { el.innerHTML='<div style="font-size:12px;color:var(--txt2)">&#x2713; Không có NAV nào cần xác nhận</div>'; return; }
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
  const el=document.getElementById('admin-summary-box'); el.innerHTML='<div style="font-size:12px;color:var(--txt2)">Đang tải...</div>';
  if (IS_DEV) { el.innerHTML='<div style="font-size:12px">&#x1F465; <b>42</b> user (<span style="color:var(--buy)">8 pro</span> / 34 free)<br>&#x1F3AF; MAPE: arima 3.2% / xgb 2.8% / ensemble 2.1%<br>&#x26A0; 3 quỹ chưa có NAV hôm nay</div>'; return; }
  try {
    const d=await apiFetch('/api/admin/summary'); const u=d.users||{};
    let html=`<div style="margin-bottom:8px">&#x1F465; <b>${u.total??'-'}</b> user (<span style="color:var(--buy)">${u.pro??'-'} pro</span> / ${u.free??'-'} free)</div>`;
    html+=`<div style="color:#6b7280;margin-bottom:4px">&#x1F3AF; MAPE (7 ngay):</div>`;
    for (const m of d.model_mape||[]) html+=`<div style="padding:2px 0">${m.model_version}: <b style="color:${(m.mape_7d??99)>8?'var(--sell)':'var(--buy)'}">${m.mape_7d??'-'}%</b></div>`;
    html+=`<div style="margin-top:8px;color:#6b7280">&#x26A0; Chưa có NAV hôm nay: <b>${(d.funds_missing_today||[]).length}</b></div>`;
    el.innerHTML=html;
  } catch(e) { el.innerHTML=`<div style="color:var(--sell)">Loi: ${e.message}</div>`; }
}

async function loadAdminAudit() {
  const el=document.getElementById('admin-audit-list'); el.innerHTML='Đang tải...';
  if (IS_DEV) { el.innerHTML='<div style="color:var(--txt2)">DEV: Không có audit log.</div>'; return; }
  try {
    const d=await apiFetch('/api/admin/audit?limit=50'); const list=d.log||[];
    if (!list.length) { el.innerHTML='<div style="color:var(--txt2)">Chưa có log nào</div>'; return; }
    el.innerHTML=list.map(row=>{const t=row.created_at?new Date(row.created_at).toLocaleString('vi-VN',{hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit'}):'';return`<div style="border-bottom:1px solid var(--bdr);padding:5px 0"><span style="color:#6b7280">${t}</span> &middot; <span style="color:var(--c0);font-weight:700">${row.action}</span>${row.note?' &middot; <span style="color:var(--txt2)">'+row.note+'</span>':''}</div>`;}).join('');
  } catch(e) { el.innerHTML=`<div style="color:var(--sell)">Loi: ${e.message}</div>`; }
}

// ── SePay poller ─────────────────────────────────────────────────────────────
async function _pollSepay() {
  if (!_sepayRef) return;
  try {
    const d = await apiFetch('/api/payment/sepay/status?ref='+_sepayRef);
    if (d.status === 'paid') {
      clearInterval(_sepayTimer); _sepayTimer = null;
      document.getElementById('sepay-status').textContent = '✓ Thanh toán thành công!';
      document.getElementById('sepay-status').style.color = 'var(--buy)';
      _me = null; setTimeout(() => { closeUpgradeModalBtn(); loadUserProfile(); }, 2000);
    } else if (d.status === 'expired') {
      clearInterval(_sepayTimer); _sepayTimer = null;
      document.getElementById('sepay-status').textContent = 'QR đã hết hạn. Vui lòng tạo mới.';
      document.getElementById('sepay-status').style.color = 'var(--sell)';
    }
  } catch(e) { /* silently ignore poll errors */ }
}

// ── Admin: auto update NAV ────────────────────────────────────────────────────
async function autoUpdateNav() {
  const st = document.getElementById('hist-fetch-status'); if(st) st.textContent='Đang fetch...';
  if (IS_DEV) { if(st) st.textContent='✓ DEV: Fetch started'; return; }
  try {
    const d = await apiPost('/api/admin/fetch-nav', {telegram_id:USER_ID});
    if (d.ok) { if(st) st.textContent='✓ Đang fetch trong nền. Đợi 1–2 phút.'; }
    else if (d.error?.includes('token') || d.tcbs_error?.includes('token')) { showTcbsMiniModal(); }
    else { if(st) st.textContent='Lỗi: '+(d.error||'unknown'); }
    setTimeout(()=>{ if(_histPageCode) loadHistChart(_histPageCode); }, 5000);
  } catch(e) { if(st) st.textContent='Lỗi: '+(e.body?.error||e.message); }
}

// ── "Vàng khác" accordion ─────────────────────────────────────────────────────
function _toggleOtherGoldBreakdown(cardEl) {
  const panel = cardEl.querySelector('.other-gold-breakdown');
  const chevron = cardEl.querySelector('.other-gold-chevron');
  if (!panel) return;
  const opening = panel.style.display !== 'block';
  panel.style.display = opening ? 'block' : 'none';
  if (chevron) chevron.style.transform = opening ? 'rotate(180deg)' : 'rotate(0deg)';
}

// ── NAV Mismatch Warning ──────────────────────────────────────────────────────
async function checkNavMismatch() {
  const code = (document.getElementById('trade-fund-select')?.value || '').trim().toUpperCase();
  const price = parseDecimal(document.getElementById('trade-nav-input')?.value);
  const date  = document.getElementById('trade-date')?.value;
  const warn  = document.getElementById('trade-nav-mismatch');
  if (!warn) return;
  if (!code || !price || !date || IS_DEV) { warn.style.display='none'; return; }
  try {
    const d = await apiFetch(`/api/nav/${code}?date=${date}`);
    const dbNav = d?.nav;
    if (dbNav && Math.abs(dbNav - price) / dbNav * 100 > 0.5) {
      warn.textContent = `⚠ NAV DB ngày ${date}: ${fmt(Math.round(dbNav))} đ (lệch ${((Math.abs(dbNav-price)/dbNav)*100).toFixed(2)}%)`;
      warn.style.display = 'block';
    } else { warn.style.display = 'none'; }
  } catch(e) { warn.style.display = 'none'; }
}

// ── Edit CCQ Trade Modal ──────────────────────────────────────────────────────
function setEditType(type) {
  _editTradeType = type;
  ['buy','sell','dividend'].forEach(t => {
    const b = document.getElementById('edit-type-'+t);
    if (b) { b.classList.toggle('active', t===type); b.classList.toggle('buy', t==='buy'); b.classList.toggle('sell', t==='sell'); b.classList.toggle('div', t==='dividend'); }
  });
  const priceRow = document.getElementById('edit-price-row');
  const unitsLbl = document.getElementById('edit-units-label');
  if (priceRow) priceRow.style.display = type==='dividend' ? 'none' : '';
  if (unitsLbl) unitsLbl.textContent = type==='dividend' ? 'Tiền lợi tức (đ)' : 'Số CCQ';
  const amountPreview = document.getElementById('edit-amount-preview');
  if (amountPreview) calcEditAmount();
}
function calcEditAmount() {
  const units = parseDecimal(document.getElementById('edit-units')?.value) || 0;
  const price = parseDecimal(document.getElementById('edit-price')?.value) || 0;
  const el = document.getElementById('edit-amount-preview');
  if (el && units > 0 && price > 0 && _editTradeType !== 'dividend') {
    el.textContent = '≈ ' + fmt(Math.round(units * price)) + ' đ';
  } else if (el) { el.textContent = ''; }
}
function openEditModal(idx) {
  const trade = _tradeLog.find(t=>(t.id||t._idx)===idx) || _tradeLog[idx];
  if (!trade) { toast('Không tìm thấy giao dịch'); return; }
  _editTradeType = trade.trade_type === 'dividend' ? 'dividend' : trade.trade_type || 'buy';
  document.getElementById('edit-idx').value   = trade.id || idx;
  document.getElementById('edit-fund').value  = trade.fund_code || '';
  document.getElementById('edit-units').value = trade.units || '';
  document.getElementById('edit-price').value = trade.nav || trade.price_per_unit || '';
  document.getElementById('edit-date').value  = trade.trade_date || trade.date || _todayISO();
  document.getElementById('edit-note').value  = trade.note || '';
  setEditType(_editTradeType);
  document.getElementById('edit-modal').style.display = 'flex';
}
function closeEditModal() { document.getElementById('edit-modal').style.display = 'none'; }
async function saveEditTrade() {
  const idx   = parseInt(document.getElementById('edit-idx').value);
  const units = parseDecimal(document.getElementById('edit-units').value) || 0;
  const price = parseDecimal(document.getElementById('edit-price').value) || 0;
  const tdate = document.getElementById('edit-date').value;
  const note  = document.getElementById('edit-note').value;
  const isDiv = _editTradeType === 'dividend';
  const st    = document.getElementById('edit-trade-status');
  if (!isDiv && units <= 0) { st.style.color='var(--sell)'; st.textContent='Nhập số CCQ hợp lệ'; return; }
  if (!isDiv && price <= 0) { st.style.color='var(--sell)'; st.textContent='Nhập NAV hợp lệ'; return; }
  if (IS_DEV) { toast('✓ DEV: Đã cập nhật giao dịch'); closeEditModal(); return; }
  const amount = isDiv ? units : Math.round(units * price);
  st.style.color='var(--txt2)'; st.textContent='Đang lưu...';
  try {
    const d = await apiPost(`/api/trade/${idx}`, {type:_editTradeType, units, price_per_unit:price, amount, date:tdate, note, telegram_id:USER_ID});
    if (d.ok) { toast('✓ Đã cập nhật'); closeEditModal(); _me=null; loadUnifiedHistory(); loadMe(); }
    else { st.style.color='var(--sell)'; st.textContent='Lỗi: '+(d.error||'unknown'); }
  } catch(e) { st.style.color='var(--sell)'; st.textContent='Lỗi: '+(e.body?.error||e.message); }
}
async function confirmDeleteTrade(idx) {
  if (!confirm('Xoá giao dịch này?')) return;
  if (IS_DEV) { toast('✓ DEV: Đã xoá giao dịch'); _tradeLog=_tradeLog.filter((_,i)=>i!==idx); renderUnifiedHistory(); return; }
  try {
    const d = await apiDelete(`/api/trade/${idx}`, {telegram_id:USER_ID});
    if (d.ok) { toast('✓ Đã xoá'); _me=null; loadUnifiedHistory(); loadMe(); }
    else toast('Lỗi: '+(d.error||'unknown'));
  } catch(e) { toast('Lỗi: '+(e.body?.error||e.message)); }
}

// ── Edit Gold Trade Modal ─────────────────────────────────────────────────────
function setEditGoldType(type) {
  _editGoldType = type;
  ['buy','sell'].forEach(t => {
    const b = document.getElementById('edit-gold-type-'+t);
    if (b) { b.classList.toggle('active', t===type); b.classList.toggle('buy', t==='buy'); b.classList.toggle('sell', t==='sell'); }
  });
  const btn = document.getElementById('edit-gold-save-btn');
  if (btn) btn.textContent = type==='buy' ? 'Lưu lệnh MUA' : 'Lưu lệnh BÁN';
}
function calcEditGoldTotal() {
  const qty   = parseDecimal(document.getElementById('edit-gold-qty')?.value) || 0;
  const price = parseDecimal(document.getElementById('edit-gold-price')?.value) || 0;
  const el    = document.getElementById('edit-gold-total-preview');
  if (el) el.textContent = qty > 0 && price > 0 ? '≈ ' + fmt(Math.round(qty*price)) + ' đ' : '';
}
function openEditGoldModal(idx) {
  const trade = _goldTrades.find(t=>(t.id||t._idx)===idx) || _goldTrades[idx];
  if (!trade) { toast('Không tìm thấy giao dịch'); return; }
  _editGoldType = trade.trade_type || 'buy';
  document.getElementById('edit-gold-idx').value   = trade.id || idx;
  document.getElementById('edit-gold-product').value = trade.gold_product||trade.product||'';
  document.getElementById('edit-gold-qty').value   = trade.units||trade.qty||'';
  document.getElementById('edit-gold-price').value = trade.price||trade.price_per_luong||'';
  document.getElementById('edit-gold-date').value  = trade.trade_date||trade.date||_todayISO();
  document.getElementById('edit-gold-note').value  = trade.name||trade.note||'';
  setEditGoldType(_editGoldType);
  document.getElementById('edit-gold-modal').style.display = 'flex';
}
function closeEditGoldModal() { document.getElementById('edit-gold-modal').style.display = 'none'; }
async function saveEditGoldTrade() {
  const idx   = parseInt(document.getElementById('edit-gold-idx').value);
  const qty   = parseDecimal(document.getElementById('edit-gold-qty').value) || 0;
  const price = parseDecimal(document.getElementById('edit-gold-price').value) || 0;
  const dt    = document.getElementById('edit-gold-date').value;
  const note  = document.getElementById('edit-gold-note').value;
  const st    = document.getElementById('edit-gold-status');
  if (!qty||qty<=0||!price||price<=0||!dt) { st.style.color='var(--sell)'; st.textContent='Kiểm tra lại thông tin'; return; }
  if (IS_DEV) { toast('✓ DEV: Đã cập nhật giao dịch vàng'); closeEditGoldModal(); return; }
  const total = Math.round(qty * price);
  st.style.color='var(--txt2)'; st.textContent='Đang lưu...';
  try {
    const d = await apiPost(`/api/gold/trade/${idx}`, {type:_editGoldType, unit:'luong', qty, price_per_luong:price, total_vnd:total, date:dt, name:note, telegram_id:USER_ID});
    if (d.ok) { toast('✓ Đã cập nhật'); closeEditGoldModal(); _goldData=null; loadUnifiedHistory(); loadMe(); }
    else { st.style.color='var(--sell)'; st.textContent='Lỗi: '+(d.error||'unknown'); }
  } catch(e) { st.style.color='var(--sell)'; st.textContent='Lỗi: '+(e.body?.error||e.message); }
}
async function confirmDeleteGoldTrade(idx) {
  if (!confirm('Xoá giao dịch vàng này?')) return;
  if (IS_DEV) { toast('✓ DEV: Đã xoá giao dịch vàng'); _goldTrades=_goldTrades.filter((_,i)=>i!==idx); renderUnifiedHistory(); return; }
  try {
    const d = await apiDelete(`/api/gold/trade/${idx}`, {telegram_id:USER_ID});
    if (d.ok) { toast('✓ Đã xoá'); _goldData=null; loadUnifiedHistory(); loadMe(); }
    else toast('Lỗi: '+(d.error||'unknown'));
  } catch(e) { toast('Lỗi: '+(e.body?.error||e.message)); }
}

// ── Watch Funds Modal ─────────────────────────────────────────────────────────
function openWatchModal() {
  _watchToggleSet = new Set([..._watchedSet]);
  _allFundsList = _marketData || _signals || MOCK_SIGNALS;
  _renderWatchList(Object.keys(_allFundsList));
  document.getElementById('watch-modal').style.display = 'flex';
}
function closeWatchModal() { document.getElementById('watch-modal').style.display = 'none'; }
function filterWatchList() {
  const q = (document.getElementById('watch-search')?.value || '').toUpperCase();
  const keys = Object.keys(_allFundsList).filter(code => !q || code.includes(q));
  _renderWatchList(keys);
}
function _renderWatchList(codes) {
  const el = document.getElementById('watch-list'); if (!el) return;
  if (!codes.length) { el.innerHTML='<div style="color:var(--txt2);padding:12px;text-align:center">Không tìm thấy quỹ</div>'; return; }
  el.innerHTML = codes.map(code => {
    const checked = _watchToggleSet.has(code);
    const s = _allFundsList[code];
    const nav = s?.nav ? ` — ${fmt(s.nav)} đ` : '';
    return `<div class="watch-item" onclick="_toggleWatch('${code}',this)">
      <div class="watch-check ${checked?'on':''}" id="wc-${code}">&#x2713;</div>
      <div><div style="font-family:var(--mono);font-size:13px;font-weight:600">${code}</div><div style="font-size:11px;color:var(--txt2)">${nav}</div></div>
    </div>`;
  }).join('');
}
function _toggleWatch(code) {
  if (_watchToggleSet.has(code)) _watchToggleSet.delete(code);
  else _watchToggleSet.add(code);
  const el = document.getElementById('wc-'+code);
  if (el) el.className = 'watch-check ' + (_watchToggleSet.has(code) ? 'on' : '');
}
async function saveWatchedFunds() {
  const funds = [..._watchToggleSet];
  if (IS_DEV) { _watchedSet=_watchToggleSet; toast('✓ DEV: Lưu '+funds.length+' quỹ theo dõi'); closeWatchModal(); loadSignals(); return; }
  const st = document.getElementById('watch-status'); if(st) st.textContent='Đang lưu...';
  try {
    const d = await apiPost('/api/me/watched_funds', {telegram_id:USER_ID, watched_funds:funds});
    if (d.ok) { _watchedSet=_watchToggleSet; toast('✓ Đã lưu '+funds.length+' quỹ theo dõi'); closeWatchModal(); _signals=null; loadSignals(); }
    else { if(st) st.textContent='Lỗi: '+(d.error||'unknown'); if(d.error==='pro_required') { closeWatchModal(); showUpgradeModal(d); } }
  } catch(e) { if(st) st.textContent='Lỗi: '+(e.body?.error||e.message); }
}

// ── History Page ──────────────────────────────────────────────────────────────
async function loadHistoryPage() {
  if (_histPageCode) { loadHistChart(_histPageCode); return; }
  _renderHistFundList();
  const _sigs0 = _signals || _marketData || MOCK_SIGNALS || {};
  const _held0 = new Set(_me?.portfolio?.items?.map(i=>i.code)||[]);
  const _watched0 = new Set(_me?.watched_funds || []);
  const _all0 = Object.keys(_sigs0);
  const _firstCode = _all0.find(c=>_held0.has(c)||_watched0.has(c)) || _all0[0];
  if (_firstCode) loadHistChart(_firstCode);
}
function _renderHistFundList() {
  const el = document.getElementById('hist-fund-list'); if (!el) return;
  const sigs = _signals || _marketData || MOCK_SIGNALS || {};
  const held = new Set(_me?.portfolio?.items?.map(i=>i.code)||[]);
  const watched = new Set(_me?.watched_funds || []);
  // Show ALL funds — held/watched pinned at top, rest sorted alphabetically
  const allCodes = Object.keys(sigs);
  const priority = allCodes.filter(c => held.has(c) || watched.has(c));
  const rest = allCodes.filter(c => !held.has(c) && !watched.has(c)).sort();
  const funds = [...priority, ...rest];
  const countEl = document.getElementById('hist-fund-count');
  if (countEl) countEl.textContent = funds.length + ' quỹ';
  if (!allCodes.length) { el.innerHTML='<div style="color:var(--txt2);font-size:12px;padding:16px;text-align:center">Đang tải dữ liệu...</div>'; return; }
  // WEB-011: Gold row pinned at top of fund list
  const gs = _goldData?.signals;
  const goldActiveClass = _histPageCode==='GOLD_SJC' ? 'active' : '';
  const goldSigLabel = gs?.signal || '';
  const goldSigClass = goldSigLabel.includes('MUA')?'buy':goldSigLabel.includes('THẬN')||goldSigLabel.includes('BÁN')?'sell':'hold';
  const goldChgHtml = gs?.chg_pct!=null ? `<span class="pnl ${pnlC(gs.chg_pct)}" style="font-size:10px">${gs.chg_pct>=0?'+':''}${gs.chg_pct.toFixed(2)}%</span>` : '';
  const goldPriceHtml = gs?.price ? `<span style="font-family:var(--mono);font-size:10px;color:var(--txt2)">${(gs.price/1e6).toFixed(0)}M</span>` : '';
  const goldRow = `<div class="hist-fund-row ${goldActiveClass}" onclick="_selectHistFund('GOLD_SJC',this)" style="border-left:2px solid #fbbf24;padding-left:6px">
    <div style="display:flex;align-items:center;gap:3px;min-width:0">
      <div class="hist-fund-code" style="color:#fbbf24">🥇 VÀNG</div>
    </div>
    <div class="hist-fund-nav">${goldPriceHtml} ${goldChgHtml}</div>
    ${goldSigLabel?`<span class="badge ${goldSigClass}" style="font-size:9px;padding:1px 5px">${goldSigLabel}</span>`:'<span style="font-size:9px;color:var(--txt3)">—</span>'}
  </div>`;
  el.innerHTML = goldRow + funds.map(code => {
    const s = sigs[code] || {};
    const nav = s.nav ? fmt(s.nav)+' đ' : '—';
    const chg = s.chg_pct ?? s.change_pct ?? s.change ?? null;
    const chgHtml = chg!=null ? `<span class="pnl ${pnlC(chg)}" style="font-size:11px">${chg>=0?'+':''}${chg.toFixed(2)}%</span>` : '';
    const sig = s.signal || '';
    const sigClass = sig.includes('MUA')?'buy':sig.includes('BÁN')||sig.includes('BAN')?'sell':'hold';
    const sigHtml = sig ? `<span class="badge ${sigClass}" style="font-size:9px;padding:1px 5px">${sig}</span>` : '';
    const isWatched = watched.has(code);
    const starBtn = `<span onclick="event.stopPropagation();_toggleWatchFund('${code}')" title="${isWatched?'Bỏ theo dõi':'Thêm theo dõi'}" style="cursor:pointer;font-size:10px;color:${isWatched?'var(--c0)':'var(--txt3)'};padding:0 1px;line-height:1;flex-shrink:0">${isWatched?'★':'☆'}</span>`;
    const heldBadge = held.has(code) ? `<span class="hist-fund-held">NẮM</span>` : '';
    return `<div class="hist-fund-row ${_histPageCode===code?'active':''}" onclick="_selectHistFund('${code}',this)">
      <div style="display:flex;align-items:center;gap:3px;min-width:0">
        <div class="hist-fund-code">${code}</div>
        ${starBtn}${heldBadge}
      </div>
      <div class="hist-fund-nav">${nav} ${chgHtml}</div>
      ${sigHtml}
    </div>`;
  }).join('');
}
async function _quickWatch(code, e) {
  if (e) e.stopPropagation();
  await _toggleWatchFund(code);
  const star = document.querySelector(`[data-code="${code}"] .watch-star`);
  if (star) {
    const w = (_me?.watched_funds||[]).includes(code);
    star.textContent = w ? '★' : '☆';
    star.style.color = w ? 'var(--c0)' : 'var(--txt3)';
    star.title = w ? 'Bỏ theo dõi' : 'Thêm theo dõi';
  }
}
async function _toggleWatchFund(code) {
  const watched = new Set(_me?.watched_funds || []);
  const wasWatched = watched.has(code);
  if (wasWatched) watched.delete(code); else watched.add(code);
  const list = [...watched];
  if (_me) _me.watched_funds = list;
  _renderHistFundList();
  if (IS_DEV) { toast(wasWatched ? `Đã bỏ ${code} khỏi theo dõi (DEV)` : `Đã thêm ${code} vào theo dõi (DEV)`); return; }
  try {
    await apiPost('/api/me/watched_funds', {telegram_id: USER_ID, watched_funds: list});
    toast(wasWatched ? `Đã bỏ ${code} khỏi danh sách theo dõi` : `Đã thêm ${code} vào danh sách theo dõi`);
  } catch(e) { toast('Lỗi: '+(e.body?.error||e.message)); }
}
function _selectHistFund(code, el) {
  document.querySelectorAll('.hist-fund-row').forEach(r=>r.classList.remove('active'));
  el?.classList.add('active');
  const lbl = document.getElementById('hist-fund-label');
  if (lbl) lbl.textContent = code === 'GOLD_SJC' ? '🥇 VÀNG SJC' : code;
  if (_histView === 'cmp') { _histPageCode = code; loadComparisonView(); return; }
  if (code === 'GOLD_SJC') loadGoldAnalysis();
  else loadHistChart(code);
}
async function loadHistChart(code) {
  if (code === 'GOLD_SJC') { loadGoldAnalysis(); return; }
  _histPageCode = code;
  const lbl = document.getElementById('hist-fund-label');
  if (lbl) lbl.textContent = code;
  // Update active state in fund list
  document.querySelectorAll('.hist-fund-row').forEach(r => {
    r.classList.toggle('active', r.querySelector('.hist-fund-code')?.textContent === code);
  });
  const el = document.getElementById('hist-chart-area'); if (!el) return;
  el.innerHTML = spin();
  if (IS_DEV) {
    const s = (MOCK_SIGNALS||{})[code]||{nav:15000};
    const pts = _mockNavHistory(s.nav||15000, 365);
    _histPageData = pts; renderHistChart(pts, code);
    _renderHistAnalysis(code);
    return;
  }
  try {
    const d = await apiFetch(`/api/nav_history/${code}?limit=365`);
    _histPageData = d.history || d;
    renderHistChart(_histPageData, code);
    _renderHistAnalysis(code);
  } catch(e) { el.innerHTML=renderErr('Lỗi: '+e.message); }
}
function renderHistChart(pts, code) {
  const el = document.getElementById('hist-chart-area'); if (!el) return;
  // Apply time range filter
  if (_histRange && _histRange !== 'ALL') {
    const days = {_1M:30,'1M':30,'3M':90,'6M':180,'1Y':365}[_histRange]||30;
    const cutoff = new Date(); cutoff.setDate(cutoff.getDate()-days);
    const cut = cutoff.toISOString().slice(0,10);
    pts = pts.filter(p=>p.date>=cut);
  }
  if (!pts?.length) { el.innerHTML='<div style="color:var(--txt2);padding:24px;text-align:center">Chưa có lịch sử NAV</div>'; return; }
  const fromV = document.getElementById('hist-from')?.value;
  const toV   = document.getElementById('hist-to')?.value;
  const filtered = pts.filter(p => (!fromV||p.date>=fromV) && (!toV||p.date<=toV));
  const labels = filtered.map(p=>p.date);
  const vals   = filtered.map(p=>p.nav||p[1]||0);
  const first  = vals[0]||0, last=vals[vals.length-1]||0;
  const chg    = first>0 ? ((last-first)/first*100) : 0;
  const high   = Math.max(...vals), low=Math.min(...vals);
  const hdrEl = document.getElementById('hist-nav-header');
  if (hdrEl) {
    const latestDate = filtered[filtered.length-1]?.date || '';
    hdrEl.innerHTML = `<div style="display:flex;align-items:baseline;gap:10px">
      <span style="font-family:var(--mono);font-size:10px;color:var(--txt2);letter-spacing:.08em">${code}</span>
      <span class="hist-nav-hval">${fmt(last)} đ</span>
      <span class="hist-nav-hchg pnl ${pnlC(chg)}">${chg>=0?'+':''}${chg.toFixed(2)}%</span>
    </div>
    <div style="font-size:10px;color:var(--txt2);margin-top:2px">${latestDate}</div>`;
  }
  document.getElementById('hist-stats')?.innerHTML ? null : null;
  const statsEl = document.getElementById('hist-stats');
  if (statsEl) statsEl.innerHTML=`
    <div class="sum-row"><span class="sum-label">NAV mới nhất</span><span class="sum-val">${fmt(last)} đ</span></div>
    <div class="sum-row"><span class="sum-label">Thay đổi</span><span class="sum-val pnl ${pnlC(chg)}">${fmtP(chg)}</span></div>
    <div class="sum-row"><span class="sum-label">Cao nhất</span><span class="sum-val pnl pos">${fmt(high)} đ</span></div>
    <div class="sum-row"><span class="sum-label">Thấp nhất</span><span class="sum-val pnl neg">${fmt(low)} đ</span></div>
    <div class="sum-row"><span class="sum-label">Điểm dữ liệu</span><span class="sum-val">${filtered.length}</span></div>`;
  el.innerHTML = '<canvas id="hist-page-canvas"></canvas>';
  const ctx = document.getElementById('hist-page-canvas');
  if (!ctx) return;
  if (_histPageChart) { try { _histPageChart.destroy(); } catch(e){} _histPageChart=null; }
  const gc = ctx.getContext('2d');
  const grad = gc.createLinearGradient(0,0,0,ctx.offsetHeight||200);
  grad.addColorStop(0,'rgba(0,229,255,.3)'); grad.addColorStop(1,'rgba(0,229,255,0)');
  _histPageChart = new Chart(ctx, {
    type:'line',
    data:{labels, datasets:[{data:vals, borderColor:'#00e5ff', borderWidth:1.5, fill:true, backgroundColor:grad, tension:0.35, pointRadius:0, pointHoverRadius:4}]},
    options:{responsive:true, maintainAspectRatio:false, animation:false,
      plugins:{legend:{display:false}, tooltip:{mode:'index',intersect:false, callbacks:{label:(ctx)=>`NAV: ${fmt(Math.round(ctx.parsed.y))} đ`}}, crosshair:_crosshairPlugin},
      scales:{x:{ticks:{maxTicksLimit:8,color:'#6b7280',font:{size:10}},grid:{color:'rgba(255,255,255,.04)'}}, y:{ticks:{color:'#6b7280',font:{size:10}, callback:v=>fmt(Math.round(v))},grid:{color:'rgba(255,255,255,.04)'}}}}
  });
}
function applyHistDateRange() {
  if (_histPageData) renderHistChart(_histPageData, _histPageCode);
}

async function submitSingleNav() {
  const code = _histPageCode;
  const dateEl = document.getElementById('bulk-nav-date-single');
  const valEl  = document.getElementById('bulk-nav-value-single');
  const statusEl = document.getElementById('bulk-nav-status');
  if (!code) { if (statusEl) statusEl.textContent = 'Chọn quỹ trước'; return; }
  const date = dateEl?.value;
  const nav  = parseFloat((valEl?.value||'').replace(/[^0-9.]/g,''));
  if (!date || !nav || isNaN(nav)) { if (statusEl) statusEl.textContent = 'Nhập đủ ngày và NAV'; return; }
  if (statusEl) statusEl.textContent = 'Đang lưu…';
  try {
    const res = await apiPost('/api/nav/manual', { user_id: USER_ID, fund_code: code, date, nav });
    if (res.ok || res.success) {
      if (statusEl) { statusEl.textContent = '✓ Đã lưu'; statusEl.style.color='var(--buy)'; }
      if (valEl) valEl.value = '';
      loadHistChart(code);
      setTimeout(() => { if (statusEl) { statusEl.textContent=''; statusEl.style.color=''; } }, 3000);
    } else {
      if (statusEl) { statusEl.textContent = res.error || 'Lỗi'; statusEl.style.color='var(--sell)'; }
    }
  } catch(e) {
    if (statusEl) { statusEl.textContent = e.message; statusEl.style.color='var(--sell)'; }
  }
}

// ── MoMo Payment ──────────────────────────────────────────────────────────────
async function startUpgradeMomo() {
  if (IS_DEV) { toast('DEV: MoMo redirect cho plan '+_selectedPlan); return; }
  const btn=document.getElementById('momo-btn'); if(btn){btn.disabled=true;btn.textContent='Đang tạo link...';}
  try {
    const d=await apiPost('/api/payment/momo/create',{user_id:USER_ID,tier:_selectedPlan,plan:_selectedPlan});
    if(d.pay_url) window.open(d.pay_url,'_blank');
    else toast('Lỗi MoMo: '+(d.error||'unknown'));
  } catch(e) { toast('Lỗi: '+e.message); }
  if(btn){btn.disabled=false;btn.textContent='💜 Thanh toán MoMo';}
}

// ── SePay discount code ──────────────────────────────────────────────────────
async function startUpgradeSepay() {
  if (IS_DEV) { toast('DEV: SePay QR for '+_selectedPlan); return; }
  const btn=document.getElementById('sepay-create-btn'); if(btn){btn.disabled=true;btn.textContent='Đang tạo QR...';}
  clearInterval(_sepayTimer); _sepayTimer=null;
  const discountCode=(document.getElementById('sepay-discount-code')?.value||'').trim();
  const body={plan:_selectedPlan, telegram_id:USER_ID};
  if(discountCode) body.discount_code=discountCode;
  try {
    const d=await apiPost('/api/payment/sepay/create',body);
    _sepayRef=d.ref;
    if(d.discount_applied&&d.final_price) {
      const priceEl=document.getElementById('sepay-final-price');
      if(priceEl) { priceEl.textContent=`Giá sau giảm: ${fmt(d.final_price)} đ (−${d.discount_pct||0}%)`; priceEl.style.display=''; }
    }
    document.getElementById('sepay-qr-img').src=d.qr_url||d.qr||'';
    document.getElementById('sepay-ref').textContent='Mã GD: '+d.ref;
    document.getElementById('sepay-status').textContent='Đang chờ thanh toán...';
    document.getElementById('sepay-status').style.color='';
    document.getElementById('sepay-qr-area').style.display='';
    _sepayTimer=setInterval(_pollSepay,4000);
  } catch(e) { toast('Lỗi tạo QR: '+(e.body?.error||e.message)); }
  if(btn){btn.disabled=false;btn.textContent='🏦 TẠO QR CHUYỂN KHOẢN';}
}

// ── TCBS Mini Modal ───────────────────────────────────────────────────────────
function showTcbsMiniModal() {
  const m=document.getElementById('tcbs-mini-modal'); if(m) m.style.display='flex';
  const st=document.getElementById('tcbs-mini-status'); if(st) st.textContent='';
}
function closeTcbsMiniModal() { const m=document.getElementById('tcbs-mini-modal'); if(m) m.style.display='none'; }
async function tcbsMiniSubmit() {
  const token=(document.getElementById('tcbs-mini-token')?.value||'').trim();
  const st=document.getElementById('tcbs-mini-status'); if(!token){if(st)st.textContent='Chưa nhập token';return;}
  if(st)st.textContent='Đang lưu token...';
  try {
    await apiPost('/api/admin/settoken',{admin_id:USER_ID,token});
    if(st)st.textContent='Token OK. Đang fetch...';
    const d=await apiPost('/api/admin/fetch-nav',{telegram_id:USER_ID});
    if(st)st.textContent=d.ok?'✓ Đang fetch trong nền. Đóng sau 3s.':'Lỗi: '+(d.error||'?');
    setTimeout(()=>{closeTcbsMiniModal();if(_histPageCode)loadHistChart(_histPageCode);},3000);
  } catch(e) { if(st)st.textContent='Lỗi: '+(e.body?.error||e.message); }
}
async function tcbsMiniSkip() {
  const st=document.getElementById('tcbs-mini-status'); if(st)st.textContent='Đang fetch fmarket...';
  try {
    const d=await apiPost('/api/admin/fetch-nav',{telegram_id:USER_ID,skip_tcbs:true});
    if(st)st.textContent=d.ok?'✓ Fetch fmarket started.':'Lỗi: '+(d.error||'?');
    setTimeout(()=>{closeTcbsMiniModal();},2000);
  } catch(e) { if(st)st.textContent='Lỗi: '+(e.body?.error||e.message); }
}

// ── NAV Import Modal ──────────────────────────────────────────────────────────
function openNavImport() { const m=document.getElementById('nav-import-modal'); if(m){m.style.display='flex';navImportAddRow();} }
function closeNavImport() { const m=document.getElementById('nav-import-modal'); if(m)m.style.display='none'; }
function navImportAddRow() {
  const cont=document.getElementById('nav-import-rows'); if(!cont) return;
  const row=document.createElement('div'); row.className='nav-import-row';
  row.innerHTML=`<input type="date" value="${_todayISO()}" style="flex:1;max-width:130px"><input type="text" placeholder="NAV (đ)" style="flex:1;min-width:80px"><button onclick="this.parentElement.remove()" style="background:none;border:none;color:var(--sell);font-size:16px;cursor:pointer;padding:0 4px">×</button>`;
  cont.appendChild(row);
}
async function navImportSubmit() {
  const code=(document.getElementById('nav-import-code')?.value||'').trim().toUpperCase();
  const st=document.getElementById('nav-import-status');
  if(!code){if(st){st.style.color='var(--sell)';st.textContent='Nhập mã quỹ';}return;}
  const rows=[...document.querySelectorAll('#nav-import-rows .nav-import-row')];
  const navList=rows.map(r=>{const[di,ni]=r.querySelectorAll('input');const nav=parseDecimal(ni?.value);return(di?.value&&nav>0)?{date:di.value,nav}:null;}).filter(Boolean);
  if(!navList.length){if(st){st.style.color='var(--sell)';st.textContent='Không có dữ liệu hợp lệ';}return;}
  if(IS_DEV){if(st){st.style.color='var(--buy)';st.textContent=`✓ DEV: Import ${navList.length} điểm NAV cho ${code}`;}return;}
  if(st){st.style.color='var(--txt2)';st.textContent='Đang import...';}
  const isAdmin=_me?.is_admin;
  const endpoint=isAdmin?'/api/admin/import-nav':'/api/nav/draft';
  try {
    const d=await apiPost(endpoint,{tg_id:String(USER_ID),funds:{[code]:navList}});
    if(st){st.style.color='var(--buy)';st.textContent=`✓ Đã import ${navList.length} điểm NAV cho ${code}.${d.skipped?.[code]?' ('+d.skipped[code]+' bỏ qua)':''}`;}
    if(_histPageCode===code) loadHistChart(code);
  } catch(e){if(st){st.style.color='var(--sell)';st.textContent='Lỗi: '+(e.body?.error||e.message);}}
}

// ── Header 5-tap Easter Egg ────────────────────────────────────────────────────
function onHdrTap() {
  _tapCount++;
  clearTimeout(_tapTimer);
  _tapTimer = setTimeout(()=>{_tapCount=0;},800);
  if(_tapCount>=5) { _tapCount=0; document.getElementById('token-modal')?.style.setProperty('display','block'); }
}

// ── setPaymentMethod (replaces stub) ─────────────────────────────────────────
function setPaymentMethod(method) {
  _paymentMethod=method;
  ['stars','sepay','momo'].forEach(m=>{
    const btn=document.getElementById('pay-'+m+'-btn');
    if(btn) btn.classList.toggle('active',m===method);
    const sec=document.getElementById('pay-'+m+'-section');
    if(sec) sec.style.display=m===method?'':'none';
  });
  if(method!=='sepay'){clearInterval(_sepayTimer);_sepayTimer=null;}
}

// ── closeUpgradeModalBtn (replaces old) ──────────────────────────────────────
function closeUpgradeModal(e) { if(e.target===document.getElementById('upgrade-modal')) closeUpgradeModalBtn(); }
function closeUpgradeModalBtn() {
  document.getElementById('upgrade-modal').classList.remove('open');
  clearInterval(_sepayTimer); _sepayTimer=null; _sepayRef=null;
  const qr=document.getElementById('sepay-qr-area'); if(qr) qr.style.display='none';
  const fp=document.getElementById('sepay-final-price'); if(fp) fp.style.display='none';
  setPaymentMethod('stars');
}

// ── #12 T+2 Prediction helper ─────────────────────────────────────────────────
function _t2PredHtml(d) {
  const nav=d.nav||0; if(!nav) return '';
  const t2Raw=d.t2_prediction?.nav||d.t2_nav||null;
  const t2Date=d.t2_prediction?.date||d.t2_date||null;
  const mape=d.t2_prediction?.mape_7d||d.mape_7d||null;
  const score=d.score||0;
  const predNav=t2Raw||Math.round(nav*(1+score*0.0012));
  const predChg=(predNav-nav)/nav*100;
  const nextBiz=()=>{const d=new Date();d.setDate(d.getDate()+2);return d.toISOString().slice(0,10);};
  const predDate=t2Date||nextBiz();
  return `<div style="background:var(--bg3);border:1px solid var(--bdr);border-radius:8px;padding:8px 12px;margin:6px 14px;display:flex;justify-content:space-between;align-items:center">
    <div>
      <div style="font-size:9px;font-family:var(--mono);color:var(--txt2);text-transform:uppercase;letter-spacing:.08em">Dự báo T+2 (${predDate})</div>
      <div style="font-family:var(--mono);font-size:14px;font-weight:700;margin-top:2px">${fmt(predNav)} đ</div>
    </div>
    <div style="text-align:right">
      <div class="pnl ${pnlC(predChg)}" style="font-size:12px;font-family:var(--mono)">${fmtP(predChg)}</div>
      ${mape!=null?`<div style="font-size:10px;color:var(--txt2);margin-top:2px">MAPE ${Number(mape).toFixed(1)}%</div>`:'<div style="font-size:10px;color:var(--txt3);margin-top:2px">AI dự báo</div>'}
    </div>
  </div>`;
}

// ── #15 Gold School Cards ──────────────────────────────────────────────────────
function _goldSchoolCards(sjcPrice, xauUSD, usdVND, premiumPct, fedRate, inf) {
  const divider=_goldUnit==='chi'?10:1;
  const intlVND=xauUSD*usdVND/37.5/divider;
  // Technical school
  const techSig=premiumPct>15?'BÁN':premiumPct<5?'MUA':'TRUNG LẬP';
  const techSum=premiumPct>15?'Phí bù SJC quá cao — dư địa tăng giá hạn chế.'
    :premiumPct<5?'SJC đang gần giá quốc tế — cơ hội mua tốt.'
    :'Phí bù ở mức hợp lý, thị trường cân bằng.';
  // Macro school
  const macroSig=fedRate<3?'MUA':fedRate>5?'BÁN':'TRUNG LẬP';
  const macroSum=fedRate<3?'Lãi suất Fed thấp — tích sản vàng được hưởng lợi.'
    :fedRate>5?'Lãi suất cao — vàng chịu áp lực từ USD mạnh.'
    :'Lãi suất trung tính — duy trì tỷ trọng hiện tại.';
  // DCA school
  const t1y=sjcPrice*(1+inf/100);
  const dcaSig='MUA';
  const dcaSum=`Mục tiêu 1 năm (+${inf}% lạm phát): ${fmt(Math.round(t1y))} đ. DCA hàng tháng là tối ưu.`;
  const schools=[
    {name:'Kỹ thuật (Phí bù)',signal:techSig,summary:techSum,action:premiumPct>15?'⚠ Cân nhắc chờ phí bù giảm':premiumPct<5?'✓ Điểm vào tốt':'→ Theo dõi thêm'},
    {name:'Vĩ mô (Fed/USD)',signal:macroSig,summary:macroSum,action:fedRate>5?'⚠ Vàng bị áp lực — giảm tỷ trọng':'✓ Tích lũy vàng vật chất'},
    {name:'DCA dài hạn',signal:dcaSig,summary:dcaSum,action:'✓ Mua đều mỗi tháng, không cần đoán đỉnh/đáy'},
  ];
  return '<div class="section"><div class="section-hdr" style="padding:8px 0 4px"><span>3 TRƯỜNG PHÁI VÀNG</span></div>'
    +schools.map(sc=>`<div class="school-card ${sigC(sc.signal)}" onclick="this.classList.toggle('open')">
      <div class="school-hdr"><div><div class="school-title">${sc.name}</div><div class="school-summary">${sc.summary}</div></div>
      <span class="badge ${sigC(sc.signal)}" style="font-size:10px;flex-shrink:0;margin:0 6px">${sigLabel(sc.signal)}</span>
      <span class="school-chevron">▼</span></div>
      <div class="school-detail"><div class="school-action ${sigC(sc.signal)}">${sc.action}</div></div>
    </div>`).join('')+'</div>';
}

// ── #14 Price Alert System ────────────────────────────────────────────────────
let _alerts = [], _alertCode = '';
function openAlertModal(code) {
  _alertCode = code || _researchCode || '';
  const el = document.getElementById('alert-modal'); if (!el) return;
  document.getElementById('alert-fund-code').value = _alertCode;
  document.getElementById('alert-price').value = '';
  document.getElementById('alert-pct').value = '';
  document.getElementById('alert-status').textContent = '';
  _loadAlertList();
  el.style.display = 'flex';
}
function closeAlertModal() { const el=document.getElementById('alert-modal'); if(el) el.style.display='none'; }
async function _loadAlertList() {
  const el=document.getElementById('alert-list'); if(!el) return;
  if (IS_DEV) {
    el.innerHTML = _alerts.length ? _alerts.map((a,i)=>`<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--bdr)">
      <span style="font-family:var(--mono);font-size:12px">${a.code} ${a.direction==='above'?'≥':'≤'} ${fmt(a.price)} đ${a.pct?` (${a.pct>=0?'+':''}${a.pct}%)`:''}
      </span><button onclick="_removeAlert(${i})" style="background:none;border:none;color:var(--sell);cursor:pointer;font-size:14px">×</button></div>`).join('')
      : '<div style="font-size:11px;color:var(--txt2)">Chưa có cảnh báo</div>';
    return;
  }
  try {
    const d=await apiFetch('/api/alerts?user_id='+USER_ID);
    _alerts=d.alerts||[];
    el.innerHTML=_alerts.length?_alerts.map((a,i)=>`<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--bdr)">
      <span style="font-family:var(--mono);font-size:12px">${a.fund_code||a.code} ${a.direction==='above'?'≥':'≤'} ${fmt(a.threshold||a.price)} đ</span>
      <button onclick="deleteAlert(${a.id||i})" style="background:none;border:none;color:var(--sell);cursor:pointer;font-size:14px">×</button></div>`).join('')
      :'<div style="font-size:11px;color:var(--txt2)">Chưa có cảnh báo</div>';
  } catch(e) { el.innerHTML='<div style="font-size:11px;color:var(--txt2)">—</div>'; }
}
function _removeAlert(i) { _alerts.splice(i,1); _loadAlertList(); toast('Đã xoá cảnh báo'); }
let _alertDirection = 'above';
function setAlertDirection(dir, el) {
  _alertDirection=dir;
  document.querySelectorAll('#alert-dir-above,#alert-dir-below').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
}
async function saveAlert() {
  const code=(document.getElementById('alert-fund-code')?.value||'').trim().toUpperCase();
  const price=parseDecimal(document.getElementById('alert-price')?.value);
  const pct=parseDecimal(document.getElementById('alert-pct')?.value);
  const st=document.getElementById('alert-status');
  if(!code||(!price&&!pct)) { if(st){st.style.color='var(--sell)';st.textContent='Nhập mã quỹ và giá/% cảnh báo';} return; }
  const threshold=price||((_signals?.[code]?.nav||0)*(1+(pct||0)/100));
  if(IS_DEV) {
    _alerts.push({code,price:threshold,direction:_alertDirection,pct});
    toast('✓ DEV: Đặt cảnh báo '+code+' '+(price?fmt(threshold)+' đ':fmtP(pct||0)));
    _loadAlertList(); return;
  }
  if(st){st.style.color='var(--txt2)';st.textContent='Đang lưu...';}
  try {
    const d=await apiPost('/api/alerts',{telegram_id:USER_ID,fund_code:code,threshold,direction:_alertDirection});
    if(d.ok){if(st){st.style.color='var(--buy)';st.textContent='✓ Đã đặt cảnh báo';} _loadAlertList();}
    else {if(st){st.style.color='var(--sell)';st.textContent='Lỗi: '+(d.error||'unknown');}}
  } catch(e){if(st){st.style.color='var(--sell)';st.textContent='Lỗi: '+(e.body?.error||e.message);}}
}
async function deleteAlert(id) {
  if(IS_DEV){_removeAlert(id);return;}
  try { await apiDelete('/api/alerts/'+id,{telegram_id:USER_ID}); _loadAlertList(); toast('Đã xoá'); }
  catch(e){toast('Lỗi: '+e.message);}
}

// ── #29 Admin: Recent Payments ────────────────────────────────────────────────
async function loadAdminPayments() {
  const el=document.getElementById('admin-payments-list'); if(!el) return;
  el.innerHTML='<div style="font-size:12px;color:var(--txt2)">Đang tải...</div>';
  if (IS_DEV) {
    el.innerHTML=`<table class="au-table"><thead><tr><th>Người dùng</th><th>Gói</th><th>Phương thức</th><th>Giá</th><th>Ngày</th><th>Trạng thái</th></tr></thead>
      <tbody>
        <tr><td>Harvey</td><td>m3</td><td>SePay</td><td>129,000 đ</td><td>2026-07-20</td><td style="color:var(--buy)">paid</td></tr>
        <tr><td>Test User</td><td>m1</td><td>Stars</td><td>99 ⭐</td><td>2026-07-18</td><td style="color:var(--buy)">paid</td></tr>
      </tbody></table>`; return;
  }
  try {
    const d=await apiFetch('/api/admin/payments/recent?user_id='+(USER_ID||''));
    const list=d.payments||[];
    if(!list.length){el.innerHTML='<div style="font-size:12px;color:var(--txt2)">Chưa có giao dịch</div>';return;}
    const rows=list.map(p=>`<tr>
      <td>${p.name||p.telegram_id}</td><td style="font-family:var(--mono);font-size:11px">${p.plan||'—'}</td>
      <td>${p.method||'—'}</td>
      <td style="font-family:var(--mono);font-size:11px">${p.amount_vnd?fmt(p.amount_vnd)+' đ':(p.stars?p.stars+' ⭐':'—')}</td>
      <td style="font-size:10px;color:var(--txt2)">${(p.created_at||'').slice(0,10)}</td>
      <td style="color:${p.status==='paid'?'var(--buy)':p.status==='pending'?'#facc15':'var(--sell)'}">
        ${p.status||'—'}</td></tr>`).join('');
    el.innerHTML=`<table class="au-table" style="width:100%"><thead><tr><th>User</th><th>Gói</th><th>PP</th><th>Giá</th><th>Ngày</th><th>TT</th></tr></thead><tbody>${rows}</tbody></table>`;
  } catch(e){el.innerHTML=`<div style="font-size:12px;color:var(--sell)">Lỗi: ${e.message}</div>`;}
}

// ── #2 Portfolio School Summary ───────────────────────────────────────────────
function renderSchoolSummary(items) {
  if (!items?.length) return '';
  const schools = items.map(h => _computeSchools({rsi:50, bb:50, macd:0, score: h.signal?.includes('MUA')?3:h.signal?.includes('BAN')||h.signal?.includes('BÁN')?-3:0, chg_pct:h.chg_pct||0}));
  // Aggregate: count buy/sell/hold across 5 schools × all funds
  const votes={buy:0,sell:0,hold:0};
  schools.forEach(sc=>sc.forEach(s=>{const c=sigC(s.signal);if(c==='buy')votes.buy++;else if(c==='sell')votes.sell++;else votes.hold++;}));
  const total=votes.buy+votes.sell+votes.hold;
  if(!total) return '';
  const majority=votes.buy>votes.sell&&votes.buy>votes.hold?'MUA':votes.sell>votes.buy&&votes.sell>votes.hold?'BÁN':'TRUNG LẬP';
  const mc=sigC(majority);
  return `<div style="margin:0 0 8px;background:var(--bg3);border:1px solid var(--bdr);border-radius:8px;padding:8px 12px">
    <div style="font-size:9px;font-family:var(--mono);color:var(--txt2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">TỔNG HỢP 5 TRƯỜNG PHÁI</div>
    <div style="display:flex;align-items:center;gap:10px">
      <span class="badge ${mc}" style="font-size:11px;padding:3px 10px">${majority}</span>
      <div style="flex:1;display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;text-align:center">
        <div style="font-size:10px;color:var(--buy)">MUA<br><b>${votes.buy}</b></div>
        <div style="font-size:10px;color:var(--txt2)">TRUNG<br><b>${votes.hold}</b></div>
        <div style="font-size:10px;color:var(--sell)">BÁN<br><b>${votes.sell}</b></div>
      </div>
    </div>
  </div>`;
}

// ── History tab: view state + switcher ────────────────────────────────────────
let _histView = 'nav';
let _histRange = '1M';
let _cmpCode2 = '';

function setHistView(view, el) {
  _histView = view;
  ['hist-view-nav','hist-view-t2','hist-view-gold','hist-view-cmp'].forEach(id=>{
    const b=document.getElementById(id); if(b) b.classList.remove('active');
  });
  if(el) el.classList.add('active');
  const rangeBar = document.getElementById('hist-range-bar');
  const analysisPanel = document.getElementById('hist-analysis-panel');
  if(rangeBar) rangeBar.style.display = (view==='nav'||view==='cmp') ? 'flex' : 'none';
  if(analysisPanel) analysisPanel.style.display = (view==='nav') ? 'block' : 'none';
  if(view==='nav' && _histPageCode) {
    if (_histPageCode==='GOLD_SJC') loadGoldAnalysis(); else loadHistChart(_histPageCode);
  } else if(view==='t2') renderT2AccuracyChart(_histPageCode||Object.keys(MOCK_SIGNALS||{})[0]||'VESAF');
  else if(view==='gold') loadGoldHistory();
  else if(view==='cmp') loadComparisonView();
}

// ── WEB-012: Fund comparison tool ─────────────────────────────────────────────
async function loadComparisonView() {
  const el = document.getElementById('hist-chart-area'); if (!el) return;
  const code1 = _histPageCode;
  if (!code1) {
    el.innerHTML = '<div style="padding:24px;text-align:center;color:var(--txt2);font-size:12px">Chọn quỹ bên trái để so sánh</div>';
    return;
  }
  const allCodes = Object.keys(_marketData || _signals || MOCK_SIGNALS || {}).filter(c=>c!==code1 && c!=='GOLD_SJC');
  const cmpOpts = allCodes.map(c=>`<option value="${c}" ${c===_cmpCode2?'selected':''}>${c}</option>`).join('');
  const sel2 = `<select onchange="_cmpCode2=this.value;loadComparisonView()" style="font-family:var(--mono);font-size:12px;background:var(--bg3);color:var(--txt);border:1px solid var(--bdr);border-radius:6px;padding:4px 8px;min-width:120px">
    <option value="">-- Chọn quỹ 2 --</option>${cmpOpts}
  </select>`;
  const hdrEl = document.getElementById('hist-nav-header');
  if (hdrEl) hdrEl.innerHTML = `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
    <span style="font-family:var(--mono);font-size:11px;color:var(--c0)">${code1}</span>
    <span style="font-size:10px;color:var(--txt2)">so với</span>
    ${sel2}
  </div>`;
  if (!_cmpCode2) {
    el.innerHTML = '<div style="padding:24px;text-align:center;color:var(--txt2);font-size:12px">Chọn quỹ thứ 2 để so sánh</div>';
    return;
  }
  el.innerHTML = spin();
  try {
    let pts1, pts2;
    if (IS_DEV) {
      const s1 = (MOCK_SIGNALS||{})[code1]||{nav:15000};
      const s2 = (MOCK_SIGNALS||{})[_cmpCode2]||{nav:12000};
      pts1 = _mockNavHistory(s1.nav||15000, 365);
      pts2 = _mockNavHistory(s2.nav||12000, 365);
    } else {
      const _cmpLim = (_histRange && _histRange !== 'ALL') ? `?limit=${({'1M':30,'3M':90,'6M':180,'1Y':365,'3Y':1095}[_histRange]||365)}` : '';
      [pts1, pts2] = await Promise.all([
        apiFetch(`/api/nav_history/${code1}${_cmpLim}`).then(d=>Array.isArray(d)?d:(d.history||d)),
        apiFetch(`/api/nav_history/${_cmpCode2}${_cmpLim}`).then(d=>Array.isArray(d)?d:(d.history||d)),
      ]);
    }
    renderComparisonChart(pts1, pts2, code1, _cmpCode2);
    _renderCmpSignals(code1, _cmpCode2);
  } catch(e) { el.innerHTML = renderErr('Lỗi: '+e.message); }
}

function renderComparisonChart(pts1, pts2, code1, code2) {
  const el = document.getElementById('hist-chart-area'); if (!el) return;
  // Apply time range
  let p1 = pts1, p2 = pts2;
  if (_histRange && _histRange !== 'ALL') {
    const days = {'1M':30,'3M':90,'6M':180,'1Y':365}[_histRange]||30;
    const cutoff = new Date(); cutoff.setDate(cutoff.getDate()-days);
    const cut = cutoff.toISOString().slice(0,10);
    p1 = p1.filter(p=>p.date>=cut);
    p2 = p2.filter(p=>p.date>=cut);
  }
  if (!p1.length && !p2.length) { el.innerHTML='<div style="color:var(--txt2);padding:24px;text-align:center">Chưa có dữ liệu</div>'; return; }
  // Build union of dates (all dates from both series)
  const allDates = [...new Set([...p1.map(p=>p.date), ...p2.map(p=>p.date)])].sort();
  const map1 = Object.fromEntries(p1.map(p=>[p.date, p.nav]));
  const map2 = Object.fromEntries(p2.map(p=>[p.date, p.nav]));
  // Forward-fill missing dates
  let last1=null, last2=null;
  const vals1=[], vals2=[];
  allDates.forEach(d=>{
    if(map1[d]!=null) last1=map1[d];
    if(map2[d]!=null) last2=map2[d];
    vals1.push(last1); vals2.push(last2);
  });
  // Normalize to % return from first valid point
  const base1 = vals1.find(v=>v!=null)||1;
  const base2 = vals2.find(v=>v!=null)||1;
  const norm1 = vals1.map(v=>v!=null?((v-base1)/base1*100):null);
  const norm2 = vals2.map(v=>v!=null?((v-base2)/base2*100):null);
  // Calc final returns for header
  const fin1 = norm1.filter(v=>v!=null).slice(-1)[0]??0;
  const fin2 = norm2.filter(v=>v!=null).slice(-1)[0]??0;
  const c1Color='#00e5ff', c2Color='#fbbf24';
  // Stats in header
  const hdrEl = document.getElementById('hist-nav-header');
  if (hdrEl) {
    const sel2 = hdrEl.querySelector('select');
    const selHtml = sel2 ? sel2.outerHTML : '';
    hdrEl.innerHTML = `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <span style="font-family:var(--mono);font-size:11px;color:${c1Color}">${code1} <span class="pnl ${pnlC(fin1)}">${fin1>=0?'+':''}${fin1.toFixed(2)}%</span></span>
      <span style="font-size:10px;color:var(--txt2)">vs</span>
      ${selHtml||`<span style="font-family:var(--mono);font-size:11px;color:${c2Color}">${code2}</span>`}
      <span style="font-family:var(--mono);font-size:11px;color:${c2Color}">${code2} <span class="pnl ${pnlC(fin2)}">${fin2>=0?'+':''}${fin2.toFixed(2)}%</span></span>
    </div>
    <div style="font-size:10px;color:var(--txt2);margin-top:2px">% sinh lời từ đầu kỳ (tỷ lệ hóa về 0%)</div>`;
  }
  el.innerHTML = '<canvas id="cmp-canvas"></canvas>';
  const ctx = document.getElementById('cmp-canvas'); if(!ctx) return;
  if (_histPageChart) { try{_histPageChart.destroy();}catch(e){} _histPageChart=null; }
  _histPageChart = new Chart(ctx, {
    type:'line',
    data:{labels:allDates, datasets:[
      {label:code1, data:norm1, borderColor:c1Color, borderWidth:1.5, fill:false, tension:0.25, pointRadius:0, pointHoverRadius:4, spanGaps:true},
      {label:code2, data:norm2, borderColor:c2Color, borderWidth:1.5, fill:false, tension:0.25, pointRadius:0, pointHoverRadius:4, spanGaps:true},
    ]},
    options:{responsive:true, maintainAspectRatio:false, animation:false,
      plugins:{
        legend:{display:true, position:'top', labels:{color:'#9ca3af',font:{size:10},boxWidth:12,padding:10}},
        tooltip:{mode:'index', intersect:false, callbacks:{label:(c)=>`${c.dataset.label}: ${c.parsed.y!=null?(c.parsed.y>=0?'+':'')+c.parsed.y.toFixed(2)+'%':'N/A'}`}},
        crosshair:_crosshairPlugin
      },
      scales:{
        x:{ticks:{maxTicksLimit:8,color:'#6b7280',font:{size:10}},grid:{color:'rgba(255,255,255,.04)'}},
        y:{ticks:{color:'#6b7280',font:{size:10}, callback:v=>(v>=0?'+':'')+v.toFixed(1)+'%'}, grid:{color:'rgba(255,255,255,.04)'},
           title:{display:true, text:'% Sinh lời', color:'#6b7280',font:{size:9}}}
      }
    }
  });
}

function _renderCmpSignals(code1, code2) {
  const panel = document.getElementById('hist-analysis-panel'); if(!panel) return;
  panel.style.display='block';
  const s1 = (_signals?.[code1])||(_marketData?.[code1])||(MOCK_SIGNALS?.[code1]);
  const s2 = (_signals?.[code2])||(_marketData?.[code2])||(MOCK_SIGNALS?.[code2]);
  if(!s1 && !s2) { panel.innerHTML=''; return; }
  const fmtI = (v,unit='')=>v!=null?v.toFixed(2)+unit:'—';
  const sigBadge = sig=>{
    const sc=sigC(sig); const label={'buy':'MUA','strong_buy':'MUA MẠNH','sell':'BÁN','strong_sell':'BÁN MẠNH'}[sig]||'TL';
    return `<span class="sig-badge ${sc}" style="font-size:10px;padding:2px 6px">${label}</span>`;
  };
  const row=(label,v1,v2)=>`<tr>
    <td style="color:var(--txt2);font-size:10px;padding:4px 0">${label}</td>
    <td style="font-family:var(--mono);font-size:11px;text-align:right;color:var(--c0);padding:4px 8px">${v1}</td>
    <td style="font-family:var(--mono);font-size:11px;text-align:right;color:#fbbf24;padding:4px 0">${v2}</td>
  </tr>`;
  panel.innerHTML=`
  <div style="padding:12px 0 4px;font-family:var(--mono);font-size:10px;color:var(--txt2);letter-spacing:.06em">SO SÁNH TÍN HIỆU</div>
  <table style="width:100%;border-collapse:collapse">
    <thead><tr>
      <th style="font-size:9px;color:var(--txt3);text-align:left;padding-bottom:4px;font-weight:400"></th>
      <th style="font-size:10px;color:#00e5ff;text-align:right;padding-bottom:4px;font-family:var(--mono)">${code1}</th>
      <th style="font-size:10px;color:#fbbf24;text-align:right;padding-bottom:4px;font-family:var(--mono)">${code2}</th>
    </tr></thead>
    <tbody>
      ${row('NAV', s1?fmt(s1.nav)+'đ':'—', s2?fmt(s2.nav)+'đ':'—')}
      ${row('Thay đổi 1N', s1?fmtP(s1.chg_pct):'—', s2?fmtP(s2.chg_pct):'—')}
      ${row('RSI(14)', fmtI(s1?.rsi), fmtI(s2?.rsi))}
      ${row('BB%B', fmtI(s1?.bb_pct??s1?.bb), fmtI(s2?.bb_pct??s2?.bb))}
      ${row('MACD hist', fmtI(s1?.macd_hist??s1?.macd), fmtI(s2?.macd_hist??s2?.macd))}
      <tr>
        <td style="color:var(--txt2);font-size:10px;padding:6px 0 4px">Tín hiệu</td>
        <td style="text-align:right;padding:6px 8px 4px">${s1?sigBadge(s1.signal):'—'}</td>
        <td style="text-align:right;padding:6px 0 4px">${s2?sigBadge(s2.signal):'—'}</td>
      </tr>
      ${row('Score', s1?.score!=null?s1.score.toFixed(1):'—', s2?.score!=null?s2.score.toFixed(1):'—')}
    </tbody>
  </table>`;
}

function setHistRange(range, el) {
  _histRange = range;
  document.querySelectorAll('.hist-range-btn').forEach(b=>b.classList.remove('active'));
  if(el) el.classList.add('active');
  if(_histView==='cmp' && _histPageCode && _cmpCode2) loadComparisonView();
  else if(_histPageData) renderHistChart(_histPageData, _histPageCode);
}

// ── Bulk NAV entry ─────────────────────────────────────────────────────────────
function _makeBulkRow(code='', date='', nav='') {
  const today = new Date().toISOString().slice(0,10);
  const row = document.createElement('div');
  row.className = 'bulk-nav-row';
  row.innerHTML = `
    <input type="text" class="bnr-code" placeholder="TCBF" value="${code}" oninput="this.value=this.value.toUpperCase()" style="text-transform:uppercase">
    <input type="date" class="bnr-date" value="${date||today}">
    <input type="text" class="bnr-nav"  placeholder="14500" value="${nav}">
    <button onclick="this.closest('.bulk-nav-row').remove();_updateBulkBtn()" style="background:none;border:none;color:var(--txt3);font-size:14px;cursor:pointer;padding:0;line-height:1">×</button>`;
  return row;
}
function addBulkNavRow(code='', date='', nav='') {
  const container = document.getElementById('bulk-nav-rows'); if(!container) return;
  container.appendChild(_makeBulkRow(code, date, nav));
  _updateBulkBtn();
}
function _updateBulkBtn() {
  const count = document.querySelectorAll('.bulk-nav-row').length;
  const btn = document.querySelector('button[onclick="submitBulkNav()"]');
  if(btn) btn.textContent = `Lưu tất cả${count>0?' ('+count+')':''}`;
}
function _initBulkRows() {
  const container = document.getElementById('bulk-nav-rows'); if(!container) return;
  if(!container.children.length) { addBulkNavRow(); }
}
async function submitBulkNav() {
  const rows = document.querySelectorAll('.bulk-nav-row');
  const st = document.getElementById('bulk-nav-status');
  const entries = [];
  let hasError = false;
  rows.forEach(row=>{
    const code = (row.querySelector('.bnr-code')?.value||'').trim().toUpperCase();
    const date = row.querySelector('.bnr-date')?.value||'';
    const raw  = (row.querySelector('.bnr-nav')?.value||'').replace(/\./g,'').replace(',','.').trim();
    const nav  = parseFloat(raw);
    if(!code||!date||!nav||nav<=0) { hasError=true; return; }
    entries.push({code, date, nav: Math.round(nav)});
  });
  if(!entries.length) {
    if(st){st.style.color='var(--sell)';st.textContent=hasError?'Kiểm tra lại thông tin':'Chưa có dòng nào';}
    return;
  }
  if(IS_DEV) {
    if(st){st.style.color='var(--buy)';st.textContent=`✓ DEV: ${entries.length} NAV — ${entries.map(e=>e.code).join(', ')}`;}
    // Refresh chart if current code was in batch
    const codes = entries.map(e=>e.code);
    if(_histPageCode && codes.includes(_histPageCode)) loadHistChart(_histPageCode);
    return;
  }
  if(st){st.style.color='var(--txt2)';st.textContent='Đang lưu...';}
  const isAdmin = _me?.is_admin;
  const endpoint = isAdmin ? '/api/admin/import-nav' : '/api/nav/draft';
  // Group by code
  const byCode = {};
  entries.forEach(e=>{ if(!byCode[e.code]) byCode[e.code]=[]; byCode[e.code].push({date:e.date,nav:e.nav}); });
  try {
    await apiPost(endpoint, {tg_id:String(USER_ID), funds:byCode});
    if(st){st.style.color='var(--buy)';st.textContent=`✓ Đã lưu ${entries.length} NAV`;}
    const codes = entries.map(e=>e.code);
    if(_histPageCode && codes.includes(_histPageCode)) loadHistChart(_histPageCode);
  } catch(e) { if(st){st.style.color='var(--sell)';st.textContent='Lỗi: '+(e?.body?.error||e.message);} }
}

// ── Analysis panel below chart ─────────────────────────────────────────────────
function _renderHistAnalysis(code) {
  const panel = document.getElementById('hist-analysis-panel'); if(!panel) return;
  // Use any available signal source: signals API → market data → mock
  const s = (_signals?.[code]) || (_marketData?.[code]) || (MOCK_SIGNALS?.[code]);
  const pfItem = _me?.portfolio?.items?.find(h=>h.code===code);
  if(!s && !pfItem) {
    panel.innerHTML=`<div style="color:var(--txt2);font-size:12px;padding:16px;text-align:center;line-height:1.7">
      <div style="font-size:22px;margin-bottom:8px">📊</div>
      <div style="color:var(--txt1);font-weight:600;font-family:var(--mono);font-size:11px;margin-bottom:6px">${code}</div>
      <div>Chưa đủ dữ liệu để tính tín hiệu.<br><span style="font-size:10px">Cần ít nhất 20 ngày NAV để tính RSI/BB%/MACD.<br>Dùng "Nhập NAV thủ công" bên dưới để bổ sung.</span></div>
    </div>`;
    return;
  }

  const rsi = s?.rsi||50;
  const bb  = s?.bb_pct??s?.bb??50;
  const macd= s?.macd_hist??s?.macd??0;
  const score=s?.score||0;
  const rsiColor = rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--txt2)';
  const rsiLabel = rsi<30?'Quá bán':rsi<45?'Yếu':rsi>70?'Quá mua':rsi>55?'Mạnh':'Trung tính';
  const bbColor  = bb<30?'var(--buy)':bb>70?'var(--sell)':'var(--txt2)';
  const macdColor= macd>0?'var(--buy)':macd<0?'var(--sell)':'var(--txt2)';

  // P&L block (only if in portfolio)
  let pnlHtml = '';
  if(pfItem) {
    const nav = s?.nav || pfItem.current_nav || 0;
    const units = pfItem.units||0;
    const cost  = pfItem.cost||0;
    const mktVal= nav*units;
    const pnl   = mktVal - cost;
    const pnlP  = cost>0 ? pnl/cost*100 : 0;
    pnlHtml = `
      <div style="background:var(--bg3);border-radius:8px;padding:10px 12px;margin-bottom:10px">
        <div style="font-size:10px;font-family:var(--mono);color:var(--txt2);margin-bottom:6px;letter-spacing:.05em">P&amp;L — ${code}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
          <div><div style="font-size:10px;color:var(--txt3)">Giá trị TT</div><div style="font-family:var(--mono);font-size:13px;font-weight:600">${(mktVal/1e6).toFixed(2)}M</div></div>
          <div><div style="font-size:10px;color:var(--txt3)">Lãi/Lỗ</div><div class="pnl ${pnlC(pnlP)}" style="font-family:var(--mono);font-size:13px;font-weight:600">${pnl>=0?'+':''}${(pnl/1e6).toFixed(2)}M (${fmtP(pnlP)})</div></div>
          <div><div style="font-size:10px;color:var(--txt3)">Số CCQ</div><div style="font-family:var(--mono);font-size:12px">${units.toFixed(2)}</div></div>
          <div><div style="font-size:10px;color:var(--txt3)">Giá vốn TB</div><div style="font-family:var(--mono);font-size:12px">${fmt(cost/units||0)} đ</div></div>
        </div>
      </div>`;
  }

  // Technical indicators
  const indHtml = s ? `
    <div style="font-size:10px;font-family:var(--mono);color:var(--txt2);letter-spacing:.05em;margin-bottom:8px">CHỈ SỐ KỸ THUẬT</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
      <div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:10px;color:var(--txt3);margin-bottom:4px">RSI (14)</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${rsiColor}">${rsi.toFixed(1)}</div>
        <div style="font-size:10px;color:${rsiColor};margin-top:2px">${rsiLabel}</div>
        <div style="height:4px;background:var(--bdr);border-radius:2px;margin-top:6px"><div style="height:100%;width:${Math.min(rsi,100)}%;background:${rsiColor};border-radius:2px"></div></div>
      </div>
      <div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:10px;color:var(--txt3);margin-bottom:4px">BB %B</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${bbColor}">${bb.toFixed(1)}%</div>
        <div style="font-size:10px;color:${bbColor};margin-top:2px">${bb<30?'Gần band dưới':bb>70?'Gần band trên':'Giữa dải'}</div>
        <div style="height:4px;background:var(--bdr);border-radius:2px;margin-top:6px"><div style="height:100%;width:${Math.min(bb,100)}%;background:${bbColor};border-radius:2px"></div></div>
      </div>
      <div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:10px;color:var(--txt3);margin-bottom:4px">MACD</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${macdColor}">${macd>=0?'+':''}${(macd||0).toFixed(2)}</div>
        <div style="font-size:10px;color:${macdColor};margin-top:2px">${macd>0?'Xu hướng tăng':macd<0?'Xu hướng giảm':'Trung tính'}</div>
      </div>
      <div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:10px;color:var(--txt3);margin-bottom:4px">Score</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${score>0?'var(--buy)':score<0?'var(--sell)':'var(--txt2)'}">${score>0?'+':''}${score}</div>
        <div style="font-size:10px;color:var(--txt2);margin-top:2px">${score>=2?'Tín hiệu MUA':score<=-2?'Tín hiệu BÁN':'Chờ đợi'}</div>
      </div>
    </div>` : '';

  // T+2 prediction block
  const t2Nav = s?.t2_prediction?.nav || s?.t2_nav;
  const t2Date = s?.t2_prediction?.date || '';
  const t2Dev = (t2Nav && s?.nav) ? ((t2Nav - s.nav) / s.nav * 100) : null;
  const t2Html = (s && t2Nav) ? `
    <div style="background:var(--bg3);border:1px solid #facc1533;border-radius:8px;padding:10px 12px;margin-bottom:10px">
      <div style="font-size:10px;font-family:var(--mono);color:var(--txt2);letter-spacing:.05em;margin-bottom:6px">DỰ BÁO T+2${t2Date?' · '+t2Date:''}</div>
      <div style="display:flex;align-items:baseline;gap:8px">
        <div style="font-family:var(--mono);font-size:16px;font-weight:700;color:#facc15">${fmt(t2Nav)} đ</div>
        ${t2Dev!=null?`<div class="pnl ${pnlC(t2Dev)}" style="font-size:12px">${t2Dev>=0?'+':''}${t2Dev.toFixed(2)}%</div>`:''}
      </div>
      <div style="font-size:10px;color:var(--txt3);margin-top:3px">Dự báo dựa trên mô hình trend ngắn hạn</div>
    </div>` : '';

  // Data adequacy warning
  const pts = _histPageData || [];
  const dataWarnHtml = (s && pts.length > 0 && pts.length < 20) ? `
    <div style="background:#facc1511;border:1px solid #facc1533;border-radius:6px;padding:6px 10px;margin-bottom:8px;font-size:10px;color:#facc15">
      ⚠ Chỉ có ${pts.length} điểm NAV — tín hiệu RSI/BB%/MACD có thể chưa chính xác (cần ≥20 ngày)
    </div>` : '';

  // Conclusion
  const scoreDesc = score>=4?'MUA MẠNH':score>=2?'MUA':score<=-4?'BÁN MẠNH':score<=-2?'BÁN':'TRUNG LẬP';
  const scoreColor = score>=2?'var(--buy)':score<=-2?'var(--sell)':'var(--txt2)';
  const conclusionHtml = s ? `
    <div style="background:var(--bg3);border-radius:8px;padding:8px 12px;text-align:center">
      <div style="font-size:9px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;margin-bottom:4px">KẾT LUẬN</div>
      <div style="font-family:var(--mono);font-size:13px;font-weight:700;color:${scoreColor}">Score ${score>0?'+':''}${score} — ${scoreDesc}</div>
    </div>` : '';

  panel.innerHTML = `<div style="padding:12px 0">${pnlHtml}${t2Html}${dataWarnHtml}${indHtml}${conclusionHtml}</div>`;
}

// WEB-011: Gold analysis in Phân Tích tab ──────────────────────────────────────
async function loadGoldAnalysis() {
  _histPageCode = 'GOLD_SJC';
  const lbl = document.getElementById('hist-fund-label');
  if (lbl) lbl.textContent = '🥇 VÀNG SJC';
  // Ensure NAV view mode (shows analysis panel)
  if (_histView !== 'nav') {
    _histView = 'nav';
    ['hist-view-nav','hist-view-t2','hist-view-gold'].forEach(id=>{
      const b=document.getElementById(id); if(b) b.classList.remove('active');
    });
    const nb=document.getElementById('hist-view-nav'); if(nb) nb.classList.add('active');
  }
  const rangeBar=document.getElementById('hist-range-bar');
  const analysisPanel=document.getElementById('hist-analysis-panel');
  if(rangeBar) rangeBar.style.display='flex';
  if(analysisPanel) analysisPanel.style.display='block';
  // Update active row in fund list
  document.querySelectorAll('.hist-fund-row').forEach(r=>{
    r.classList.toggle('active', !!r.querySelector('.hist-fund-code[style*="fbbf24"]'));
  });
  const chartEl=document.getElementById('hist-chart-area'); if(!chartEl) return;
  chartEl.innerHTML=spin();
  try {
    if (!_goldData) {
      const d=await apiFetch(`/api/gold?user_id=${USER_ID}`);
      _goldData=d;
    }
    const prod='VANGTODAYAPI:SJC_1L';
    const hist=await apiFetch('/api/gold/price_history/'+encodeURIComponent(prod)).catch(()=>({history:[]}));
    const history=hist.history||[];
    if (history.length) {
      chartEl.innerHTML='<canvas id="gold-analysis-canvas" style="width:100%;height:100%"></canvas>';
      if (_histPageChart) { _histPageChart.destroy(); _histPageChart=null; }
      const labels=history.map(h=>h.date);
      const vals=history.map(h=>h.sell||h.buy||0);
      _histPageChart=new Chart(document.getElementById('gold-analysis-canvas'),{
        type:'line',
        data:{labels,datasets:[{data:vals,borderColor:'#fbbf24',borderWidth:2,fill:true,backgroundColor:'#fbbf2422',tension:0.3,pointRadius:0}]},
        options:{responsive:true,maintainAspectRatio:false,
          plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>fmt(c.parsed.y)+' đ'}}},
          scales:{x:{display:false},y:{display:true,grid:{color:'#1e3050'},
            ticks:{color:'#94a3b8',font:{family:'IBM Plex Mono',size:10},
              callback:v=>v>=1e6?(v/1e6).toFixed(0)+'M':''+v}}}}
      });
    } else {
      chartEl.innerHTML='<div style="color:var(--txt2);font-size:12px;padding:24px;text-align:center;line-height:1.7">📊<br>Chưa có lịch sử giá vàng SJC.<br><span style="font-size:10px">Cần kết nối Railway DB để xem biểu đồ.</span></div>';
    }
  } catch(e) { if(chartEl) chartEl.innerHTML=renderErr('Lỗi: '+e.message); }
  _renderGoldAnalysisPanel();
}

function _renderGoldAnalysisPanel() {
  const panel=document.getElementById('hist-analysis-panel'); if(!panel) return;
  const s=_goldData?.signals;
  const hasData = s && (s.price || s.rsi != null);
  if (!hasData) {
    panel.innerHTML=`<div style="color:var(--txt2);font-size:12px;padding:16px;text-align:center;line-height:1.7">
      <div style="font-size:22px;margin-bottom:8px">🥇</div>
      <div style="color:var(--txt1);font-weight:600;font-family:var(--mono);font-size:11px;margin-bottom:6px">VÀNG SJC</div>
      <div>Tín hiệu vàng chỉ có trên Railway.<br><span style="font-size:10px;color:var(--txt3)">Giá vàng lịch sử cần DB cloud để tính RSI/BB%.</span></div>
    </div>`;
    return;
  }
  const rsi=s.rsi||50, bb=s.bb_pct||50, score=s.score||0;
  const rsiColor=rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--txt2)';
  const rsiLabel=rsi<33?'Quá bán':rsi<48?'Yếu':rsi>70?'Quá mua':rsi>55?'Mạnh':'Trung tính';
  const bbColor=bb<25?'var(--buy)':bb>75?'var(--sell)':'var(--txt2)';
  const priceHtml=s.price?`
    <div style="background:var(--bg3);border-radius:8px;padding:10px 12px;margin-bottom:10px">
      <div style="font-size:10px;font-family:var(--mono);color:var(--txt2);letter-spacing:.05em;margin-bottom:6px">GIÁ VÀNG SJC HIỆN TẠI</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
        <div><div style="font-size:10px;color:var(--txt3)">Giá bán</div><div style="font-family:var(--mono);font-size:13px;font-weight:600">${fmt(s.price)} đ/lượng</div></div>
        <div><div style="font-size:10px;color:var(--txt3)">Thay đổi ngày</div><div class="pnl ${pnlC(s.chg_pct||0)}" style="font-family:var(--mono);font-size:13px;font-weight:600">${fmtP(s.chg_pct||0)}</div></div>
        ${s.ma20?`<div><div style="font-size:10px;color:var(--txt3)">MA20</div><div style="font-family:var(--mono);font-size:12px">${fmt(s.ma20)} đ</div></div>`:''}
        ${s.ma50?`<div><div style="font-size:10px;color:var(--txt3)">MA50</div><div style="font-family:var(--mono);font-size:12px">${fmt(s.ma50)} đ</div></div>`:''}
      </div>
    </div>`:'';
  const indHtml=`
    <div style="font-size:10px;font-family:var(--mono);color:var(--txt2);letter-spacing:.05em;margin-bottom:8px">CHỈ SỐ KỸ THUẬT — VÀNG SJC</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
      <div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:10px;color:var(--txt3);margin-bottom:4px">RSI (14)</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${rsiColor}">${rsi.toFixed?rsi.toFixed(1):rsi}</div>
        <div style="font-size:10px;color:${rsiColor};margin-top:2px">${rsiLabel}</div>
        <div style="height:4px;background:var(--bdr);border-radius:2px;margin-top:6px"><div style="height:100%;width:${Math.min(rsi,100)}%;background:${rsiColor};border-radius:2px"></div></div>
      </div>
      <div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:10px;color:var(--txt3);margin-bottom:4px">BB %B</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${bbColor}">${bb.toFixed?bb.toFixed(1):bb}%</div>
        <div style="font-size:10px;color:${bbColor};margin-top:2px">${bb<25?'Gần band dưới':bb>75?'Gần band trên':'Giữa dải'}</div>
        <div style="height:4px;background:var(--bdr);border-radius:2px;margin-top:6px"><div style="height:100%;width:${Math.min(bb,100)}%;background:${bbColor};border-radius:2px"></div></div>
      </div>
      <div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:10px;color:var(--txt3);margin-bottom:4px">Score</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${score>0?'var(--buy)':score<0?'var(--sell)':'var(--txt2)'}">${score>0?'+':''}${score}</div>
        <div style="font-size:10px;color:var(--txt3);margin-top:2px">Thang vàng (max ±4)</div>
      </div>
      ${s.ma20?`<div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:10px;color:var(--txt3);margin-bottom:4px">Xu hướng MA</div>
        <div style="font-family:var(--mono);font-size:13px;font-weight:700;color:${s.price>s.ma20?'var(--buy)':'var(--sell)'}">
          ${s.price>s.ma20?'↑ Trên MA20':'↓ Dưới MA20'}
        </div>
        <div style="font-size:10px;color:var(--txt3);margin-top:2px">${s.ma50?(s.price>s.ma50?'↑ Trên MA50':'↓ Dưới MA50'):''}</div>
      </div>`:'' }
    </div>`;
  const scoreDesc=score>=3?'MUA':score>=1?'TÍCH LŨY':score<=-2?'THẬN TRỌNG':'HOLD';
  const scoreColor=score>=1?'var(--buy)':score<=-2?'var(--sell)':'var(--txt2)';
  const conclusionHtml=`
    <div style="background:var(--bg3);border-radius:8px;padding:8px 12px;text-align:center">
      <div style="font-size:9px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;margin-bottom:4px">KẾT LUẬN — VÀNG SJC</div>
      <div style="font-family:var(--mono);font-size:13px;font-weight:700;color:${scoreColor}">${s.signal||('Score '+(score>0?'+':'')+score+' — '+scoreDesc)}</div>
    </div>`;
  panel.innerHTML=`<div style="padding:12px 0">${priceHtml}${indHtml}${conclusionHtml}</div>`;
}

// #13 T+2 accuracy chart ───────────────────────────────────────────────────────
async function renderT2AccuracyChart(code) {
  const el=document.getElementById('hist-chart-area'); if(!el) return;
  el.innerHTML=spin();
  let pts, summary=[];
  if (IS_DEV) {
    const days=30, nav0=(_histPageData?.history?.slice(-1)[0]?.nav)||15000;
    let nav=nav0*(0.9+Math.random()*0.05); pts=[];
    for(let i=days;i>=0;i--){
      const d=new Date();d.setDate(d.getDate()-i);
      if(d.getDay()===0||d.getDay()===6) continue;
      nav*=(1+(Math.random()-0.47)*0.007);
      const predicted=Math.round(nav*(0.995+Math.random()*0.01));
      pts.push({date:d.toISOString().slice(0,10),actual:Math.round(nav),predicted,error_pct:(predicted-Math.round(nav))/Math.round(nav)*100});
    }
  } else {
    try {
      const d=await apiFetch(`/api/t2/accuracy/${code}`);
      const hist=(d.history||[]).slice().reverse(); // API trả newest-first → oldest-first cho chart
      summary=d.summary||[];
      if (!hist.length) {
        el.innerHTML='<div style="padding:24px;text-align:center;color:var(--txt2)">Chưa có dữ liệu dự báo T+2 để so sánh.<br><span style="font-size:11px;opacity:.7">Dữ liệu tích lũy sau khi pipeline T+2 chạy đủ ngày.</span></div>';
        const st=document.getElementById('hist-stats');
        if(st) st.innerHTML=`<div class="sum-row"><span class="sum-label">Quỹ</span><span class="sum-val">${code}</span></div><div style="font-size:11px;color:var(--txt2);margin-top:8px">Chưa có dữ liệu chấm điểm T+2</div>`;
        return;
      }
      pts=hist.map(h=>({date:h.predicted_for_date,actual:h.actual_nav,predicted:h.predicted_nav,error_pct:h.error_pct}));
    } catch(e) {
      el.innerHTML=`<div style="padding:24px;text-align:center;color:var(--sell)">Lỗi tải T+2: ${e.message}</div>`;
      return;
    }
  }
  const labels=pts.map(p=>p.date.slice(5));
  el.innerHTML='<canvas id="t2-acc-canvas" style="width:100%;height:100%"></canvas>';
  if(_histPageChart){try{_histPageChart.destroy();}catch(e){}_histPageChart=null;}
  const ctx=document.getElementById('t2-acc-canvas');
  _histPageChart=new Chart(ctx,{type:'line',data:{labels,datasets:[
    {label:'NAV Thực tế',data:pts.map(p=>p.actual),borderColor:'#4ade80',borderWidth:2,fill:false,tension:0.3,pointRadius:0},
    {label:'Dự báo T+2',data:pts.map(p=>p.predicted),borderColor:'#facc15',borderWidth:1.5,fill:false,tension:0.3,pointRadius:0,borderDash:[4,4]},
  ]},options:{responsive:true,maintainAspectRatio:false,animation:false,
    plugins:{legend:{display:true,labels:{color:'#94a3b8',font:{family:'IBM Plex Mono',size:10}}},tooltip:{mode:'index',intersect:false}},
    scales:{x:{ticks:{color:'#6b7280',font:{size:10},maxTicksLimit:8},grid:{color:'rgba(255,255,255,.04)'}},
      y:{ticks:{color:'#6b7280',font:{size:10},callback:v=>fmt(Math.round(v))},grid:{color:'rgba(255,255,255,.04)'}}}}});
  const errs=pts.map(p=>Math.abs(typeof p.error_pct==='number'?p.error_pct:(p.predicted-p.actual)/p.actual*100));
  const mape=(errs.reduce((a,b)=>a+b,0)/errs.length).toFixed(2);
  const bestModel=summary.length?summary[0].model_version:'—';
  const st=document.getElementById('hist-stats');
  if(st) st.innerHTML=`
    <div class="sum-row"><span class="sum-label">Quỹ</span><span class="sum-val">${code}</span></div>
    <div class="sum-row"><span class="sum-label">MAPE (${pts.length} phiên)</span><span class="sum-val pnl ${parseFloat(mape)<5?'pos':'neg'}">${mape}%</span></div>
    ${summary.length?`<div class="sum-row"><span class="sum-label">Model tốt nhất</span><span class="sum-val" style="color:var(--c0)">${bestModel}</span></div>`:''}
    <div style="margin-top:8px;font-size:10px;color:var(--txt2)">Đường xanh = Thực tế · Vàng đứt = T+2 dự báo</div>`;
}

// #21 Gold history multi-series chart ─────────────────────────────────────────
async function loadGoldHistory() {
  const el=document.getElementById('hist-chart-area'); if(!el) return;
  el.innerHTML=spin();
  const colors=['#fbbf24','#f97316','#a78bfa','#34d399','#60a5fa'];
  if(IS_DEV) {
    const prods=Object.keys(MOCK_GOLD?.portfolio?.by_product||{});
    const days=60;
    const allLabels=[];
    for(let i=days;i>=0;i--){const d=new Date();d.setDate(d.getDate()-i);if(d.getDay()!==0&&d.getDay()!==6)allLabels.push(d.toISOString().slice(0,10));}
    const datasets=prods.map((prod,pi)=>{
      const base=(MOCK_GOLD.portfolio.by_product[prod]?.price_buy)||87000000;
      let p=base*(0.92+Math.random()*0.04);
      return{label:prod.replace('VANGTODAYAPI:','').replace(/_/g,' '),
        data:allLabels.map(()=>{p*=(1+(Math.random()-0.47)*0.007);return Math.round(p);}),
        borderColor:colors[pi%colors.length],borderWidth:1.5,fill:false,tension:0.3,pointRadius:0};
    });
    el.innerHTML='<canvas id="gold-hist-canvas" style="width:100%;height:100%"></canvas>';
    if(_histPageChart){try{_histPageChart.destroy();}catch(e){}_histPageChart=null;}
    _histPageChart=new Chart(document.getElementById('gold-hist-canvas'),{type:'line',
      data:{labels:allLabels,datasets},
      options:{responsive:true,maintainAspectRatio:false,animation:false,
        plugins:{legend:{display:true,labels:{color:'#94a3b8',font:{family:'IBM Plex Mono',size:10}}}},
        scales:{x:{ticks:{color:'#6b7280',font:{size:10},maxTicksLimit:8},grid:{color:'rgba(255,255,255,.04)'}},
          y:{ticks:{color:'#6b7280',font:{size:10},callback:v=>(v/1e6).toFixed(1)+'M ₫'},grid:{color:'rgba(255,255,255,.04)'}}}}});
    const st=document.getElementById('hist-stats');
    if(st) st.innerHTML=`<div style="font-size:11px;color:var(--txt2)">Giá vàng ${prods.length} sản phẩm · ${days} phiên</div>`;
    return;
  }
  try{
    const prods=Object.keys(_goldData?.portfolio?.by_product||{});
    if(!prods.length){el.innerHTML='<div style="padding:24px;text-align:center;color:var(--txt2)">Chưa có vàng trong danh mục</div>';return;}
    const histories=await Promise.all(prods.map(p=>apiFetch('/api/gold/price_history/'+encodeURIComponent(p)).catch(()=>({history:[]}))));
    const labelsSet=new Set();
    histories.forEach(h=>(h.history||[]).forEach(p=>labelsSet.add(p.date)));
    const allLabels=[...labelsSet].sort();
    const datasets=prods.map((prod,i)=>{
      const h=histories[i]?.history||[];
      const byDate=Object.fromEntries(h.map(p=>[p.date,p.price]));
      return{label:prod,data:allLabels.map(d=>byDate[d]||null),borderColor:colors[i%colors.length],borderWidth:1.5,fill:false,tension:0.3,pointRadius:0,spanGaps:true};
    });
    el.innerHTML='<canvas id="gold-hist-canvas" style="width:100%;height:100%"></canvas>';
    if(_histPageChart){try{_histPageChart.destroy();}catch(e){}_histPageChart=null;}
    _histPageChart=new Chart(document.getElementById('gold-hist-canvas'),{type:'line',data:{labels:allLabels,datasets},
      options:{responsive:true,maintainAspectRatio:false,animation:false,
        plugins:{legend:{display:true,labels:{color:'#94a3b8',font:{family:'IBM Plex Mono',size:10}}}},
        scales:{x:{ticks:{color:'#6b7280',font:{size:10},maxTicksLimit:8},grid:{color:'rgba(255,255,255,.04)'}},
          y:{ticks:{color:'#6b7280',font:{size:10},callback:v=>(v/1e6).toFixed(1)+'M ₫'},grid:{color:'rgba(255,255,255,.04)'}}}}});
  }catch(e){el.innerHTML=renderErr('Lỗi tải lịch sử vàng: '+e.message);}
}

// Manual NAV entry ─────────────────────────────────────────────────────────────
async function submitManualNav() {
  const codeEl=document.getElementById('manual-nav-code');
  const dateEl=document.getElementById('manual-nav-date');
  const valEl=document.getElementById('manual-nav-value');
  const st=document.getElementById('manual-nav-status');
  const code=(codeEl?.value||'').trim().toUpperCase();
  const date=dateEl?.value||'';
  const raw=(valEl?.value||'').replace(/[,.]/g,'').trim();
  const nav=parseInt(raw,10);
  if(!code||!date||!nav||nav<=0){
    if(st){st.style.color='var(--sell)';st.textContent='Kiểm tra lại thông tin';}return;
  }
  if(IS_DEV){
    if(st){st.style.color='var(--buy)';st.textContent='✓ DEV: '+code+' '+date+' = '+fmt(nav)+' đ';}
    if(_histPageCode===code) loadHistChart(code);
    return;
  }
  if(st){st.style.color='var(--txt2)';st.textContent='Đang lưu...';}
  const isAdmin=_me?.is_admin;
  const endpoint=isAdmin?'/api/admin/import-nav':'/api/nav/draft';
  try{
    await apiPost(endpoint,{tg_id:String(USER_ID),funds:{[code]:[{date,nav}]}});
    if(st){st.style.color='var(--buy)';st.textContent='✓ Đã lưu NAV '+code+' '+date;}
    if(valEl) valEl.value='';
    if(_histPageCode===code) loadHistChart(code);
  }catch(e){if(st){st.style.color='var(--sell)';st.textContent='Lỗi: '+(e?.body?.error||e.message);}}
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setDcaStyle('dca');
  _refreshGoldProductSelect();
  const td = document.getElementById('trade-date'); if (td) td.value = _todayISO();
  const gd = document.getElementById('gold-date');  if (gd) gd.value  = _todayISO();
  // Add NAV mismatch listeners
  const navInput = document.getElementById('trade-nav-input');
  const tradeDateEl = document.getElementById('trade-date');
  if (navInput) navInput.addEventListener('blur', checkNavMismatch);
  if (tradeDateEl) tradeDateEl.addEventListener('change', checkNavMismatch);
  loadMe();
  loadMarket();
});
