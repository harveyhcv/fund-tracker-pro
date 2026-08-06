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

// HTML-escape utility — dùng cho mọi dữ liệu API trước khi inject vào innerHTML
const esc = s => { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; };

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
let _histNavCache = {};  // code → sorted [{date,nav}] cached per fund for sparklines
let _histFundSort = 'default';  // 'default' | 'score' | 'rsi' | 'm1'
let _lastStrategyHtml = '';  // cached from last renderResearchInline, shown in below-chart
let _histSortByTime = false;   // false=grouped by fund, true=flat time-sorted
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
      {code:'VHIZ',  nav:18450, units:850.5,  avg_cost:15200, cost:12943600, value:15691725, pnl:2748125,  pnl_pct:21.2, chg_pct:0.12,  signal:'MUA MẠNH'},
      {code:'VESAF', nav:22100, units:1200,   avg_cost:19500, cost:23400000, value:26520000, pnl:3120000,  pnl_pct:13.3, chg_pct:-0.05, signal:'MUA'},
      {code:'VCBFTBF',nav:14320,units:2000,  avg_cost:14100, cost:28200000, value:28640000, pnl:440000,   pnl_pct:1.6,  chg_pct:0.08,  signal:'TRUNG LAP'},
      {code:'VFMVF1',nav:31200, units:500,   avg_cost:28000, cost:14000000, value:15600000, pnl:1600000,  pnl_pct:11.4, chg_pct:0.22,  signal:'MUA'},
      {code:'VFMVSF',nav:16800, units:360,   avg_cost:18500, cost:6660000,  value:6048000,  pnl:-612000,  pnl_pct:-9.2, chg_pct:-0.33, signal:'BÁN MẠNH'},
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
  VHIZ:    {nav:18450, chg_pct:0.12,  rsi:38, bb_pct:22, macd:0.03,  score:4,  signal:'MUA MẠNH',  has_position:true},
  VESAF:   {nav:22100, chg_pct:-0.05, rsi:52, bb_pct:48, macd:-0.01, score:2,  signal:'MUA',       has_position:true},
  VCBFTBF: {nav:14320, chg_pct:0.08,  rsi:50, bb_pct:51, macd:0.0,   score:0,  signal:'TRUNG LAP', has_position:true},
  VFMVF1:  {nav:31200, chg_pct:0.22,  rsi:62, bb_pct:67, macd:0.05,  score:3,  signal:'MUA',       has_position:true},
  VFMVSF:  {nav:16800, chg_pct:-0.33, rsi:72, bb_pct:81, macd:-0.04, score:-4, signal:'BÁN MẠNH',  has_position:true},
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
const TAB_TITLES = {home:'TRANG CHỦ', trade:'GIAO DỊCH', history:'PHÂN TÍCH', user:'TÀI KHOẢN'};
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
  if (name === 'home')    {
    if (!_me) loadMe(); if (!_marketData) loadMarket();
    // Return to portfolio overview if re-clicking home while on a fund
    else { _researchCode = null; _showPfIntelligence(); }
  }
  if (name === 'trade')   { if (!_signals) loadSignals(); else renderSignals(_signals); loadUnifiedHistory(); setDcaStyle(_dcaStyle); }
  if (name === 'history') loadHistoryPage();
  if (name === 'user')    loadAccountTab();
}

function _quickTrade(code, type) {
  const navBtn = document.querySelector('.nav-btn[onclick*="trade"]');
  goTab('trade', navBtn);
  setTimeout(() => {
    // Switch to CCQ subtab
    const ccqSubBtn = document.querySelector('[onclick*="order-sub-ccq"]') || document.querySelector('[onclick*="ccq"]');
    // Set buy/sell type
    const typeBtn = document.querySelector(`.type-btn.${type}[onclick*="setTradeType"]`);
    if (typeBtn) { typeBtn.click(); }
    // Pre-select fund
    const sel = document.getElementById('trade-fund-select');
    if (sel && code) { sel.value = code; sel.dispatchEvent(new Event('change')); }
    document.getElementById('order-sub-ccq')?.scrollIntoView({behavior:'smooth',block:'start'});
  }, 350);
}
function showSubtab(page, sub, el) {
  const prefix = {trade:'trade-sub-'}[page];
  if (!prefix) return;
  document.querySelectorAll(`[id^="${prefix}"]`).forEach(d => d.style.display = 'none');
  document.getElementById(prefix+sub).style.display = 'block';
  el.closest('.subtab-bar').querySelectorAll('.subtab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  if (page==='trade' && sub==='signals') { if (!_signals) loadSignals(); else renderSignals(_signals); }
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
    apiFetch(`/api/gold?user_id=${USER_ID}`).then(d=>{if(d?.portfolio?.portfolio!==undefined)d.portfolio=d.portfolio.portfolio;_goldData=d;renderPfBanner();renderPfAlloc();renderPfGoldSub();_renderHistFundList();}).catch(()=>{});
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
  const items=_me?.portfolio?.items||[];
  const goldVal=_goldData?.portfolio?.current_value||0;
  const ccqVal=items.reduce((s,h)=>s+(h.value||0),0);
  const total=ccqVal+goldVal;
  if (!total) return;
  // Chỉ hiện 2 loại: CCQ và Vàng
  const segments=[];
  if (ccqVal>0) segments.push({lbl:'CCQ',val:ccqVal,c:'var(--c0)'});
  if (goldVal>0) segments.push({lbl:'Vàng',val:goldVal,c:'#fbbf24'});
  const trackHtml=segments.map(seg=>`<div style="width:${(seg.val/total*100).toFixed(1)}%;background:${seg.c};height:100%"></div>`).join('');
  const legendHtml=segments.map(seg=>`<span style="color:${seg.c};font-size:10px;font-family:var(--mono)">${seg.lbl} ${(seg.val/total*100).toFixed(0)}%</span>`).join('<span style="color:var(--txt3);margin:0 3px">·</span>');
  document.getElementById('pf-alloc').innerHTML=`<div class="alloc-wrap">
    <div style="font-size:10px;color:var(--txt3);margin-bottom:4px">Phân bổ tài sản</div>
    <div style="height:6px;border-radius:3px;overflow:hidden;display:flex;margin-bottom:6px">${trackHtml}</div>
    <div style="display:flex;flex-wrap:wrap;gap:4px 10px">${legendHtml}</div>
  </div>`;
}

function toggleSumDetail(id, rowEl) {
  const el=document.getElementById(id); if(!el) return;
  const open=el.style.display==='none'; el.style.display=open?'flex':'none';
  rowEl?.querySelector('.sum-chevron')?.classList.toggle('open',open);
}

function _pfT2Summary(items) {
  // Compute weighted-average T+2 prediction across portfolio holdings
  let totalVal=0, weightedPct=0, count=0;
  for (const h of items) {
    const t2=_marketData?.[h.code]?.t2_prediction || _signals?.[h.code]?.t2_prediction;
    if (!t2 || !h.value) continue;
    totalVal+=h.value; weightedPct+=t2.pct*h.value; count++;
  }
  if (!count||!totalVal) return null;
  return {pct: weightedPct/totalVal, count};
}

function _calcPfWeightedPerf(items) {
  const totalVal = items.reduce((s, h) => s + (h.value || 0), 0);
  if (!totalVal) return null;
  let s1d = 0, s30 = 0, s90 = 0, s180 = 0, s1y = 0;
  let n1d = 0, n30 = 0, n90 = 0, n180 = 0, n1y = 0;
  for (const h of items) {
    const v = h.value || 0; if (!v) continue;
    const sig = _marketData?.[h.code] || _signals?.[h.code] || {};
    const wt = v / totalVal;
    if (sig.chg_pct != null) { s1d  += sig.chg_pct * wt;  n1d++;  }
    if (sig.chg30   != null) { s30  += sig.chg30   * wt;  n30++;  }
    if (sig.chg90   != null) { s90  += sig.chg90   * wt;  n90++;  }
    if (sig.chg180  != null) { s180 += sig.chg180  * wt;  n180++; }
    if (sig.chg1y   != null) { s1y  += sig.chg1y   * wt;  n1y++;  }
  }
  return {
    d1:   n1d  ? s1d  : null,
    m1:   n30  ? s30  : null,
    m3:   n90  ? s90  : null,
    m6:   n180 ? s180 : null,
    y1:   n1y  ? s1y  : null,
  };
}

async function _buildPfMiniChart(items, range) {
  if (!items || !items.length) return;
  window._pfLastItems = items;
  const canvasEl = document.getElementById('pf-mini-chart'); if (!canvasEl) return;
  const _range = range || window._pfChartRange || '3M';
  const _limitMap = {'1M':35,'3M':95,'6M':185,'1Y':370,'ALL':9999};
  const _limit = _limitMap[_range] || 95;
  // Update range button styles
  const _pfRangeBtnsEl = document.getElementById('pf-range-btns');
  if (_pfRangeBtnsEl) {
    _pfRangeBtnsEl.querySelectorAll('button').forEach(btn => {
      const _btnRange = {'1T':'1M','3T':'3M','6T':'6M','1N':'1Y','Tất cả':'ALL'}[btn.textContent] || btn.textContent;
      btn.style.background = _btnRange === _range ? 'var(--c0)' : 'var(--bg3)';
      btn.style.color = _btnRange === _range ? '#000' : 'var(--txt2)';
    });
    window._pfChartRange = _range;
  }
  const results = (await Promise.all(items.map(h =>
    apiFetch(`/api/nav_history/${h.code}?limit=${_limit}`)
      .then(d => ({ code:h.code, units:h.units, navs:(d.history||[]).slice().reverse() }))
      .catch(()=>null)
  ))).filter(Boolean);
  if (!results.length) return;
  // Build date union, sorted ascending
  const allDates = [...new Set(results.flatMap(r=>r.navs.map(p=>p.date)))].sort();
  const navMapArr = {};
  for (const r of results) navMapArr[r.code] = r.navs.sort((a,b)=>a.date<b.date?-1:1);
  function _navAt(code, date) {
    let v=null;
    for (const p of navMapArr[code]||[]) { if (p.date<=date) v=p.nav; else break; }
    return v;
  }
  const values = allDates.map(date => {
    let total=0;
    for (const r of results) { const n=_navAt(r.code,date); if(n) total+=r.units*n; }
    return total;
  });
  if (values.filter(v=>v>0).length < 2) return;
  // Hiện date range
  const fmtD = d => d ? d.slice(5).replace('-','/') : '';
  const drEl = document.getElementById('pf-chart-daterange');
  if (drEl && allDates.length) drEl.textContent = `${fmtD(allDates[0])} — ${fmtD(allDates[allDates.length-1])}`;
  if (window._pfMiniChartInst) { window._pfMiniChartInst.destroy(); window._pfMiniChartInst=null; }
  window._pfMiniChartInst = new Chart(canvasEl.getContext('2d'), {
    type:'line',
    data:{ labels:allDates, datasets:[{
      data:values, borderColor:'var(--c0)', backgroundColor:'rgba(0,229,255,0.07)',
      fill:true, borderWidth:1.5, pointRadius:0, tension:0.3
    }]},
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{legend:{display:false}, tooltip:{callbacks:{
        title:items=>`${fmtD(items[0].label)}`,
        label:c=>`${(c.raw/1e6).toFixed(2)}M đ`
      }}},
      scales:{
        x:{display:false},
        y:{grid:{color:'rgba(255,255,255,0.04)'}, border:{display:false},
           ticks:{color:'rgba(255,255,255,0.4)',font:{size:8,family:'IBM Plex Mono'},
                  callback:v=>`${(v/1e6).toFixed(0)}M`,maxTicksLimit:3}}
      }
    }
  });
}
function renderPortfolio(me) {
  renderPfBanner(); renderPfAlloc();
  const pf=me.portfolio;
  let html='';
  if (!pf.items.length) {
    html=`<div class="card" style="text-align:center;color:var(--txt2);padding:24px">Chưa có giao dịch CCQ.<br>Thêm ở tab Giao Dịch.</div>`;
  } else {
    // Portfolio mini chart (value curve with range selector)
    if (!window._pfChartRange) window._pfChartRange = '3M';
    const _pfRangeBtns = ['1T','3T','6T','1N','Tất cả'].map((lbl,i) => {
      const val = ['1M','3M','6M','1Y','ALL'][i];
      return `<button onclick="window._pfChartRange='${val}';_buildPfMiniChart(window._pfLastItems,'${val}')" style="font-size:9px;font-family:var(--mono);background:${window._pfChartRange===val?'var(--c0)':'var(--bg3)'};color:${window._pfChartRange===val?'#000':'var(--txt2)'};border:none;border-radius:3px;padding:2px 6px;cursor:pointer;transition:all .15s">${lbl}</button>`;
    }).join('');
    html+=`<div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:8px;padding:10px 12px;margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <span style="font-size:10px;color:var(--txt3)">Giá trị danh mục</span>
        <div id="pf-range-btns" style="display:flex;gap:3px">${_pfRangeBtns}</div>
      </div>
      <div style="height:70px;position:relative"><canvas id="pf-mini-chart"></canvas></div>
      <div style="text-align:right"><span id="pf-chart-daterange" style="font-size:9px;color:var(--txt3);font-family:var(--mono)"></span></div>
    </div>`;
    // Portfolio weighted performance card
    const pfPerf = _calcPfWeightedPerf(pf.items);
    if (pfPerf && (pfPerf.m1 != null || pfPerf.m3 != null)) {
      const _pc = v => v == null
        ? '<span style="color:var(--txt3)">—</span>'
        : `<span style="font-family:var(--mono);font-weight:700;color:${v>=0?'var(--buy)':'var(--sell)'}">${v>=0?'+':''}${v.toFixed(2)}%</span>`;
      html+=`<div style="background:var(--bg2);border:1px solid var(--bdr);border-radius:8px;padding:10px 12px;margin-bottom:8px">
        <div style="font-size:10px;color:var(--txt3);margin-bottom:8px">Hiệu suất danh mục (bình quân theo giá trị)</div>
        <div style="display:grid;grid-template-columns:repeat(${[pfPerf.d1,pfPerf.m1,pfPerf.m3,pfPerf.m6,pfPerf.y1].filter(v=>v!=null).length},1fr);gap:8px;text-align:center">
          ${pfPerf.d1!=null?`<div><div style="font-size:9px;color:var(--txt3)">Hôm nay</div>${_pc(pfPerf.d1)}</div>`:''}
          ${pfPerf.m1!=null?`<div><div style="font-size:9px;color:var(--txt3)">1 tháng</div>${_pc(pfPerf.m1)}</div>`:''}
          ${pfPerf.m3!=null?`<div><div style="font-size:9px;color:var(--txt3)">3 tháng</div>${_pc(pfPerf.m3)}</div>`:''}
          ${pfPerf.m6!=null?`<div><div style="font-size:9px;color:var(--txt3)">6 tháng</div>${_pc(pfPerf.m6)}</div>`:''}
          ${pfPerf.y1!=null?`<div><div style="font-size:9px;color:var(--txt3)">1 năm</div>${_pc(pfPerf.y1)}</div>`:''}
        </div>
      </div>`;
    }
    // Portfolio Intelligence → rendered in center column via _showPfIntelligence()
    // (triggered after this render + after market data loads)

    html+='<div class="card">';
    const _todayStr = new Date().toISOString().slice(0,10);
    for (const h of pf.items) {
      const chg=h.chg_pct||0;
      const navSrc = h.nav_source || '';
      const navBadgeTxt = navSrc==='provisional'?'est':navSrc==='pending_confirm'?'pend':navSrc==='confirmed'?'conf':navSrc==='fixed'?'fix':navSrc==='manual'?'man':'';
      const navBadgeCol = (navSrc==='confirmed'||navSrc==='fixed')?'var(--buy)':navSrc==='pending_confirm'?'#fbbf24':'var(--txt2)';
      const navBadge = navBadgeTxt ? `<span style="font-size:9px;color:${navBadgeCol};border:1px solid ${navBadgeCol};border-radius:3px;padding:0 3px;margin-left:4px;font-family:var(--mono)">${navBadgeTxt}</span>` : '';
      const t2=_marketData?.[h.code]?.t2_prediction || _signals?.[h.code]?.t2_prediction;
      const t2html = t2 ? `<span style="font-size:9px;font-family:var(--mono);color:${t2.pct>=0?'var(--buy)':'var(--sell)'};margin-left:4px" title="Dự báo T+2">T+2 ${t2.pct>=0?'+':''}${t2.pct.toFixed(2)}%</span>` : '';
      const _nd = (_marketData||_signals||{})?.[h.code]?.nav_date;
      const _fmtFullDate = d => { const p=d.split('-'); return `${p[2]}/${p[1]}/${p[0]}`; };
      const _staleBadge = (_nd && _nd !== _todayStr) ? `<div style="margin-top:3px"><span style="font-size:10px;color:#f59e0b;font-family:var(--mono);padding:2px 7px;border:1px solid #f59e0b55;border-radius:4px;background:#f59e0b15;white-space:nowrap" title="Hệ thống chưa cập nhật NAV ngày hôm nay — đây là NAV từ ngày ${_fmtFullDate(_nd)}">📅 NAV ${_fmtFullDate(_nd)}</span></div>` : '';
      html+=`<div class="fund-row" onclick="openResearch('${h.code}')">
        <div class="fund-info">
          <div class="fund-top">
            <span class="fund-code">${h.code}</span>
            <span class="fund-nav">${fmt(h.nav)} đ${navBadge}</span>
            <span class="pnl ${pnlC(chg)}" style="font-size:11px">${fmtP(chg)}</span>
          </div>
          <div class="fund-sub"><span>${fmt(h.units)} CCQ</span><span style="opacity:.4">&middot;</span><span>Giá vốn ${fmt(h.avg_cost)} đ</span>${t2html}</div>
          ${_staleBadge}
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
  if (pf.items.length) setTimeout(() => _buildPfMiniChart(pf.items), 150);
  setTimeout(_showPfIntelligence, 50);
}

function _pfIntelCompactHtml() {
  const pf = _me?.portfolio;
  if (!pf?.items?.length) return '';
  const sigs = _marketData || _signals || {};
  const total = pf.total_value || 0;
  const pnlAmt = pf.items.reduce((s,h)=>s+(h.pnl_amount||0),0);
  const pnlPct = total > pnlAmt ? pnlAmt / (total - pnlAmt) * 100 : 0;
  const pfPerf = _calcPfWeightedPerf(pf.items);
  const m1 = pfPerf?.m1, m3 = pfPerf?.m3;
  const pnlC2 = v => v>=0?'var(--buy)':'var(--sell)';
  // Key alert
  const pfConc = pf.items.map(h=>({code:h.code,pct:total>0?h.value/total*100:0,rsi:sigs[h.code]?.rsi}));
  const maxC = pfConc.reduce((mx,c)=>c.pct>mx.pct?c:mx,{pct:0,code:''});
  const oversold = [...pfConc].filter(c=>c.rsi!=null).sort((a,b)=>a.rsi-b.rsi)[0];
  let alertStr = '';
  if (maxC.pct>40) alertStr=`⚠ ${maxC.code} ${maxC.pct.toFixed(0)}% danh mục`;
  else if (oversold&&oversold.rsi<32) alertStr=`💡 ${oversold.code} RSI ${oversold.rsi.toFixed(0)} quá bán`;
  return `<details id="pf-intel-mini" style="background:var(--bg2);border-bottom:1px solid var(--bdr);flex-shrink:0">
    <summary style="padding:9px 14px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;list-style:none;user-select:none">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0">
        <span style="font-family:var(--mono);font-size:10px;color:var(--txt3);letter-spacing:.05em;flex-shrink:0">DANH MỤC</span>
        <span style="font-family:var(--mono);font-size:12px;font-weight:700;color:${pnlC2(pnlAmt)}">${pnlAmt>=0?'+':''}${(pnlAmt/1e6).toFixed(2)}M (${pnlPct>=0?'+':''}${pnlPct.toFixed(1)}%)</span>
        ${m1!=null?`<span style="font-size:11px;color:${pnlC2(m1)};font-family:var(--mono)">${m1>=0?'+':''}${m1.toFixed(1)}% 1T</span>`:''}
        ${m3!=null?`<span style="font-size:11px;color:${pnlC2(m3)};font-family:var(--mono)">${m3>=0?'+':''}${m3.toFixed(1)}% 3T</span>`:''}
        ${alertStr?`<span style="font-size:10px;color:#f59e0b">${alertStr}</span>`:''}
      </div>
      <span style="font-size:9px;color:var(--txt3);flex-shrink:0;margin-left:8px">▼</span>
    </summary>
    <div style="padding:10px 14px 12px;border-top:1px solid var(--bdr)">
      ${pf.items.map(h=>{
        const pnlP=h.pnl_pct||0;
        return `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;font-size:11px">
          <span style="font-family:var(--mono);color:var(--txt1);cursor:pointer;text-decoration:underline;text-underline-offset:2px;text-decoration-color:var(--bdr)" onclick="_selectHistFund('${h.code}')">${h.code}</span>
          <span style="font-family:var(--mono);color:${pnlC2(pnlP)}">${pnlP>=0?'+':''}${pnlP.toFixed(1)}%</span>
        </div>`;
      }).join('')}
      <div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--bdr);font-size:10px;color:var(--c0);cursor:pointer;text-align:center" onclick="_researchCode=null;_showPfIntelligence()">Xem phân tích đầy đủ →</div>
    </div>
  </details>`;
}

function _populateHomepiStrip() {
  const piStrip = document.getElementById('home-pi-strip');
  if (!piStrip) return;
  const pf = _me?.portfolio;
  if (!pf?.items?.length) { piStrip.style.display = 'none'; return; }
  const total = pf.total_value || 0;
  const cost = pf.items.reduce((s,h)=>s+(h.cost||0),0);
  const pnl = total - cost;
  const pnlP = cost > 0 ? pnl/cost*100 : 0;
  const c = pnlP >= 0 ? 'var(--buy)' : 'var(--sell)';
  const isResearch = !!_researchCode;
  piStrip.style.display = '';
  piStrip.innerHTML = `<div style="display:flex;align-items:center;gap:14px;padding:10px 16px;cursor:${isResearch?'pointer':'default'};flex-wrap:wrap" ${isResearch?`onclick="_researchCode=null;_showPfIntelligence()" title="Quay về tổng quan danh mục"`:''}>
    ${isResearch ? `<span style="font-size:10px;font-family:var(--mono);color:var(--c0);letter-spacing:.06em;flex-shrink:0">← DANH MỤC</span>` : `<span style="font-size:10px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;flex-shrink:0">DANH MỤC</span>`}
    <span style="font-family:var(--mono);font-size:16px;font-weight:700;color:${c}">${pnlP>=0?'+':''}${pnlP.toFixed(2)}%</span>
    <span style="font-size:13px;font-family:var(--mono);color:${c}">${pnl>=0?'+':''}${(pnl/1e6).toFixed(2)}M đ</span>
    <span style="margin-left:auto;font-size:11px;color:var(--txt2)">${pf.items.length} quỹ · ${(total/1e6).toFixed(1)}M đ</span>
  </div>`;
}

function _showPfIntelligence() {
  if (_researchCode) return;
  const pf = _me?.portfolio;
  if (!pf?.items?.length) return;
  _populateHomepiStrip();
  const el = document.getElementById('chart-col-content');
  if (!el) return;
  const titleEl = document.getElementById('chart-col-title');
  const subEl = document.getElementById('chart-col-sub');
  if (titleEl) titleEl.textContent = 'PHÂN TÍCH DANH MỤC';
  if (subEl) subEl.textContent = `${pf.items.length} quỹ đang nắm`;
  const sigs = _marketData || _signals || {};
  const total = pf.total_value || 0;
  const hasSignals = Object.keys(sigs).length > 0;
  const ts = new Date();
  const tsFmt = `${ts.getHours().toString().padStart(2,'0')}:${ts.getMinutes().toString().padStart(2,'0')} ${ts.getDate().toString().padStart(2,'0')}/${(ts.getMonth()+1).toString().padStart(2,'0')}/${ts.getFullYear()}`;
  // Weighted perf
  const pfPerf = _calcPfWeightedPerf(pf.items);
  const _pc = v => v == null ? '<span style="color:var(--txt3)">—</span>'
    : `<span style="font-family:var(--mono);font-weight:700;font-size:15px;color:${v>=0?'var(--buy)':'var(--sell)'}">${v>=0?'+':''}${v.toFixed(2)}%</span>`;
  const perfCols = [
    pfPerf?.d1!=null?{lbl:'Hôm nay',v:pfPerf.d1}:null,
    pfPerf?.m1!=null?{lbl:'1 tháng',v:pfPerf.m1}:null,
    pfPerf?.m3!=null?{lbl:'3 tháng',v:pfPerf.m3}:null,
    pfPerf?.m6!=null?{lbl:'6 tháng',v:pfPerf.m6}:null,
    pfPerf?.y1!=null?{lbl:'1 năm',v:pfPerf.y1}:null,
  ].filter(Boolean);
  // Concentration
  const pfConc = pf.items.map(h => ({
    code:h.code, pct:total>0?h.value/total*100:0,
    rsi:sigs[h.code]?.rsi, chg30:sigs[h.code]?.chg30, pnl_pct:h.pnl_pct||0,
  }));
  const topConc = [...pfConc].sort((a,b)=>b.pct-a.pct);
  const concBarsHtml = topConc.map(c => {
    const barC = c.pct>40?'var(--sell)':c.pct>28?'#facc15':'var(--c0)';
    return `<div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px">
        <span style="font-family:var(--mono);font-weight:600;color:var(--txt1);cursor:pointer;text-decoration:underline;text-underline-offset:2px;text-decoration-color:var(--bdr)" onclick="openResearch('${c.code}')">${c.code}</span>
        <span style="font-family:var(--mono);color:${barC}">${c.pct.toFixed(1)}%</span>
      </div>
      <div style="height:6px;background:var(--bdr);border-radius:4px;overflow:hidden">
        <div style="height:100%;width:${Math.min(c.pct,100).toFixed(1)}%;background:${barC};border-radius:4px"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:9px;color:var(--txt3);margin-top:2px">
        <span class="pnl ${pnlC(c.pnl_pct)}" style="font-size:9px">${c.pnl_pct>=0?'+':''}${c.pnl_pct.toFixed(1)}% P&L</span>
        ${c.rsi!=null?`<span>RSI ${c.rsi.toFixed(0)}</span>`:''}
      </div>
    </div>`;
  }).join('');
  // Alerts
  const maxConc = pfConc.reduce((mx,c)=>c.pct>mx.pct?c:mx,{pct:0,code:''});
  const mostOversold = [...pfConc].filter(c=>c.rsi!=null).sort((a,b)=>a.rsi-b.rsi)[0];
  const worst30 = [...pfConc].filter(c=>c.chg30!=null).sort((a,b)=>a.chg30-b.chg30)[0];
  const best30 = [...pfConc].filter(c=>c.chg30!=null).sort((a,b)=>b.chg30-a.chg30)[0];
  const alerts=[];
  if (maxConc.pct>40) alerts.push({icon:'⚠️',color:'#facc15',text:`<b>${maxConc.code}</b> chiếm <b>${maxConc.pct.toFixed(0)}%</b> danh mục — rủi ro tập trung cao`});
  if (mostOversold&&mostOversold.rsi<30) alerts.push({icon:'💡',color:'var(--buy)',text:`<b>${mostOversold.code}</b> RSI <b>${mostOversold.rsi.toFixed(0)}</b> — vùng quá bán mạnh, cơ hội tích lũy tốt`});
  else if (mostOversold&&mostOversold.rsi<40) alerts.push({icon:'📊',color:'var(--c0)',text:`<b>${mostOversold.code}</b> RSI <b>${mostOversold.rsi.toFixed(0)}</b> — tiệm cận vùng quá bán, theo dõi thêm`});
  if (worst30&&worst30.chg30<-10) alerts.push({icon:'📉',color:'var(--sell)',text:`<b>${worst30.code}</b> giảm <b>${Math.abs(worst30.chg30).toFixed(1)}%</b> trong 1 tháng — xem xét tái cân bằng`});
  if (best30&&best30.chg30>8&&best30.code!==worst30?.code) alerts.push({icon:'🚀',color:'var(--buy)',text:`<b>${best30.code}</b> tăng <b>+${best30.chg30.toFixed(1)}%</b> trong 1 tháng — đang dẫn đầu danh mục`});
  if (!alerts.length) alerts.push({icon:'✅',color:'var(--buy)',text:'Danh mục ổn định — không có cảnh báo nào cần chú ý'});
  const alertsHtml = alerts.map(a=>`<div style="display:flex;gap:10px;align-items:flex-start;padding:10px 12px;background:var(--bg3);border-radius:8px;border-left:3px solid ${a.color}">
    <span style="font-size:16px;line-height:1.2;flex-shrink:0">${a.icon}</span>
    <span style="font-size:11px;color:var(--txt1);line-height:1.6">${a.text}</span>
  </div>`).join('');
  const perfHtml = perfCols.length ? `<div style="display:grid;grid-template-columns:repeat(${perfCols.length},1fr);gap:6px;text-align:center;margin-bottom:20px">
    ${perfCols.map(p=>`<div style="background:var(--bg3);border-radius:8px;padding:10px 4px">
      <div style="font-size:9px;color:var(--txt3);margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em">${p.lbl}</div>
      ${_pc(p.v)}
    </div>`).join('')}
  </div>` : '';
  el.innerHTML=`<div style="padding:20px;overflow-y:auto;height:100%;box-sizing:border-box">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <div style="font-size:10px;font-family:var(--mono);color:var(--txt3);letter-spacing:.1em;text-transform:uppercase">Phân tích danh mục</div>
      <div style="font-size:9px;color:${hasSignals?'var(--txt3)':'var(--sell)'}">
        ${hasSignals?`🕐 Dữ liệu: ${tsFmt}`:'⚠ Chưa có dữ liệu thị trường'}
      </div>
    </div>
    ${perfHtml}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start">
      <div>
        <div style="font-size:9px;color:var(--txt3);font-family:var(--mono);letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px">Tỷ trọng danh mục</div>
        ${concBarsHtml}
      </div>
      <div>
        <div style="font-size:9px;color:var(--txt3);font-family:var(--mono);letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px">Cảnh báo & gợi ý</div>
        <div style="display:flex;flex-direction:column;gap:6px">${alertsHtml}</div>
      </div>
    </div>
    <div style="margin-top:20px;padding-top:14px;border-top:1px solid var(--bdr);text-align:center;color:var(--txt3);font-size:11px">
      Nhấn vào tên quỹ ở trên hoặc bất kỳ quỹ nào trong danh sách để xem biểu đồ NAV &amp; phân tích kỹ thuật
    </div>
  </div>`;
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
    // Re-render portfolio now that market data (chg30/chg90/t2_prediction) is available
    if (_me) renderPortfolio(_me);
  } catch(e) { document.getElementById('market-content').innerHTML=renderErr('Lỗi tải thị trường: '+e.message); }
}

let _marketBulkMode = false;
let _marketBulkSet = new Set();
function _toggleMarketBulkMode() {
  _marketBulkMode = !_marketBulkMode;
  if (!_marketBulkMode) _marketBulkSet.clear();
  const btn = document.getElementById('market-bulk-toggle');
  if (btn) { btn.classList.toggle('active', _marketBulkMode); btn.innerHTML = _marketBulkMode ? '&#x2715; Huỷ chọn' : '&#x2611; Chọn nhiều'; }
  const bar = document.getElementById('market-bulk-bar');
  if (bar) bar.style.display = _marketBulkMode ? 'flex' : 'none';
  renderMarket();
}
function _toggleBulkPick(code, e) {
  if (e) e.stopPropagation();
  if (_marketBulkSet.has(code)) _marketBulkSet.delete(code); else _marketBulkSet.add(code);
  const cnt = document.getElementById('market-bulk-count');
  if (cnt) cnt.textContent = `Đã chọn ${_marketBulkSet.size} quỹ`;
  const box = document.querySelector(`[data-code="${code}"] .bulk-check`);
  if (box) box.classList.toggle('on', _marketBulkSet.has(code));
}
async function _bulkAddWatch() {
  if (!_marketBulkSet.size) { toast('Chưa chọn quỹ nào'); return; }
  const existing = new Set(_me?.watched_funds || []);
  _marketBulkSet.forEach(c => existing.add(c));
  const list = [...existing];
  const n = _marketBulkSet.size;
  if (_me) _me.watched_funds = list;
  if (IS_DEV) { toast(`✓ DEV: Đã thêm ${n} quỹ vào theo dõi`); _toggleMarketBulkMode(); return; }
  try {
    await apiPost('/api/me/watched_funds', {telegram_id: USER_ID, watched_funds: list});
    toast(`✓ Đã thêm ${n} quỹ vào danh sách theo dõi`);
  } catch(e) { toast('Lỗi: '+(e.body?.error||e.message)); }
  _toggleMarketBulkMode();
  renderMarket();
}
function renderMarket() {
  if (!_marketData) return;
  const search=(document.getElementById('market-search').value||'').toUpperCase();
  // Compute breadth counts for filter button labels
  const allCodes = Object.keys(_marketData);
  const nBuyM = allCodes.filter(c=>sigC(_marketData[c].signal)==='buy').length;
  const nSellM = allCodes.filter(c=>sigC(_marketData[c].signal)==='sell').length;
  const nHoldM = allCodes.length - nBuyM - nSellM;
  const nHeld = allCodes.filter(c=>_marketData[c].has_position).length;
  const btnLabels = {all:`Tất cả (${allCodes.length})`,buy:`MUA (${nBuyM})`,sell:`BÁN (${nSellM})`,hold:`TRUNG LẬP (${nHoldM})`,held:`Đang nắm (${nHeld})`};
  document.querySelectorAll('.filter-btn').forEach(btn=>{
    const m=btn.getAttribute('onclick')?.match(/setMarketFilter\('(\w+)'/);
    if(m && btnLabels[m[1]]) btn.textContent=btnLabels[m[1]];
  });
  const codes=Object.keys(_marketData).filter(code=>{
    if (search && !code.includes(search)) return false;
    const s=_marketData[code]; const sc=sigC(s.signal);
    if (_marketFilter==='buy') return sc==='buy';
    if (_marketFilter==='sell') return sc==='sell';
    if (_marketFilter==='hold') return sc==='hold';
    if (_marketFilter==='held') return s.has_position;
    return true;
  }).sort((a,b)=>{
    // Held funds always first, then sort by signal score descending
    const sa=_marketData[a], sb=_marketData[b];
    if (sa.has_position && !sb.has_position) return -1;
    if (!sa.has_position && sb.has_position) return 1;
    return (sb.score||0)-(sa.score||0);
  });
  if (!codes.length) { document.getElementById('market-content').innerHTML='<div style="text-align:center;color:var(--txt2);padding:20px">Không có quỹ nào.</div>'; return; }
  const _mktTodayStr = new Date().toISOString().slice(0,10);
  const _fmtMktDate = d => { const p=d.split('-'); return `${p[2]}/${p[1]}/${p[0]}`; };
  let html='<div class="card">';
  for (const code of codes) {
    const s=_marketData[code];
    const rsi=s.rsi??50, bb=s.bb_pct??50, chg=s.chg_pct||0;
    const rsiC=rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--hold)';
    const bbC=bb<20?'var(--buy)':bb>80?'var(--sell)':'var(--hold)';
    const alertIcon = (s.data_stale||s.nav_stale||s.alert||s.nav_jump_anomaly)
      ? `<span title="${s.alert||'Dữ liệu hoặc NAV có thể chưa cập nhật'}" style="color:#facc15;font-size:9px;line-height:1">⚠</span>` : '';
    const isWatched = (_me?.watched_funds||[]).includes(code);
    const ftBorderColor = {equity:'var(--buy)',bond:'#60a5fa',balanced:'#a78bfa',money_market:'#facc15'}[s.fund_type||'equity']||'var(--c0)';
    const bulkCheckHtml = _marketBulkMode
      ? `<span class="bulk-check${_marketBulkSet.has(code)?' on':''}" onclick="event.stopPropagation();_toggleBulkPick('${code}',event)" style="cursor:pointer;width:15px;height:15px;border:1px solid var(--c0);border-radius:3px;display:inline-flex;align-items:center;justify-content:center;font-size:10px;color:var(--bg);background:${_marketBulkSet.has(code)?'var(--c0)':'transparent'};flex-shrink:0">${_marketBulkSet.has(code)?'✓':''}</span>` : '';
    html+=`<div class="sig-row" onclick="${_marketBulkMode?`_toggleBulkPick('${code}',event)`:`openResearch('${code}')`}" data-code="${code}" style="border-left:2px solid ${ftBorderColor}">
      <div>
        <div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap">
          ${bulkCheckHtml}
          <span class="sig-code">${code}</span>
          <span class="pnl ${pnlC(chg)}" style="font-size:11px">${fmtP(chg)}</span>
          ${s.has_position?'<span style="font-size:9px;color:var(--c0);font-family:var(--mono)">&#x2022;NẮM</span>':''}
          ${alertIcon}
        </div>
        <div style="display:flex;align-items:center;gap:6px;margin-top:2px;flex-wrap:wrap">
          <span style="font-size:11px;color:var(--txt2)">${fmt(s.nav)} đ</span>
          ${(s.nav_date && s.nav_date !== _mktTodayStr) ? `<span style="font-size:9px;color:#f59e0b;font-family:var(--mono);padding:1px 5px;border:1px solid #f59e0b55;border-radius:3px;background:#f59e0b15;white-space:nowrap" title="NAV từ ngày ${s.nav_date}">📅 ${_fmtMktDate(s.nav_date)}</span>` : ''}
        </div>
      </div>
      <div class="sig-meters">
        <div class="meter"><div class="meter-lbl">RSI</div><div class="meter-bar"><div class="meter-fill" style="width:${rsi}%;background:${rsiC}"></div></div><div class="meter-val">${rsi.toFixed?rsi.toFixed(0):rsi}</div></div>
        <div class="meter"><div class="meter-lbl">BB%</div><div class="meter-bar"><div class="meter-fill" style="width:${bb}%;background:${bbC}"></div></div><div class="meter-val">${bb.toFixed?bb.toFixed(0):bb}</div></div>
        <div class="meter"><div class="meter-lbl">SCR</div><div class="meter-val" style="font-size:11px;color:${(s.score||0)>=3?'var(--buy)':(s.score||0)<=-3?'var(--sell)':'var(--txt)'}">${(s.score>=0?'+':'')}${s.score||0}</div></div>
      </div>
      <div style="text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:3px">
        <div class="badge ${sigC(s.signal)}">${sigLabel(s.signal)}</div>
        ${s.t2_prediction ? `<span style="font-size:9px;font-family:var(--mono);color:${s.t2_prediction.pct>=0?'var(--buy)':'var(--sell)'}" title="Dự báo T+2">T+2 ${s.t2_prediction.pct>=0?'+':''}${s.t2_prediction.pct.toFixed(2)}%</span>` : ''}
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
  // Sort by score descending — strongest buy signals first
  codes.sort((a,b)=>(watched[b].score||0)-(watched[a].score||0));
  // Summary header
  const nBuy=codes.filter(c=>(watched[c].score||0)>=3).length;
  const nSell=codes.filter(c=>(watched[c].score||0)<=-3).length;
  const nNeutral=codes.length-nBuy-nSell;
  const summaryHtml=`<div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap">
    ${nBuy?`<span style="font-size:11px;background:#4ade8022;color:var(--buy);border:1px solid #4ade8044;border-radius:5px;padding:3px 10px;font-family:var(--mono)">● ${nBuy} MUA</span>`:''}
    ${nNeutral?`<span style="font-size:11px;background:#facc1522;color:#facc15;border:1px solid #facc1544;border-radius:5px;padding:3px 10px;font-family:var(--mono)">● ${nNeutral} TRUNG LẬP</span>`:''}
    ${nSell?`<span style="font-size:11px;background:#f8717122;color:var(--sell);border:1px solid #f8717144;border-radius:5px;padding:3px 10px;font-family:var(--mono)">● ${nSell} BÁN</span>`:''}
  </div>`;
  let html=summaryHtml+'<div style="display:flex;flex-direction:column;gap:10px">';
  for (const code of codes) {
    const s=sigs[code];
    const rsi=s.rsi??50, bb=s.bb_pct??50, macdH=s.macd_hist??0, chg=s.chg_pct||0, sc=s.score||0;
    const scC=sc>=3?'var(--buy)':sc<=-3?'var(--sell)':'#facc15';
    const sigFtColor={equity:'var(--buy)',bond:'#60a5fa',balanced:'#a78bfa',money_market:'#facc15'}[s.fund_type||'equity']||'var(--c0)';
    const sigFtLabel={equity:'Quỹ CP',bond:'Quỹ TP',balanced:'Quỹ CB',money_market:'Tiền tệ'}[s.fund_type||'equity']||'Quỹ mở';
    const t2=s.t2_prediction;
    const details=Array.isArray(s.details)?s.details:[];
    // RSI interpretation
    const rsiInterp=rsi<25?{txt:'Quá bán mạnh',c:'var(--buy)'}:rsi<40?{txt:'Vùng bán',c:'var(--buy)'}:rsi<60?{txt:'Trung tính',c:'var(--txt2)'}:rsi<75?{txt:'Vùng mua',c:'var(--sell)'}:{txt:'Quá mua',c:'var(--sell)'};
    // BB% interpretation
    const bbInterp=bb<15?{txt:'Gần đáy BB',c:'var(--buy)'}:bb<35?{txt:'Vùng thấp',c:'var(--buy)'}:bb<65?{txt:'Trung tính',c:'var(--txt2)'}:bb<85?{txt:'Vùng cao',c:'var(--sell)'}:{txt:'Sát đỉnh BB',c:'var(--sell)'};
    // MACD histogram bar (normalized to ±100 from NAV)
    const macdPct=s.nav>0?Math.min(Math.abs(macdH)/s.nav*100*20,50):Math.min(Math.abs(macdH)/100,50);
    const macdC=macdH>=0?'var(--buy)':'var(--sell)';
    const macdInterp=macdH>0?{txt:'Đà tăng',c:'var(--buy)'}:macdH<0?{txt:'Đà giảm',c:'var(--sell)'}:{txt:'Trung tính',c:'var(--txt2)'};
    // Score bar (−6 to +6, mapped to 0..100%)
    const scoreBarPct=Math.abs(sc)/6*50; // 0..50
    // Performance trend from chg7/chg30
    const chg7=s.chg7||0; const chg30=s.chg30||0;
    // Compute signal strength label
    const strengthLabel=Math.abs(sc)>=5?'Rất mạnh':Math.abs(sc)>=3?'Mạnh':Math.abs(sc)>=1?'Vừa':'Trung lập';
    html+=`<div style="background:var(--bg2);border-radius:12px;overflow:hidden;border:1px solid var(--bdr);cursor:pointer" onclick="openResearch('${code}')">
      <!-- Header row -->
      <div style="padding:12px 14px 8px;border-bottom:1px solid var(--bdr)${sc>=3?';border-left:3px solid var(--buy)':sc<=-3?';border-left:3px solid var(--sell)':';border-left:3px solid '+sigFtColor}">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
          <div style="flex:1;min-width:0">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <span style="font-family:var(--mono);font-size:15px;font-weight:700;color:var(--c0)">${code}</span>
              <span style="font-size:9px;padding:2px 7px;border-radius:4px;border:1px solid ${sigFtColor}44;color:${sigFtColor};font-family:var(--mono)">${sigFtLabel}</span>
            </div>
            <div style="margin-top:3px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <span style="font-family:var(--mono);font-size:13px;font-weight:600;color:var(--txt1)">${fmt(s.nav)} đ</span>
              <span class="pnl ${pnlC(chg)}" style="font-size:11px;font-family:var(--mono)">${fmtP(chg)}</span>
              ${s.chg7!=null?`<span style="font-size:9px;color:${chg7>=0?'var(--buy)':'var(--sell)'};font-family:var(--mono)">7N:${chg7>=0?'+':''}${chg7.toFixed(1)}%</span>`:''}
              ${s.chg30!=null?`<span style="font-size:9px;color:${chg30>=0?'var(--buy)':'var(--sell)'};font-family:var(--mono)">1T:${chg30>=0?'+':''}${chg30.toFixed(1)}%</span>`:''}
            </div>
          </div>
          <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">
            <div class="badge ${sigC(s.signal)}" style="font-size:11px;padding:4px 10px">${sigLabel(s.signal)}</div>
            <div style="display:flex;align-items:center;gap:4px">
              <span style="font-family:var(--mono);font-size:12px;font-weight:700;color:${scC}">${sc>0?'+':''}${sc}</span>
              <span style="font-size:9px;color:var(--txt3)">${strengthLabel}</span>
            </div>
          </div>
        </div>
        <!-- Score bar -->
        <div style="margin-top:8px">
          <div style="height:3px;background:var(--bdr);border-radius:2px;position:relative">
            <div style="position:absolute;${sc>=0?'left:50%':'right:50%'};width:${scoreBarPct}%;height:100%;background:${scC};border-radius:2px"></div>
            <div style="position:absolute;left:50%;transform:translateX(-50%);width:1px;height:100%;background:var(--txt3)"></div>
          </div>
          <div style="display:flex;justify-content:space-between;font-size:8px;color:var(--txt3);margin-top:2px"><span>BÁN −6</span><span>TRUNG LẬP 0</span><span>MUA +6</span></div>
        </div>
      </div>
      <!-- Compact indicator row: RSI | BB | MACD in one line -->
      <div style="display:flex;align-items:center;gap:0;border-bottom:1px solid var(--bdr);padding:7px 14px;background:var(--bg3)">
        <span style="font-size:11px;color:var(--txt3);font-family:var(--mono);margin-right:4px">RSI</span>
        <span style="font-family:var(--mono);font-size:13px;font-weight:700;color:${rsiInterp.c};margin-right:3px">${rsi.toFixed(0)}</span>
        <span style="font-size:10px;color:${rsiInterp.c};margin-right:12px">${rsiInterp.txt}</span>
        <span style="color:var(--bdr);margin-right:12px">│</span>
        <span style="font-size:11px;color:var(--txt3);font-family:var(--mono);margin-right:4px">BB</span>
        <span style="font-family:var(--mono);font-size:13px;font-weight:700;color:${bbInterp.c};margin-right:3px">${bb.toFixed(0)}%</span>
        <span style="font-size:10px;color:${bbInterp.c};margin-right:12px">${bbInterp.txt}</span>
        <span style="color:var(--bdr);margin-right:12px">│</span>
        <span style="font-size:11px;color:var(--txt3);font-family:var(--mono);margin-right:4px">MACD</span>
        <span style="font-family:var(--mono);font-size:13px;font-weight:700;color:${macdInterp.c};margin-right:3px">${macdH>0?'+':''}${macdH.toFixed(1)}</span>
        <span style="font-size:10px;color:${macdInterp.c}">${macdInterp.txt}</span>
      </div>
      <!-- Signal details + T+2 -->
      <div style="padding:8px 12px;display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap">
        <div style="flex:1;min-width:0">
          ${details.length
            ? `<div style="display:flex;flex-wrap:wrap;gap:4px">${details.map(d=>`<span style="font-size:10px;padding:2px 7px;background:var(--bg3);border-radius:4px;color:var(--txt2);border:1px solid var(--bdr)">${d}</span>`).join('')}</div>`
            : `<span style="font-size:10px;color:var(--txt3)">Không có tín hiệu rõ ràng</span>`}
        </div>
        <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
          ${t2?`<div style="text-align:center;background:${t2.pct>=0?'#4ade8011':'#f8717111'};border:1px solid ${t2.pct>=0?'#4ade8033':'#f8717133'};border-radius:6px;padding:4px 8px">
            <div style="font-size:8px;color:var(--txt3);font-family:var(--mono)">T+2</div>
            <div style="font-family:var(--mono);font-size:11px;font-weight:700;color:${t2.pct>=0?'var(--buy)':'var(--sell)'}">${fmt(t2.nav||0)}</div>
            <div style="font-size:9px;color:${t2.pct>=0?'var(--buy)':'var(--sell)'}">${t2.pct>=0?'+':''}${(t2.pct||0).toFixed(2)}%</div>
          </div>`:''}
          <button onclick="event.stopPropagation();openAlertModal('${code}')" style="background:none;border:1px solid var(--bdr);color:var(--txt2);border-radius:6px;padding:4px 8px;font-size:11px;cursor:pointer">🔔</button>
        </div>
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
    _populateHomepiStrip();
  } else if (tradeActive) {
    // Switch to Phân Tích tab and open fund there instead of inline panel
    const histBtn = document.querySelector('.nav-btn[data-tab="history"]') || Array.from(document.querySelectorAll('.nav-btn')).find(b=>b.textContent.includes('Phân Tích'));
    goTab('history', histBtn);
    setTimeout(() => _selectHistFund(code, document.querySelector(`.hist-fund-row[onclick*="${code}"]`)), 500);
    return;
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
  if (hasHistory) html+=`<div class="section"><div class="section-hdr"><span>BIỂU ĐỒ NAV</span></div><div style="height:180px;position:relative"><canvas id="modal-nav-chart"></canvas></div></div>`;
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
  const titleEl = document.getElementById('chart-col-title');
  const subEl = document.getElementById('chart-col-sub');
  if (titleEl) titleEl.textContent = d.code;
  if (subEl) subEl.textContent = d.name || d.code;
  const hasHistory = d.nav_history?.length > 1;
  // Compact PI banner always visible at top when viewing a fund
  const miniPi = _pfIntelCompactHtml();
  let html=`<div class="res-header">
    <div>
      <div class="res-nav">${fmt(d.nav)} đ</div>
      <div class="pnl ${pnlC(chg)}" style="font-size:12px;margin-top:2px">${fmtP(chg)}</div>
    </div>
    <div class="badge ${sigC(d.signal)}" style="font-size:12px;padding:6px 10px">${sigLabel(d.signal)}</div>
  </div>`;
  html += _resIndicators(d);
  html += _t2PredHtml(d);
  if (hasHistory) {
    const _rOpts = [['1T','1M'],['3T','3M'],['1N','1Y'],['3N','3Y'],['Tất cả','ALL']];
    const _rBtns = _rOpts.map(([lbl,val])=>`<button class="range-btn${_chartRange===val?' active':''}" onclick="setChartRange('${val}',this)">${lbl}</button>`).join('');
    html+=`<div style="padding:5px 14px 4px;border-top:1px solid var(--bdr);display:flex;gap:4px">${_rBtns}</div>`;
    html+=`<div style="padding:0 14px 10px;height:300px;position:relative"><canvas id="${canvasId}"></canvas></div>`;
  }
  if (d.conclusion) html+=`<div class="res-conclusion">${d.conclusion}</div>`;
  html += _schoolCards(d.schools?.length ? d.schools : _computeSchools(d));
  html += `<div style="padding:4px 14px 8px"><button onclick="openAlertModal('${d.code}')" style="width:100%;padding:8px;background:var(--bg3);border:1px solid var(--bdr);color:var(--txt2);border-radius:8px;cursor:pointer;font-size:12px">🔔 Đặt cảnh báo giá</button></div>`;
  el.innerHTML = miniPi + html;
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

function toggleHistSortMode() {
  _histSortByTime = !_histSortByTime;
  const btn = document.getElementById('hist-sort-toggle');
  if (btn) {
    btn.title = _histSortByTime ? 'Nhóm theo quỹ' : 'Sắp xếp theo thời gian';
    btn.style.color = _histSortByTime ? 'var(--c0)' : '';
    btn.textContent = _histSortByTime ? '🕐' : '📋';
  }
  renderUnifiedHistory();
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

function _buildTradeSummary(trades) {
  // Per-fund aggregation: bought, sold, dividends
  const stats = {};
  const ensure = c => { if (!stats[c]) stats[c] = {code:c,buyAmt:0,buyUnits:0,sellAmt:0,sellUnits:0,divAmt:0,txCount:0}; };
  for (const t of trades) {
    if (t._asset !== 'ccq') continue;
    const c = t.fund_code; if (!c) continue;
    ensure(c);
    const s = stats[c]; s.txCount++;
    if (t.trade_type === 'buy')       { s.buyAmt  += t.amount||0; s.buyUnits  += t.units||0; }
    else if (t.trade_type === 'sell') { s.sellAmt += t.amount||0; s.sellUnits += t.units||0; }
    else if (t.trade_type === 'dividend') { s.divAmt += t.amount||0; }
  }
  return stats;
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

  // ── Lookup helpers ──
  const pfItems = _me?.portfolio?.items || _me?.items || [];
  const pfByCode = {};
  pfItems.forEach(it => { pfByCode[it.code || it.fund_code] = it; });
  const sigByCode = _signals || _marketData || {};

  // ── Build per-fund grouped transactions ──
  const ccqTrades = all.filter(t => t._asset === 'ccq');
  const goldTrades = all.filter(t => t._asset === 'gold');
  const fundGroups = {}; // { code: [trades...] }
  for (const t of ccqTrades) {
    const c = t.fund_code || '?';
    if (!fundGroups[c]) fundGroups[c] = [];
    fundGroups[c].push(t);
  }
  const fundStats = _buildTradeSummary(all);

  // ── Global totals ──
  let totalInvested = 0, totalUnreal = 0, totalRealized = 0;
  for (const [c, s] of Object.entries(fundStats)) {
    const pf = pfByCode[c];
    const sig = sigByCode[c];
    const currNav = pf?.current_nav || pf?.nav || sig?.nav || 0;
    const netUnits = s.buyUnits - s.sellUnits;
    const mktVal = currNav > 0 && netUnits > 0 ? netUnits * currNav : 0;
    const unrealPnl = pf?.pnl_amount != null
      ? pf.pnl_amount
      : mktVal > 0 ? mktVal - Math.max(0, s.buyAmt - s.sellAmt) : 0;
    const realPnl = s.sellUnits > 0
      ? s.sellAmt - (s.sellUnits / Math.max(s.buyUnits, 0.0001)) * s.buyAmt
      : 0;
    totalInvested += s.buyAmt;
    if (mktVal > 0) totalUnreal += unrealPnl;
    totalRealized += realPnl;
  }

  // ── Render one transaction row ──
  function _txRow(t) {
    const isGold = t._asset === 'gold';
    const code = isGold ? (t.gold_product || 'VÀNG') : t.fund_code || '';
    const date = t.trade_date || t.date || '';
    const typeLabel = t.trade_type === 'buy' ? 'MUA' : t.trade_type === 'sell' ? 'BÁN' : t.trade_type === 'dividend' ? 'LỢI TỨC' : (t.trade_type||'').toUpperCase();
    const typeC = t.trade_type === 'buy' ? 'var(--buy)' : t.trade_type === 'sell' ? 'var(--sell)' : 'var(--c0)';
    const amt = isGold ? `${t.units||t.qty||0}L × ${fmt(t.price||t.price_per_luong)}` : `${fmt(t.amount)} đ`;
    const isVirtual = !!t._virtual;
    const mismatch = (!isGold && !t.trade_type?.includes('dividend') && t.nav_mismatch) ? '<div style="font-size:10px;color:#facc15;margin-top:2px">⚠ Giá lệch NAV DB</div>' : '';
    const navInfo = (!isGold && t.nav && t.trade_type !== 'dividend') ? `<span style="font-family:var(--mono);font-size:10px;color:var(--txt3)"> · NAV ${fmt(t.nav)}</span>` : '';
    const virtualBadge = isVirtual ? `<span style="font-size:9px;color:var(--txt2);border:1px solid var(--bdr);border-radius:3px;padding:0 3px;margin-left:4px">Bot</span>` : '';
    const actions = isVirtual
      ? `<span style="font-size:10px;color:var(--txt2)">—</span>`
      : isGold
        ? `<div style="display:flex;gap:4px"><button class="tlog-btn" onclick="openEditGoldModal(${t.id||t._idx})" title="Sửa">✏️</button><button class="tlog-btn tlog-del" onclick="confirmDeleteGoldTrade(${t.id||t._idx})" title="Xoá">🗑️</button></div>`
        : `<div style="display:flex;gap:4px"><button class="tlog-btn" onclick="openEditModal(${t.id||t._idx})" title="Sửa">✏️</button><button class="tlog-btn tlog-del" onclick="confirmDeleteTrade(${t.id||t._idx})" title="Xoá">🗑️</button></div>`;
    return `<div style="display:flex;align-items:flex-start;justify-content:space-between;padding:8px 14px;border-bottom:1px solid var(--bdr);gap:8px">
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <span style="font-size:11px;font-weight:700;color:${typeC}">${typeLabel}</span>
          ${virtualBadge}
          <span style="font-family:var(--mono);font-size:11px;color:var(--txt1)">${amt}</span>
          ${navInfo}
        </div>
        <div style="font-size:10px;color:var(--txt3);margin-top:2px">${date}${t.note||t.name?` · <span style="color:var(--txt2)">${t.note||t.name}</span>`:''}</div>
        ${mismatch}
      </div>
      <div style="flex-shrink:0;margin-top:2px">${actions}</div>
    </div>`;
  }

  // ── Render per-fund group card ──
  function _fundGroupCard(c) {
    const s = fundStats[c] || {buyAmt:0,buyUnits:0,sellAmt:0,sellUnits:0,divAmt:0,txCount:0};
    const pf = pfByCode[c];
    const sig = sigByCode[c];
    const currNav = pf?.current_nav || pf?.nav || sig?.nav || 0;
    const netUnits = s.buyUnits - s.sellUnits;
    const netInvested = s.buyAmt - s.sellAmt;
    const mktVal = currNav > 0 && netUnits > 0 ? netUnits * currNav : 0;
    const unrealPnl = pf?.pnl_amount != null
      ? pf.pnl_amount
      : mktVal > 0 ? mktVal - Math.max(0, netInvested) : 0;
    const unrealPct = mktVal > 0 ? unrealPnl / Math.max(mktVal - unrealPnl, 1) * 100 : 0;
    const realPnl = s.sellUnits > 0
      ? s.sellAmt - (s.sellUnits / Math.max(s.buyUnits, 0.0001)) * s.buyAmt
      : 0;
    const holding = netUnits > 0.001;
    const pnlC = unrealPnl >= 0 ? 'var(--buy)' : 'var(--sell)';
    const sigVal = sig?.signal || '';
    const sigClass = sigVal.includes('MUA') ? 'buy' : sigVal.includes('BÁN') ? 'sell' : 'hold';
    const sigBadge = sigVal && sigVal !== 'N/A' ? `<span class="badge ${sigClass}" style="font-size:9px;padding:1px 6px">${sigVal}</span>` : '';
    const rsi = sig?.rsi;
    const rsiHint = rsi != null ? `RSI ${rsi.toFixed(0)}` : '';
    const chg30 = sig?.chg30;
    const chg30Html = chg30 != null
      ? `<span style="font-size:9px;font-family:var(--mono);color:${chg30>=0?'var(--buy)':'var(--sell)'}">${chg30>=0?'+':''}${chg30.toFixed(1)}% 1T</span>`
      : '';
    const trades = fundGroups[c] || [];
    const gid = 'fg_' + c.replace(/[^a-z0-9]/gi, '_');
    return `<div style="background:var(--bg2);border-radius:10px;overflow:hidden;border:1px solid var(--bdr);margin-bottom:10px">
      <!-- Fund group header -->
      <div onclick="(function(){var el=document.getElementById('${gid}');if(el){var open=el.style.display==='none';el.style.display=open?'block':'none';var arr=document.getElementById('${gid}_arr');if(arr)arr.textContent=open?'▲':'▼'}})()" style="cursor:pointer;padding:12px 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;border-left:3px solid ${holding?'var(--c0)':'var(--bdr)'}">
        <div style="flex:1;min-width:0">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
            <span style="font-family:var(--mono);font-size:14px;font-weight:700;color:var(--c0)">${c}</span>
            ${sigBadge}
            <span style="font-size:9px;color:var(--txt3)">${s.txCount} giao dịch · ${holding?'Đang nắm':'Đã đóng'}</span>
          </div>
          <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center">
            <span style="font-size:11px;color:var(--txt2)">Đã mua: <b style="font-family:var(--mono);color:var(--txt1)">${(s.buyAmt/1e6).toFixed(1)}M</b></span>
            ${holding && mktVal > 0 ? `<span style="font-size:11px;color:var(--txt2)">Hiện tại: <b style="font-family:var(--mono);color:var(--c0)">${(mktVal/1e6).toFixed(1)}M</b></span>` : ''}
            ${holding && mktVal > 0 ? `<span style="font-size:12px;font-weight:700;color:${pnlC}">${unrealPnl>=0?'+':''}${(unrealPnl/1e6).toFixed(2)}M (${unrealPct>=0?'+':''}${unrealPct.toFixed(1)}%)</span>` : ''}
            ${realPnl !== 0 ? `<span style="font-size:10px;color:${realPnl>=0?'var(--buy)':'var(--sell)'}">Thực hiện: ${realPnl>=0?'+':''}${(realPnl/1e3).toFixed(0)}k</span>` : ''}
            ${chg30Html}
            ${rsiHint ? `<span style="font-size:9px;color:var(--txt3);font-family:var(--mono)">${rsiHint}</span>` : ''}
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
          <button onclick="event.stopPropagation();openResearch('${c}')" style="background:none;border:1px solid var(--bdr);color:var(--txt2);border-radius:5px;padding:3px 8px;font-size:10px;cursor:pointer">📊 Phân tích</button>
          <span id="${gid}_arr" style="color:var(--txt3);font-size:11px">▼</span>
        </div>
      </div>
      <!-- Transactions list (collapsed by default if >3 trades) -->
      <div id="${gid}" style="display:${trades.length > 3 ? 'none' : 'block'}">
        ${trades.map(_txRow).join('')}
      </div>
      ${trades.length > 3 ? `<div onclick="(function(){var el=document.getElementById('${gid}');var arr=document.getElementById('${gid}_arr');if(el.style.display==='none'){el.style.display='block';if(arr)arr.textContent='▲'}else{el.style.display='none';if(arr)arr.textContent='▼'}})()" style="cursor:pointer;padding:6px 14px;font-size:10px;color:var(--txt3);text-align:center;border-top:1px solid var(--bdr)">▼ ${trades.length} giao dịch — bấm để xem</div>` : ''}
    </div>`;
  }

  // ── Gold group ──
  function _goldGroup() {
    if (!goldTrades.length) return '';
    return `<div style="background:var(--bg2);border-radius:10px;overflow:hidden;border:1px solid #fbbf2433;margin-bottom:10px">
      <div style="padding:12px 14px;border-left:3px solid #fbbf24;display:flex;align-items:center;gap:8px">
        <span style="font-size:14px;font-weight:700;color:#fbbf24;font-family:var(--mono)">🥇 VÀNG</span>
        <span style="font-size:9px;color:var(--txt3)">${goldTrades.length} giao dịch</span>
      </div>
      ${goldTrades.map(_txRow).join('')}
    </div>`;
  }

  // ── Global summary bar ──
  const totPnlC = totalUnreal >= 0 ? 'var(--buy)' : 'var(--sell)';
  const summaryBar = (assetF !== 'gold' && !codeF) ? `<div style="background:var(--bg3);border-radius:8px;padding:10px 14px;margin-bottom:14px;display:flex;gap:20px;flex-wrap:wrap">
    <div><div style="font-size:9px;color:var(--txt3)">Tổng đã mua (CCQ)</div><div style="font-family:var(--mono);font-size:14px;font-weight:700">${(totalInvested/1e6).toFixed(1)}M đ</div></div>
    ${totalUnreal !== 0 ? `<div><div style="font-size:9px;color:var(--txt3)">Lãi/lỗ chưa thực hiện</div><div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${totPnlC}">${totalUnreal>=0?'+':''}${(totalUnreal/1e6).toFixed(2)}M đ</div></div>` : ''}
    ${totalRealized !== 0 ? `<div><div style="font-size:9px;color:var(--txt3)">Lãi/lỗ đã thực hiện</div><div style="font-family:var(--mono);font-size:13px;font-weight:700;color:${totalRealized>=0?'var(--buy)':'var(--sell)'}">${totalRealized>=0?'+':''}${(totalRealized/1e3).toFixed(0)}k đ</div></div>` : ''}
  </div>` : '';

  // ── Render ──
  if (_histSortByTime) {
    // Flat chronological list
    const flatRows = all.map(_txRow).join('');
    const flatNote = `<div style="font-size:10px;color:var(--txt3);padding:8px 14px;text-align:center">Hiển thị theo thời gian — <span style="cursor:pointer;color:var(--c0)" onclick="toggleHistSortMode()">chuyển sang nhóm theo quỹ</span></div>`;
    el.innerHTML = summaryBar + flatNote + `<div>${flatRows}</div>`;
    return;
  }
  const fundCodes = Object.keys(fundGroups).sort();
  const fundHtml = (assetF !== 'gold' && ccqTrades.length)
    ? fundCodes.map(_fundGroupCard).join('')
    : '';
  el.innerHTML = summaryBar + fundHtml + _goldGroup();
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
  // gp-xau (XAU/USD USD/oz) — không auto-fill từ SJC VND (đơn vị khác nhau); user nhập thủ công
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
  const _sr0=_goldData?.signal?.sjc_sell||_goldData?.prices?.['VANGTODAYAPI:SJC_1L'];
  const sjcRaw=(typeof _sr0==='object'?(_sr0?.sell||_sr0?.buy):_sr0)||87000000;
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
      <td class="au-name">${esc(u.name)||'—'}${u.is_admin?'<span class="au-badge-admin">ADMIN</span>':''}</td>
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
function _setHistSort(mode) {
  _histFundSort = mode;
  ['default','score','rsi'].forEach(m => {
    const btn = document.getElementById('hsort-'+m);
    if (!btn) return;
    const active = m === mode;
    btn.style.background = active ? 'var(--c0)' : '';
    btn.style.color       = active ? 'var(--bg)' : '';
    btn.style.borderColor = active ? 'var(--c0)' : '';
  });
  _renderHistFundList();
}

function _sparklineSvg(code) {
  const pts = _histNavCache[code];
  if (!pts || pts.length < 3) return '';
  const last = pts.slice(-20);
  const navs = last.map(p => p.nav);
  const mn = Math.min(...navs), mx = Math.max(...navs), rng = mx - mn || 1;
  const W = 40, H = 14, n = navs.length;
  const pts2d = navs.map((v, i) => `${Math.round(i/(n-1)*W)},${Math.round(H-(v-mn)/rng*H)}`).join(' ');
  const up = navs[n-1] >= navs[0];
  return `<svg width="${W}" height="${H}" style="flex-shrink:0;opacity:.7;vertical-align:middle"><polyline points="${pts2d}" fill="none" stroke="${up?'var(--buy)':'var(--sell)'}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}
function _renderHistFundList() {
  const el = document.getElementById('hist-fund-list'); if (!el) return;
  const sigs = _signals || _marketData || MOCK_SIGNALS || {};
  const held = new Set(_me?.portfolio?.items?.map(i=>i.code)||[]);
  const watched = new Set(_me?.watched_funds || []);
  // Show ALL funds — exclude funds with no NAV data (delisted/inactive)
  const allCodes = Object.keys(sigs).filter(c => (sigs[c]?.nav || 0) > 0);
  const priority = allCodes.filter(c => held.has(c) || watched.has(c));
  const rest = allCodes.filter(c => !held.has(c) && !watched.has(c));
  // Highlight: top 2 MUA (highest score ≥ 3) + top 2 BÁN (lowest score ≤ -3) only
  const muaTop2 = new Set(allCodes.filter(c=>(sigs[c]?.score||0)>=3).sort((a,b)=>(sigs[b]?.score||0)-(sigs[a]?.score||0)).slice(0,2));
  const banTop2 = new Set(allCodes.filter(c=>(sigs[c]?.score||0)<=-3).sort((a,b)=>(sigs[a]?.score||0)-(sigs[b]?.score||0)).slice(0,2));
  const hlType = c => muaTop2.has(c) ? 'mua' : banTop2.has(c) ? 'ban' : null;
  // Apply sort mode
  const sortFn = {
    score: (a, b) => (sigs[b]?.score || 0) - (sigs[a]?.score || 0),
    rsi:   (a, b) => (sigs[a]?.rsi ?? 50) - (sigs[b]?.rsi ?? 50),
    default: (a, b) => a.localeCompare(b),
  }[_histFundSort] || ((a, b) => a.localeCompare(b));
  // Signal strength sort: MUA (score≥3) → TRUNG LẬP → BÁN (score≤-3)
  const sigOrder = c => { const sc = sigs[c]?.score||0; return sc >= 3 ? 0 : sc <= -3 ? 2 : 1; };
  const signalThenAlpha = (a, b) => sigOrder(a) - sigOrder(b) || a.localeCompare(b);
  // Default: highlight funds first (pinned top) → held/watched → rest, each group sorted by signal
  const hlCodes = allCodes.filter(c => hlType(c));
  const nonHlPriority = priority.filter(c => !hlType(c));
  const nonHlRest = rest.filter(c => !hlType(c));
  const funds = _histFundSort === 'default'
    ? [...hlCodes.sort(signalThenAlpha), ...nonHlPriority.sort(signalThenAlpha), ...nonHlRest.sort(signalThenAlpha)]
    : [...allCodes].sort(sortFn);
  const countEl = document.getElementById('hist-fund-count');
  if (countEl) countEl.textContent = funds.length + ' quỹ';
  if (!allCodes.length) { el.innerHTML='<div style="color:var(--txt2);font-size:12px;padding:16px;text-align:center">Đang tải dữ liệu...</div>'; return; }
  // WEB-011: Gold row pinned at top of fund list
  const gs = _goldData?.signals;
  // Fallback price from prices dict when signals are empty (no Railway connection)
  const _gRawPrice = gs?.price || _goldData?.prices?.['VANGTODAYAPI:SJC_1L'] || _goldData?.prices?.['SJC_1L'] || null;
  const goldActiveClass = _histPageCode==='GOLD_SJC' ? 'active' : '';
  const goldSigLabel = gs?.signal || '';
  const goldSigClass = goldSigLabel.includes('MUA')?'buy':goldSigLabel.includes('THẬN')||goldSigLabel.includes('BÁN')?'sell':'hold';
  const goldChgHtml = gs?.chg_pct!=null ? `<span class="pnl ${pnlC(gs.chg_pct)}" style="font-size:11px;font-weight:600">${gs.chg_pct>=0?'+':''}${gs.chg_pct.toFixed(2)}%</span>` : '';
  const goldPriceHtml = _gRawPrice ? `<span style="font-family:var(--mono);font-size:12px;color:var(--txt1);font-weight:600">${(_gRawPrice/1e6).toFixed(1)}M đ</span>` : '';
  const goldRsi = gs?.rsi != null ? gs.rsi : null;
  const goldBb  = gs?.bb_pct != null ? gs.bb_pct : null;
  const goldMacd = gs?.macd_hist != null ? gs.macd_hist : null;
  const goldRsiC = goldRsi!=null ? (goldRsi<35?'var(--buy)':goldRsi>65?'var(--sell)':'var(--txt3)') : 'var(--txt3)';
  const goldBbC  = goldBb!=null  ? (goldBb<25?'var(--buy)':goldBb>75?'var(--sell)':'var(--txt3)') : 'var(--txt3)';
  const goldScore = gs?.score ?? null;
  const goldScoreC = goldScore!=null ? (goldScore>=3?'var(--buy)':goldScore<=-3?'var(--sell)':'#facc15') : 'var(--txt3)';
  const goldIndHtml = (goldRsi!=null||goldBb!=null||goldScore!=null) ? `<div style="display:flex;gap:6px;margin-top:4px;flex-wrap:wrap">
    ${goldScore!=null?`<span style="font-size:9px;font-family:var(--mono);color:${goldScoreC};background:${goldScoreC}22;border:1px solid ${goldScoreC}44;border-radius:3px;padding:1px 5px">Điểm ${goldScore>0?'+':''}${goldScore}</span>`:''}
    ${goldRsi!=null?`<span style="font-size:9px;font-family:var(--mono);color:${goldRsiC}">RSI ${goldRsi.toFixed(0)}</span>`:''}
    ${goldBb!=null?`<span style="font-size:9px;font-family:var(--mono);color:${goldBbC}">BB ${goldBb.toFixed(0)}%</span>`:''}
    ${gs?.chg7!=null?`<span style="font-size:9px;font-family:var(--mono);color:${pnlC(gs.chg7)}">7N ${gs.chg7>=0?'+':''}${gs.chg7.toFixed(1)}%</span>`:''}
  </div>` : '';
  const goldRow = `<div class="hist-fund-row ${goldActiveClass}" onclick="_selectHistFund('GOLD_SJC',this)" style="display:flex;flex-direction:column;gap:2px;padding:9px 12px;border-left:3px solid #fbbf24">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;margin-bottom:2px">
      <span style="font-family:var(--mono);font-size:13px;font-weight:700;color:#fbbf24">🥇 VÀNG SJC</span>
      ${goldSigLabel ? `<span class="badge ${goldSigClass}" style="font-size:10px;padding:2px 7px;font-weight:700">${goldSigLabel}</span>` : ''}
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      ${goldPriceHtml}${goldChgHtml}
      ${!goldPriceHtml && !goldChgHtml ? '<span style="font-size:10px;color:var(--txt3);font-family:var(--mono)">Chưa có giá hôm nay</span>' : ''}
    </div>
    ${goldIndHtml}
  </div>`;
  const _todayForHist = new Date().toISOString().slice(0,10);
  el.innerHTML = goldRow + funds.map(code => {
    const s = sigs[code] || {};
    const nav = s.nav ? fmt(s.nav)+' đ' : '—';
    const chg = s.chg_pct ?? s.change_pct ?? s.change ?? null;
    const chgHtml = chg!=null ? `<span class="pnl ${pnlC(chg)}" style="font-size:11px">${chg>=0?'+':''}${chg.toFixed(2)}%</span>` : '';
    const _ndH = s.nav_date;
    const _fmtFullDateH = d => { const p=d.split('-'); return `${p[2]}/${p[1]}/${p[0]}`; };
    const _staleH = (_ndH && _ndH !== _todayForHist) ? `<span style="font-size:9px;color:#f59e0b;font-family:var(--mono);padding:1px 5px;border:1px solid #f59e0b55;border-radius:3px;background:#f59e0b15;white-space:nowrap" title="NAV từ ngày ${_fmtFullDateH(_ndH)}">📅 ${_fmtFullDateH(_ndH)}</span>` : '';
    const sig = s.signal || '';
    const sigClass = sig.includes('MUA')?'buy':sig.includes('BÁN')||sig.includes('BAN')?'sell':'hold';
    const sigHtml = sig && sig!=='N/A' ? `<span class="badge ${sigClass}" style="font-size:10px;padding:2px 7px;font-weight:700">${sig}</span>` : '';
    const isWatched = watched.has(code);
    const starBtn = `<span onclick="event.stopPropagation();_toggleWatchFund('${code}')" title="${isWatched?'Bỏ theo dõi':'Thêm theo dõi'}" style="cursor:pointer;font-size:10px;color:${isWatched?'var(--c0)':'var(--txt3)'};padding:0 1px;line-height:1;flex-shrink:0">${isWatched?'★':'☆'}</span>`;
    const sc = s.score || 0;
    const hl = hlType(code);
    // Full-row background for top-2 MUA and top-2 BÁN only
    const hlBg = hl === 'mua' ? 'rgba(74,222,128,0.07)' : hl === 'ban' ? 'rgba(248,113,113,0.07)' : '';
    const hlBorder = hl === 'mua' ? 'border-left:3px solid var(--buy)' : hl === 'ban' ? 'border-left:3px solid var(--sell)' : 'border-left:3px solid transparent';
    // Score chip shown only on highlighted rows
    const scC = hl === 'mua' ? 'var(--buy)' : hl === 'ban' ? 'var(--sell)' : '#facc15';
    const scHtml = hl ? `<span style="font-size:9px;font-family:var(--mono);color:${scC};background:${scC}20;border:1px solid ${scC}55;border-radius:3px;padding:1px 5px;font-weight:700">Điểm ${sc>0?'+':''}${sc}</span>` : '';
    const sparkline = _sparklineSvg(code);
    return `<div class="hist-fund-row ${_histPageCode===code?'active':''}" onclick="_selectHistFund('${code}',this)" style="${hlBorder};${hlBg?'background:'+hlBg+';':''}display:flex;align-items:center;gap:8px;padding:9px 12px">
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;flex-wrap:wrap">
          <span class="sig-code" style="font-size:13px">${code}</span>
          ${held.has(code)?'<span style="font-size:9px;font-family:var(--mono);color:var(--c0);background:var(--c0)22;border:1px solid var(--c0)44;border-radius:3px;padding:0 5px">NẮM</span>':''}
          ${sigHtml}
          ${scHtml}
        </div>
        <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap">
          <span style="font-size:12px;font-family:var(--mono);color:var(--txt1)">${nav}</span>
          ${chgHtml}
          ${_staleH}
        </div>
      </div>
      ${sparkline ? `<div style="flex-shrink:0">${sparkline}</div>` : ''}
      <span onclick="event.stopPropagation();_toggleWatchFund('${code}')" title="${watched.has(code)?'Bỏ theo dõi':'Thêm theo dõi'}" style="cursor:pointer;font-size:16px;flex-shrink:0;color:${watched.has(code)?'#facc15':'var(--txt3)'}">${watched.has(code)?'★':'☆'}</span>
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
  // Show/hide Vàng view button based on selected fund
  const goldBtn = document.getElementById('hist-view-gold');
  if (goldBtn) goldBtn.style.display = code === 'GOLD_SJC' ? '' : 'none';
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
    r.classList.toggle('active', r.querySelector('.sig-code')?.textContent === code);
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
    // Fetch nav history and research metadata in parallel
    const [d, res] = await Promise.all([
      apiFetch(`/api/nav_history/${code}`),
      apiFetch(`/api/research/${code}`).catch(()=>null)
    ]);
    _histPageData = (d.history || d).sort((a,b)=>a.date<b.date?-1:1);
    _histNavCache[code] = _histPageData;  // cache for sparklines / portfolio chart
    _renderHistFundList(); // re-render list so sparklines fill in now that cache exists
    // Store research metadata for analysis panel
    if (res) {
      // Kế thừa toàn bộ signals từ _marketData trước khi ghi riêng từng fund
      // để _renderHistFundList() không mất các quỹ khác
      if (!_signals && _marketData) _signals = {..._marketData};
      else if (!_signals) _signals = {};
      _signals[code] = {...(_signals[code]||{}), ...res, t2_prediction: res.t2_prediction};
    }
    // Update label with fund name if available
    const lbl2 = document.getElementById('hist-fund-label');
    if (lbl2 && res?.name && res.name !== code) lbl2.textContent = `${code} — ${res.name.slice(0,20)}`;
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
    hdrEl.innerHTML = `<div style="display:flex;align-items:center;gap:8px">
      <span style="font-family:var(--mono);font-size:10px;color:var(--txt2);letter-spacing:.08em">${code}</span>
      <span class="hist-nav-hval">${fmt(last)} đ</span>
      <span class="hist-nav-hchg pnl ${pnlC(chg)}">${chg>=0?'+':''}${chg.toFixed(2)}%</span>
      <button onclick="(()=>{const d=document.getElementById('manual-nav-panel');if(d){d.open=!d.open;if(d.open)_initBulkRows();}})()" title="Nhập NAV thủ công" style="margin-left:auto;padding:2px 8px;font-size:10px;font-family:var(--mono);background:var(--bg3);border:1px solid var(--c0)66;border-radius:4px;color:var(--c0);cursor:pointer;flex-shrink:0;line-height:1.4">✏️ NAV</button>
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
  const _ma=(arr,n)=>arr.map((_,i)=>i<n-1?null:arr.slice(i-n+1,i+1).reduce((a,b)=>a+b,0)/n);
  const ma20=_ma(vals,20), ma50=_ma(vals,50);
  // Transaction overlays: use cached _tradeLog (loaded when Giao Dịch tab opened)
  const txBuy = [], txSell = [];
  if (Array.isArray(_tradeLog)) {
    const labelSet = new Set(labels);
    _tradeLog.filter(t => t.fund_code === code).forEach(t => {
      const d = (t.date||'').slice(0,10);
      if (!labelSet.has(d)) return;
      const navAtDate = filtered[labels.indexOf(d)]?.nav ?? vals[labels.indexOf(d)];
      if (navAtDate == null) return;
      const pt = {x: d, y: navAtDate};
      if (t.type === 'buy') txBuy.push(pt); else txSell.push(pt);
    });
  }
  const txDatasets = [
    ...(txBuy.length ? [{
      type:'scatter', label:'Mua', data:txBuy,
      backgroundColor:'rgba(74,222,128,0.9)', borderColor:'#4ade80', borderWidth:1.5,
      pointRadius:5, pointStyle:'triangle', pointHoverRadius:7, order:0
    }] : []),
    ...(txSell.length ? [{
      type:'scatter', label:'Bán', data:txSell,
      backgroundColor:'rgba(248,113,113,0.9)', borderColor:'#f87171', borderWidth:1.5,
      pointRadius:5, pointStyle:'triangle', rotation:180, pointHoverRadius:7, order:0
    }] : [])
  ];
  _histPageChart = new Chart(ctx, {
    type:'line',
    data:{labels, datasets:[
      {data:vals, label:'NAV', borderColor:'#00e5ff', borderWidth:1.5, fill:true, backgroundColor:grad, tension:0.35, pointRadius:0, pointHoverRadius:4},
      {data:ma20, label:'MA20', borderColor:'rgba(250,204,21,0.7)', borderWidth:1, fill:false, tension:0.3, pointRadius:0, spanGaps:true},
      {data:ma50, label:'MA50', borderColor:'rgba(74,222,128,0.7)', borderWidth:1, fill:false, tension:0.3, pointRadius:0, spanGaps:true},
      ...txDatasets
    ]},
    options:{responsive:true, maintainAspectRatio:false, animation:false,
      layout:{padding:0},
      plugins:{legend:{display:vals.length>50||(txBuy.length+txSell.length>0), labels:{color:'#6b7280',font:{size:9},boxWidth:12,padding:8, filter:(item)=>item.text!=='NAV'||vals.length>50}},
        tooltip:{mode:'index',intersect:false, callbacks:{label:(c)=>c.dataset.label==='NAV'?`NAV: ${fmt(Math.round(c.parsed.y))} đ`:`${c.dataset.label}: ${fmt(Math.round(c.parsed.y))}`}},
        crosshair:_crosshairPlugin},
      scales:{x:{type:'category',ticks:{maxTicksLimit:8,color:'#6b7280',font:{size:10}},grid:{color:'rgba(255,255,255,.04)'}}, y:{position:'right',ticks:{color:'#6b7280',font:{size:10}, callback:v=>fmt(Math.round(v))},grid:{color:'rgba(255,255,255,.04)'}}}}
  });
  // Force chart to fill container width after layout settles
  setTimeout(() => { if (_histPageChart) _histPageChart.resize(); }, 60);
  _renderBelowChart(code, vals[vals.length-1]);
}
function applyHistDateRange() {
  if (_histPageData) renderHistChart(_histPageData, _histPageCode);
}

function _renderBelowChart(code, currentNav) {
  const el = document.getElementById('hist-below-chart'); if (!el) return;
  if (!code) { el.innerHTML = ''; return; }
  if (code === 'GOLD_SJC') { _renderGoldBelowChart(el); return; }
  const s = (_signals?.[code]) || (_marketData?.[code]) || {};
  const nav = currentNav || s.nav || 0;
  const held = _me?.portfolio?.items?.find(h => h.code === code);

  // Peer comparison within same fund type
  const allSigs = Object.entries(_signals || _marketData || {}).filter(([c]) => c !== code);
  const ft = s.fund_type || '';
  const peers = ft ? allSigs.filter(([,ps]) => ps.fund_type === ft) : allSigs;
  const peerCount = peers.length;
  const p30 = s.chg30 ?? s.chg_30 ?? null;
  const p7  = s.chg7  ?? s.chg_7  ?? null;
  const rank30 = (p30 != null && peerCount > 0) ? peers.filter(([,ps]) => (ps.chg30 ?? ps.chg_30 ?? -999) > p30).length + 1 : null;
  const rank7  = (p7  != null && peerCount > 0) ? peers.filter(([,ps]) => (ps.chg7  ?? ps.chg_7  ?? -999) > p7 ).length + 1 : null;
  const total  = peerCount + 1;

  const rankRow = (label, rank, tot, pct) => {
    if (rank == null) return '';
    const bar = Math.round((1 - (rank-1)/Math.max(tot-1,1)) * 100);
    const c = bar >= 60 ? 'var(--buy)' : bar >= 35 ? '#facc15' : 'var(--sell)';
    return `<div style="margin-bottom:6px">
      <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--txt2);margin-bottom:2px">
        <span>${label}</span>
        <span style="font-family:var(--mono);color:${c}">Hạng ${rank}/${tot} <span style="color:var(--txt3)">(${pct>=0?'+':''}${pct?.toFixed(2)}%)</span></span>
      </div>
      <div style="height:4px;background:var(--bdr);border-radius:2px"><div style="height:100%;width:${bar}%;background:${c};border-radius:2px"></div></div>
    </div>`;
  };

  // Fibonacci levels from 52w high/low
  const hi52 = s.high_52w || s.hi52 || null;
  const lo52 = s.low_52w  || s.lo52  || null;
  const fibLevels = (hi52 && lo52 && nav > 0) ? (() => {
    const rng = hi52 - lo52;
    const f = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1].map(r => ({r, v: lo52 + rng * r}));
    const cur = nav;
    return f.filter(({v}) => v > 0).map(({r, v}) => {
      const diff = ((v - cur) / cur * 100);
      const isAbove = v > cur;
      const label = r === 0 ? 'Đáy 52T' : r === 1 ? 'Đỉnh 52T' : `Fib ${(r*100).toFixed(1)}%`;
      const c = isAbove ? 'var(--sell)' : 'var(--buy)';
      const role = isAbove ? '↑ Kháng cự' : '↓ Hỗ trợ';
      if (r === 0.5 && Math.abs(diff) < 1) return null; // skip if very close to current
      return `<div style="display:flex;justify-content:space-between;align-items:center;padding:3px 0;border-bottom:1px solid var(--bdr)15">
        <span style="font-size:10px;color:var(--txt3)">${label} <span style="font-size:9px;color:${c}">${role}</span></span>
        <span style="font-family:var(--mono);font-size:10px;color:${c}">${fmt(Math.round(v))} đ <span style="font-size:9px">(${diff>=0?'+':''}${diff.toFixed(1)}%)</span></span>
      </div>`;
    }).filter(Boolean).join('');
  })() : '';

  // MA distance
  const ma20 = s.ma20 || null;
  const ma50 = s.ma50 || null;
  const maRow = (nav > 0 && (ma20 || ma50)) ? `<div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">
    ${ma20 ? (() => { const d=((nav-ma20)/ma20*100); const c=d>=0?'var(--buy)':'var(--sell)'; return `<div style="flex:1;background:var(--bg);border:1px solid var(--bdr);border-radius:5px;padding:5px 8px;text-align:center"><div style="font-size:9px;color:var(--txt3)">Giá vs TB 20 ngày</div><div style="font-family:var(--mono);font-size:12px;font-weight:600;color:${c}">${d>=0?'+':''}${d.toFixed(1)}%</div></div>`; })() : ''}
    ${ma50 ? (() => { const d=((nav-ma50)/ma50*100); const c=d>=0?'var(--buy)':'var(--sell)'; return `<div style="flex:1;background:var(--bg);border:1px solid var(--bdr);border-radius:5px;padding:5px 8px;text-align:center"><div style="font-size:9px;color:var(--txt3)">Giá vs TB 50 ngày</div><div style="font-family:var(--mono);font-size:12px;font-weight:600;color:${c}">${d>=0?'+':''}${d.toFixed(1)}%</div></div>`; })() : ''}
  </div>` : '';

  const peerSection = (rank30 || rank7) ? `<div style="margin-bottom:10px">
    <div style="font-size:9px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;margin-bottom:6px">XẾP HẠNG TRONG NHÓM${ft ? ' — '+ft : ''} (${total} quỹ)</div>
    ${rankRow('30 ngày qua', rank30, total, p30)}
    ${rankRow('7 ngày qua', rank7, total, p7)}
  </div>` : '';

  const fibSection = fibLevels ? `<div style="margin-bottom:10px">
    <div style="font-size:9px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;margin-bottom:4px">MỨC GIÁ QUAN TRỌNG (Fibonacci 52 tuần)</div>
    ${fibLevels}
    ${maRow}
  </div>` : (maRow ? `<div style="margin-bottom:10px">${maRow}</div>` : '');

  const heldSection = held ? (() => {
    const heldCost = held.cost_per_unit || 0;
    const heldUnits = held.units || 0;
    const pnlPct = (heldCost > 0 && nav > 0) ? ((nav - heldCost) / heldCost * 100) : 0;
    const breakevenUnits = heldCost > 0 && nav > 0 && heldCost > nav ? Math.ceil((heldCost - nav) / nav * heldUnits * 10) / 10 : null;
    const c = pnlPct >= 0 ? 'var(--buy)' : 'var(--sell)';
    return `<div style="background:var(--bg);border:1px solid var(--bdr)44;border-radius:6px;padding:8px 10px;margin-bottom:10px">
      <div style="font-size:9px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;margin-bottom:6px">VỊ THẾ ĐANG NẮM GIỮ</div>
      <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px">
        <span style="color:var(--txt3)">${heldUnits.toFixed(2)} CCQ × ${fmt(Math.round(nav))} đ</span>
        <span style="font-family:var(--mono);font-weight:600;color:${c}">${pnlPct>=0?'+':''}${pnlPct.toFixed(2)}%</span>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--txt3)">
        <span>Giá vốn: ${fmt(Math.round(heldCost))} đ/CCQ</span>
        <span style="color:${c}">${pnlPct>=0?'Đang lãi':'Đang lỗ'}</span>
      </div>
    </div>`;
  })() : '';

  // Fallback: always show quick indicators even when no peer/fib data
  const sc2 = s.score ?? null;
  const rsi2 = s.rsi ?? null;
  const bb2 = s.bb_pct ?? null;
  const vol2 = s.volatility ?? s.vol ?? null;
  const quickStats = (sc2!=null||rsi2!=null||bb2!=null||vol2!=null) ? `<div style="margin-bottom:10px">
    <div style="font-size:9px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;margin-bottom:6px">CHỈ SỐ NHANH</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px">
      ${sc2!=null?`<div style="background:var(--bg);border-radius:5px;padding:5px 8px;text-align:center"><div style="font-size:9px;color:var(--txt3)">Smart Score</div><div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${sc2>=3?'var(--buy)':sc2<=-3?'var(--sell)':'#facc15'}">${sc2>0?'+':''}${sc2}</div></div>`:''}
      ${rsi2!=null?`<div style="background:var(--bg);border-radius:5px;padding:5px 8px;text-align:center"><div style="font-size:9px;color:var(--txt3)">RSI (14)</div><div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${rsi2<35?'var(--buy)':rsi2>65?'var(--sell)':'var(--txt2)'}">${rsi2.toFixed(1)}</div></div>`:''}
      ${bb2!=null?`<div style="background:var(--bg);border-radius:5px;padding:5px 8px;text-align:center"><div style="font-size:9px;color:var(--txt3)">BB %B</div><div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${bb2<25?'var(--buy)':bb2>75?'var(--sell)':'var(--txt2)'}">${bb2.toFixed(1)}%</div></div>`:''}
      ${vol2!=null?`<div style="background:var(--bg);border-radius:5px;padding:5px 8px;text-align:center"><div style="font-size:9px;color:var(--txt3)">Dao động/năm</div><div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${vol2<8?'var(--buy)':vol2>18?'var(--sell)':'#facc15'}">${vol2.toFixed(1)}%</div></div>`:''}
    </div>
  </div>` : '';

  const stratSection = _lastStrategyHtml ? `<div style="margin-top:8px">
    <div style="font-size:9px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;margin-bottom:2px">CHIẾN LƯỢC GỢI Ý</div>
    ${_lastStrategyHtml}
  </div>` : '';

  el.innerHTML = `<div style="padding:10px 12px;min-height:100%;box-sizing:border-box">
    ${heldSection}${peerSection}${fibSection}${(!peerSection&&!fibSection)?quickStats:''}${stratSection}
  </div>`;
}

function _renderGoldBelowChart(el) {
  const s = _goldData?.signals;
  if (!s) {
    el.innerHTML = `<div style="padding:14px 12px;color:var(--txt2);font-size:12px;text-align:center;line-height:1.8">
      🥇<br><b style="color:var(--txt1)">VÀNG SJC</b><br>
      <span style="font-size:11px">Chưa có dữ liệu tín hiệu vàng.</span>
    </div>`;
    return;
  }
  const rsi = s.rsi ?? null, bb = s.bb_pct ?? null, score = s.score ?? 0;
  const sc = score >= 3 ? 'var(--buy)' : score <= -2 ? 'var(--sell)' : '#facc15';
  const rsiC = rsi==null?'var(--txt2)':rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--txt2)';
  const bbC  = bb==null?'var(--txt2)':bb<25?'var(--buy)':bb>75?'var(--sell)':'var(--txt2)';
  const goldHeld = _me?.portfolio?.gold_items?.length || _me?.portfolio?.gold_total_value > 0;
  const goldValue = _me?.portfolio?.gold_total_value;
  const goldPnl   = _me?.portfolio?.gold_pnl_pct;
  const heldHtml = goldHeld ? `<div style="background:var(--bg);border:1px solid var(--bdr)44;border-radius:6px;padding:8px 10px;margin-bottom:10px">
    <div style="font-size:9px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;margin-bottom:5px">VỊ THẾ VÀNG ĐANG NẮM</div>
    <div style="display:flex;justify-content:space-between;font-size:12px">
      <span style="color:var(--txt2)">${goldValue ? fmt(goldValue)+' đ' : '—'}</span>
      <span style="font-family:var(--mono);font-weight:600;color:${goldPnl>=0?'var(--buy)':'var(--sell)'}">${goldPnl!=null?(goldPnl>=0?'+':'')+goldPnl.toFixed(2)+'%':'—'}</span>
    </div>
  </div>` : '';
  const statsHtml = `<div style="margin-bottom:10px">
    <div style="font-size:9px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;margin-bottom:6px">CHỈ SỐ KỸ THUẬT — VÀNG</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px">
      <div style="background:var(--bg);border-radius:5px;padding:6px 8px;text-align:center">
        <div style="font-size:9px;color:var(--txt3)">Smart Score</div>
        <div style="font-family:var(--mono);font-size:16px;font-weight:700;color:${sc}">${score>0?'+':''}${score}</div>
        <div style="font-size:9px;color:${sc}">${score>=3?'MUA':score<=-2?'THẬN TRỌNG':'HOLD'}</div>
      </div>
      ${rsi!=null?`<div style="background:var(--bg);border-radius:5px;padding:6px 8px;text-align:center">
        <div style="font-size:9px;color:var(--txt3)">RSI (14)</div>
        <div style="font-family:var(--mono);font-size:16px;font-weight:700;color:${rsiC}">${rsi.toFixed(1)}</div>
        <div style="font-size:9px;color:${rsiC}">${rsi<35?'Quá bán':rsi>65?'Quá mua':'Trung tính'}</div>
      </div>`:''}
      ${bb!=null?`<div style="background:var(--bg);border-radius:5px;padding:6px 8px;text-align:center">
        <div style="font-size:9px;color:var(--txt3)">BB %B</div>
        <div style="font-family:var(--mono);font-size:16px;font-weight:700;color:${bbC}">${bb.toFixed(1)}%</div>
        <div style="font-size:9px;color:${bbC}">${bb<25?'Gần đáy':bb>75?'Gần đỉnh':'Giữa dải'}</div>
      </div>`:''}
      ${s.chg7!=null?`<div style="background:var(--bg);border-radius:5px;padding:6px 8px;text-align:center">
        <div style="font-size:9px;color:var(--txt3)">7 ngày</div>
        <div style="font-family:var(--mono);font-size:16px;font-weight:700;color:${s.chg7>=0?'var(--buy)':'var(--sell)'}">${s.chg7>=0?'+':''}${s.chg7.toFixed(2)}%</div>
      </div>`:''}
    </div>
  </div>`;
  const phiBuHtml = s.phi_bu_xau != null ? `<div style="margin-bottom:10px">
    <div style="font-size:9px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;margin-bottom:4px">PHÍ BÙ XAU (CHÊNH LỆCH SJC)</div>
    <div style="background:var(--bg);border-radius:5px;padding:6px 10px;font-family:var(--mono);font-size:13px;font-weight:600;color:${s.phi_bu_xau>5?'var(--sell)':'var(--txt1)'}">${s.phi_bu_xau?.toFixed(1)}% <span style="font-size:10px;color:var(--txt3);font-weight:400">so với giá thế giới</span></div>
  </div>` : '';
  el.innerHTML = `<div style="padding:10px 12px;min-height:100%;box-sizing:border-box">${heldHtml}${statsHtml}${phiBuHtml}</div>`;
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
  return `<div style="background:var(--bg3);border:1px solid var(--bdr);border-radius:6px;padding:5px 10px;margin:4px 14px;display:flex;justify-content:space-between;align-items:center;gap:10px">
    <div>
      <div style="font-size:8px;font-family:var(--mono);color:var(--txt3);text-transform:uppercase;letter-spacing:.08em">Dự báo T+2 (${predDate})</div>
      <div style="font-family:var(--mono);font-size:11px;font-weight:600;margin-top:1px">${fmt(predNav)} đ</div>
    </div>
    <div style="text-align:right">
      <div class="pnl ${pnlC(predChg)}" style="font-size:11px;font-family:var(--mono)">${fmtP(predChg)}</div>
      ${mape!=null?`<div style="font-size:9px;color:var(--txt2)">MAPE ${Number(mape).toFixed(1)}%</div>`:'<div style="font-size:9px;color:var(--txt3)">AI dự báo</div>'}
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
  // Expand chart area to fill space when analysis panel hidden
  const chartArea = document.getElementById('hist-chart-area');
  if (chartArea) {
    if (view === 'nav') {
      chartArea.style.height = '280px'; chartArea.style.flex = '';
    } else {
      chartArea.style.height = ''; chartArea.style.flex = '1';
    }
  }
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
  const _hasGold = !!(_goldData?.signals?.price || _goldData?.signals?.rsi);
  const allCodes = Object.keys(_marketData || _signals || MOCK_SIGNALS || {}).filter(c=>c!==code1)
    .concat(_hasGold && code1!=='GOLD_SJC' ? ['GOLD_SJC'] : []);
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
      const _cmpLim = (_histRange && _histRange !== 'ALL') ? `?limit=${({'1M':30,'3M':90,'6M':180,'1Y':365,'3Y':1095}[_histRange]||365)}` : '?limit=3650';
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
  const _gs = _goldData?.signals;
  const s1 = code1==='GOLD_SJC' ? _gs : ((_signals?.[code1])||(_marketData?.[code1])||(MOCK_SIGNALS?.[code1]));
  const s2 = code2==='GOLD_SJC' ? _gs : ((_signals?.[code2])||(_marketData?.[code2])||(MOCK_SIGNALS?.[code2]));
  if(!s1 && !s2) { panel.innerHTML=''; return; }
  const fmtI=(v,dec=2)=>v!=null?v.toFixed(dec):'—';
  const fP=v=>v==null?'—':`<span style="color:${v>=0?'var(--buy)':'var(--sell)'}">${v>=0?'+':''}${v.toFixed(2)}%</span>`;
  // Win: highlight the better value in bold; dim the weaker
  const win=(v1,v2,hi=true)=>{
    if(v1==null||v2==null) return ['',''];
    const w1=hi?v1>v2:v1<v2, w2=hi?v2>v1:v1>v2;
    return [w1?'font-weight:700;color:var(--txt)':'color:var(--txt3)', w2?'font-weight:700;color:var(--txt)':'color:var(--txt3)'];
  };
  const row=(label,v1,v2,hi=true,unit='',note='')=>{
    const [sy1,sy2]=win(v1,v2,hi);
    const f1=typeof v1==='number'?fmtI(v1)+unit:v1||'—';
    const f2=typeof v2==='number'?fmtI(v2)+unit:v2||'—';
    return `<tr>
      <td style="color:var(--txt3);font-size:11px;padding:6px 0;line-height:1.4">${label}${note?`<div style="font-size:9px;color:var(--txt3);font-weight:400">${note}</div>`:''}</td>
      <td style="font-family:var(--mono);font-size:12px;text-align:right;padding:6px 8px;${sy1}">${f1}</td>
      <td style="font-family:var(--mono);font-size:12px;text-align:right;padding:6px 0;${sy2}">${f2}</td>
    </tr>`;
  };
  const chgRow=(label,v1,v2,note='')=>`<tr>
    <td style="color:var(--txt3);font-size:11px;padding:6px 0">${label}${note?`<div style="font-size:9px;color:var(--txt3)">${note}</div>`:''}</td>
    <td style="font-size:12px;text-align:right;padding:6px 8px">${fP(v1)}</td>
    <td style="font-size:12px;text-align:right;padding:6px 0">${fP(v2)}</td>
  </tr>`;

  // ── Expert AM interpretation ──
  const _interp = () => {
    const insights = [];
    // 1. Return comparison
    const r30_1=s1?.chg30, r30_2=s2?.chg30;
    const r90_1=s1?.chg90, r90_2=s2?.chg90;
    if(r30_1!=null&&r30_2!=null) {
      const diff=r30_1-r30_2;
      if(Math.abs(diff)>1) insights.push({icon:diff>0?'📈':'📉',text:
        `<b>${diff>0?code1:code2}</b> vượt trội <b>${Math.abs(diff).toFixed(1)}%</b> trong 1 tháng qua. ${
          Math.abs(diff)>5 ? 'Khoảng cách lớn — có thể phản ánh sự khác biệt loại tài sản hoặc chiến lược đầu tư.' :
          'Khoảng cách vừa phải — theo dõi thêm để xác nhận xu hướng.'}`});
    }
    if(r90_1!=null&&r90_2!=null&&r30_1!=null&&r30_2!=null) {
      const w30=r30_1>r30_2?code1:code2, w90=r90_1>r90_2?code1:code2;
      if(w30!==w90) insights.push({icon:'🔄',text:
        `<b>${w30}</b> dẫn đầu ngắn hạn nhưng <b>${w90}</b> tốt hơn trung hạn. Đây là tín hiệu <b>phân kỳ xu hướng</b> — nhà đầu tư cần xem xét cả hai khung thời gian trước khi quyết định.`});
    }
    // 2. RSI comparison
    const rsi1=s1?.rsi, rsi2=s2?.rsi;
    if(rsi1!=null&&rsi2!=null) {
      if(rsi1<35&&rsi2>50) insights.push({icon:'💡',text:`<b>${code1}</b> đang ở vùng quá bán (RSI ${rsi1.toFixed(0)}) trong khi <b>${code2}</b> trung tính/mua (RSI ${rsi2.toFixed(0)}). Cơ hội mua ${code1} nếu tin vào phục hồi.`});
      else if(rsi2<35&&rsi1>50) insights.push({icon:'💡',text:`<b>${code2}</b> đang ở vùng quá bán (RSI ${rsi2.toFixed(0)}) trong khi <b>${code1}</b> trung tính/mua (RSI ${rsi1.toFixed(0)}). Cơ hội mua ${code2} nếu tin vào phục hồi.`});
      else if(rsi1>70&&rsi2<55) insights.push({icon:'⚠️',text:`<b>${code1}</b> đang quá mua (RSI ${rsi1.toFixed(0)}) — rủi ro điều chỉnh cao. <b>${code2}</b> (RSI ${rsi2.toFixed(0)}) an toàn hơn để mua mới.`});
      else if(rsi2>70&&rsi1<55) insights.push({icon:'⚠️',text:`<b>${code2}</b> đang quá mua (RSI ${rsi2.toFixed(0)}) — rủi ro điều chỉnh cao. <b>${code1}</b> (RSI ${rsi1.toFixed(0)}) an toàn hơn để mua mới.`});
    }
    // 3. Volatility / risk-adjusted
    const v1=s1?.vol_ann, v2=s2?.vol_ann;
    if(v1!=null&&v2!=null&&r90_1!=null&&r90_2!=null) {
      const sr1=v1>0?r90_1/v1:null, sr2=v2>0?r90_2/v2:null;
      if(sr1!=null&&sr2!=null&&Math.abs(sr1-sr2)>0.1) {
        const better=sr1>sr2?code1:code2;
        insights.push({icon:'⚖️',text:`Điều chỉnh theo rủi ro (Sharpe proxy 3T): <b>${better}</b> hiệu quả hơn — sinh lời cao hơn tương đối so với mức biến động. Đây là chỉ số quan trọng để so sánh quỹ cùng loại.`});
      } else if(Math.abs(v1-v2)>3) {
        const lower=v1<v2?code1:code2;
        insights.push({icon:'🛡️',text:`<b>${lower}</b> có biến động thấp hơn (${Math.min(v1,v2).toFixed(1)}% vs ${Math.max(v1,v2).toFixed(1)}%/năm). Phù hợp hơn cho nhà đầu tư thận trọng.`});
      }
    }
    // 4. Signal consensus
    const sig1=s1?.signal, sig2=s2?.signal;
    if(sig1&&sig2) {
      const both_buy=sig1.includes('MUA')&&sig2.includes('MUA');
      const both_sell=(sig1.includes('BÁN')||sig1.includes('BAN'))&&(sig2.includes('BÁN')||sig2.includes('BAN'));
      if(both_buy) insights.push({icon:'✅',text:`Cả hai đều có tín hiệu <b>MUA</b> — xác nhận xu hướng tích cực chung của thị trường. Có thể tăng tỷ trọng cả hai.`});
      else if(both_sell) insights.push({icon:'🔴',text:`Cả hai đều có tín hiệu <b>BÁN</b> — áp lực bán toàn diện. Thận trọng, chờ xác nhận đáy trước khi mua thêm.`});
    }
    if(!insights.length) insights.push({icon:'📊',text:'Hai tài sản đang hoạt động khá tương đồng. Theo dõi thêm để phát hiện sự phân kỳ có ý nghĩa.'});
    return insights.map(a=>`<div style="display:flex;gap:10px;align-items:flex-start;padding:10px 12px;background:var(--bg3);border-radius:8px;border-left:3px solid var(--bdr);margin-bottom:6px">
      <span style="font-size:16px;flex-shrink:0;line-height:1.3">${a.icon}</span>
      <span style="font-size:12px;color:var(--txt1);line-height:1.6">${a.text}</span>
    </div>`).join('');
  };

  const t2_1=s1?.t2_prediction, t2_2=s2?.t2_prediction;
  panel.innerHTML=`
  <div style="padding:12px 0 8px">
    <div style="font-family:var(--mono);font-size:10px;color:var(--txt3);letter-spacing:.08em;margin-bottom:10px">SO SÁNH CHỈ SỐ — <b style="color:var(--txt1)">ĐẬM = TỐT HƠN</b></div>
    <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
      <thead><tr>
        <th style="font-size:10px;color:var(--txt3);text-align:left;padding-bottom:8px;font-weight:400;border-bottom:1px solid var(--bdr)">Chỉ số</th>
        <th style="font-size:11px;color:var(--c0);text-align:right;padding-bottom:8px;font-family:var(--mono);border-bottom:1px solid var(--bdr)">${code1}</th>
        <th style="font-size:11px;color:#fbbf24;text-align:right;padding-bottom:8px;font-family:var(--mono);border-bottom:1px solid var(--bdr)">${code2}</th>
      </tr></thead>
      <tbody>
        ${chgRow('Hôm nay',s1?.chg_pct,s2?.chg_pct,'Biến động giá NAV trong ngày')}
        ${chgRow('1 tháng',s1?.chg30,s2?.chg30,'Tổng sinh lời 30 ngày gần nhất')}
        ${chgRow('3 tháng',s1?.chg90,s2?.chg90,'Tổng sinh lời 90 ngày gần nhất')}
        <tr><td colspan="3" style="border-top:1px solid var(--bdr);padding:2px 0"></td></tr>
        ${row('RSI (14 ngày)',s1?.rsi,s2?.rsi,false,'','<30: Quá bán · >70: Quá mua · Thấp hơn = mua tốt hơn')}
        ${row('BB %B',s1?.bb_pct??s1?.bb,s2?.bb_pct??s2?.bb,false,'%','0-20%: Sát dải dưới (rẻ) · 80-100%: Sát dải trên (đắt)')}
        ${row('Score tổng hợp',s1?.score,s2?.score,true,'','Thang điểm từ −6 đến +6 · Cao hơn = tín hiệu mua mạnh hơn')}
        ${s1?.vol_ann!=null||s2?.vol_ann!=null?row('Biến động/năm',s1?.vol_ann,s2?.vol_ann,false,'%','Độ lệch chuẩn hằng năm · Thấp hơn = ít rủi ro hơn'):''}
        <tr><td colspan="3" style="border-top:1px solid var(--bdr);padding:2px 0"></td></tr>
        <tr>
          <td style="color:var(--txt3);font-size:11px;padding:6px 0">Tín hiệu tổng hợp<div style="font-size:9px">Kết hợp RSI + BB + MACD + Score</div></td>
          <td style="text-align:right;padding:6px 8px"><span class="badge ${sigC(s1?.signal)}" style="font-size:10px;padding:2px 7px">${sigLabel(s1?.signal)||'—'}</span></td>
          <td style="text-align:right;padding:6px 0"><span class="badge ${sigC(s2?.signal)}" style="font-size:10px;padding:2px 7px">${sigLabel(s2?.signal)||'—'}</span></td>
        </tr>
        ${t2_1||t2_2?chgRow('Dự báo T+2',t2_1?.pct,t2_2?.pct,'Dự báo biến động NAV 2 ngày tới'):''}
      </tbody>
    </table>
    <div style="font-family:var(--mono);font-size:10px;color:var(--txt3);letter-spacing:.06em;margin-bottom:8px">PHÂN TÍCH CHUYÊN GIA</div>
    ${_interp()}
  </div>`;
}

function setHistRange(range, el) {
  _histRange = range;
  document.querySelectorAll('.hist-range-btn').forEach(b=>b.classList.remove('active'));
  if(el) el.classList.add('active');
  if(_histView==='cmp' && _histPageCode && _cmpCode2) loadComparisonView();
  else if(_histView==='t2') renderT2AccuracyChart(_histPageCode||Object.keys(MOCK_SIGNALS||{})[0]||'VESAF');
  else if(_histView==='gold') loadGoldHistory();
  else if(_histPageCode==='GOLD_SJC') loadGoldAnalysis();
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
  if(!container.children.length) addBulkNavRow(_histPageCode || '');
  const tag = document.getElementById('manual-nav-fund-tag');
  if(tag && _histPageCode) tag.textContent = `— ${_histPageCode}`;
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

// ── Analysis helpers ──────────────────────────────────────────────────────────
function _perfReturn(pts, calDays) {
  if (!pts?.length) return null;
  const last = pts[pts.length-1];
  const cut = new Date(last.date); cut.setDate(cut.getDate()-calDays);
  const cutStr = cut.toISOString().slice(0,10);
  const start = pts.find(p=>p.date>=cutStr);
  if (!start || start.date===last.date) return null;
  return (last.nav - start.nav) / start.nav * 100;
}
function _annVol(pts, n=252) {
  const tail = pts.slice(-Math.min(n, pts.length));
  if (tail.length < 10) return null;
  const r = [];
  for (let i=1;i<tail.length;i++) if(tail[i-1].nav>0) r.push((tail[i].nav-tail[i-1].nav)/tail[i-1].nav);
  if (r.length < 5) return null;
  const m = r.reduce((a,b)=>a+b,0)/r.length;
  return Math.sqrt(r.reduce((a,b)=>a+(b-m)**2,0)/r.length * 252)*100;
}
function _maxDrawdown(pts) {
  if (!pts?.length) return 0;
  let peak=0, dd=0;
  for(const p of pts){if(p.nav>peak)peak=p.nav; const d=peak>0?(peak-p.nav)/peak:0; if(d>dd)dd=d;}
  return dd*100;
}
function _sharpe(pts, n=252, rf=3.5) {
  const tail = pts.slice(-Math.min(n,pts.length));
  if(tail.length<10) return null;
  const rfD = rf/100/252;
  const r = [];
  for(let i=1;i<tail.length;i++) if(tail[i-1].nav>0) r.push((tail[i].nav-tail[i-1].nav)/tail[i-1].nav - rfD);
  if(r.length<5) return null;
  const m=r.reduce((a,b)=>a+b,0)/r.length;
  const s2=r.reduce((a,b)=>a+b**2,0)/r.length - m**2;
  if(s2<=0) return null;
  return m/Math.sqrt(s2)*Math.sqrt(252);
}
function _sortino(pts, n=252, rf=4.5) {
  const tail = pts.slice(-Math.min(n,pts.length));
  if (tail.length < 10) return null;
  const rfD = rf/100/252;
  const r = [];
  for (let i=1;i<tail.length;i++) if(tail[i-1].nav>0) r.push((tail[i].nav-tail[i-1].nav)/tail[i-1].nav);
  if (r.length < 5) return null;
  const annRet = r.reduce((a,b)=>a+b,0)/r.length*252;
  const downR = r.map(v => Math.min(v - rfD, 0));
  const downVar = downR.reduce((a,v)=>a+v**2,0)/downR.length;
  if (downVar <= 0) return null;
  return (annRet - rf/100) / Math.sqrt(downVar * 252);
}
function _calmar(pts, n=756) {
  const tail = pts.slice(-Math.min(n,pts.length));
  if (tail.length < 10) return null;
  const r = [];
  for (let i=1;i<tail.length;i++) if(tail[i-1].nav>0) r.push((tail[i].nav-tail[i-1].nav)/tail[i-1].nav);
  const annRet = r.reduce((a,b)=>a+b,0)/r.length*252;
  const mdd = _maxDrawdown(tail);
  if (mdd <= 0) return null;
  return annRet / (mdd/100);
}
function _smartPredict(pts, horizon=2) {
  if(!pts||pts.length<10) return null;
  const tail = pts.slice(-30);
  const n = tail.length;
  const xs=tail.map((_,i)=>i), ys=tail.map(p=>p.nav);
  const mx=xs.reduce((a,b)=>a+b,0)/n, my=ys.reduce((a,b)=>a+b,0)/n;
  const cov=xs.reduce((s,x,i)=>s+(x-mx)*(ys[i]-my),0);
  const vx=xs.reduce((s,x)=>s+(x-mx)**2,0);
  const slope=vx?cov/vx:0;
  const regNav = my + slope*(n-1+horizon - mx);
  const mom5 = n>5 ? tail[n-1].nav + (tail[n-1].nav-tail[n-6].nav)/5*horizon : regNav;
  const mom3 = n>3 ? tail[n-1].nav + (tail[n-1].nav-tail[n-4].nav)/3*horizon : regNav;
  return regNav*0.5 + mom5*0.3 + mom3*0.2;
}
function _savePrediction(code, predNav, predDate) {
  try {
    const key=`ftp_pred_${code}`;
    const hist=JSON.parse(localStorage.getItem(key)||'[]');
    const today=new Date().toISOString().slice(0,10);
    if(!hist.find(p=>p.predDate===predDate&&p.madeOn===today))
      hist.push({predNav, predDate, madeOn:today});
    if(hist.length>50) hist.splice(0, hist.length-50);
    localStorage.setItem(key, JSON.stringify(hist));
  } catch(e){}
}
function _checkPredAccuracy(code, actualPts) {
  try {
    const key=`ftp_pred_${code}`;
    const hist=JSON.parse(localStorage.getItem(key)||'[]');
    const navMap={}; actualPts.forEach(p=>{ navMap[p.date]=p.nav; });
    let verified=0;
    hist.forEach(p=>{
      if(navMap[p.predDate]&&!p.actualNav){ p.actualNav=navMap[p.predDate]; verified++; }
    });
    if(verified>0) localStorage.setItem(key, JSON.stringify(hist));
    const allV=hist.filter(p=>p.actualNav);
    if(!allV.length) return null;
    const errs=allV.map(p=>Math.abs((p.predNav-p.actualNav)/p.actualNav*100));
    return {mae: errs.reduce((a,b)=>a+b,0)/errs.length, count: allV.length};
  } catch(e){ return null; }
}

// ── Analysis panel below chart ─────────────────────────────────────────────────
function _mkSect(title, icon, body) {
  return `<div style="margin-bottom:16px">
    <div style="font-size:13px;font-family:var(--mono);color:var(--txt1);letter-spacing:.05em;margin-bottom:10px;display:flex;align-items:center;gap:6px;border-bottom:1px solid var(--bdr);padding-bottom:6px">
      <span>${icon}</span><span style="font-weight:700">${title}</span>
    </div>${body}</div>`;
}
function _mkRow(label, value, sub='') {
  return `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--bdr)">
    <span style="font-size:13px;color:var(--txt2)">${label}</span>
    <div style="text-align:right">
      <div style="font-family:var(--mono);font-size:14px;font-weight:600">${value}</div>
      ${sub?`<div style="font-size:11px;color:var(--txt3);margin-top:1px">${sub}</div>`:''}
    </div>
  </div>`;
}
function _mkMetric(label, val, color, hint) {
  return `<div style="background:var(--bg3);border-radius:8px;padding:12px 8px;text-align:center">
    <div style="font-size:12px;color:var(--txt3);margin-bottom:5px;line-height:1.3">${label}</div>
    <div style="font-family:var(--mono);font-size:19px;font-weight:700;color:${color}">${val}</div>
    ${hint?`<div style="font-size:12px;color:${color};margin-top:5px;line-height:1.4">${hint}</div>`:''}
  </div>`;
}
function _mkPerfRow(label, pct, sub='') {
  if (pct == null) return _mkRow(label, '—', sub);
  const color = pct >= 0 ? 'var(--buy)' : 'var(--sell)';
  const barW = Math.min(Math.abs(pct) / 25 * 50, 50);
  return `<div style="padding:8px 0;border-bottom:1px solid var(--bdr)">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:13px;color:var(--txt2)">${label}</span>
      <span style="font-family:var(--mono);font-size:14px;font-weight:700;color:${color}">${pct>=0?'+':''}${pct.toFixed(2)}%</span>
    </div>
    <div style="height:3px;background:var(--bdr);border-radius:2px;margin-top:5px;position:relative">
      <div style="position:absolute;${pct>=0?'left:50%':'right:50%'};width:${barW}%;height:100%;background:${color};border-radius:2px"></div>
    </div>
    ${sub?`<div style="font-size:11px;color:var(--txt3);margin-top:3px">${sub}</div>`:''}
  </div>`;
}

function _renderHistAnalysis(code) {
  const panel = document.getElementById('hist-analysis-panel'); if(!panel) return;
  const s = (_signals?.[code]) || (_marketData?.[code]) || (MOCK_SIGNALS?.[code]);
  const pfItem = _me?.portfolio?.items?.find(h=>h.code===code);
  const pts = _histPageData || [];

  // Helper: colour a percentage
  const pctColor = v => v == null ? 'var(--txt2)' : v >= 0 ? 'var(--buy)' : 'var(--sell)';
  const pctFmt  = v => v == null ? '\u2013' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
  const pF = v => v == null
    ? '<span style="color:var(--txt3)">\u2013</span>'
    : `<span style="color:${pctColor(v)};font-family:var(--mono);font-weight:700">${pctFmt(v)}</span>`;

  const curr = pts.length ? pts[pts.length - 1].nav : (s?.nav || 0);

  if (!s && !pfItem && pts.length < 5) {
    panel.innerHTML = `<div style="color:var(--txt2);font-size:12px;padding:24px;text-align:center;line-height:1.7">
      <div style="font-size:28px;margin-bottom:10px">\u{1F4CA}</div>
      <div style="color:var(--txt1);font-weight:600;font-family:var(--mono);font-size:13px;margin-bottom:8px">${code}</div>
      <div>Ch\u01b0a \u0111\u1ee7 d\u1eef li\u1ec7u \u0111\u1ec3 ph\u00e2n t\u00edch.<br><span style="font-size:10px;color:var(--txt3)">C\u1ea7n \u00edt nh\u1ea5t 20 ng\u00e0y NAV l\u1ecbch s\u1eed.</span></div>
    </div>`;
    return;
  }

  // ── Fund type meta ──
  const fundType = s?.fund_type || 'equity';
  const techRel  = s?.tech_reliability || 'MEDIUM';
  const ftLabel  = {equity:'Qu\u1ef9 C\u1ed5 Phi\u1ebfu',bond:'Qu\u1ef9 Tr\u00e1i Phi\u1ebfu',balanced:'Qu\u1ef9 C\u00e2n B\u1eb1ng',money_market:'Qu\u1ef9 Ti\u1ec1n T\u1ec7'}[fundType] || 'Qu\u1ef9 M\u1edf';
  const ftColor  = {equity:'var(--buy)',bond:'#60a5fa',balanced:'#a78bfa',money_market:'#facc15'}[fundType] || 'var(--c0)';
  const relColor = {HIGH:'var(--buy)',MEDIUM:'#facc15',LOW:'var(--sell)','N/A':'var(--txt2)'}[techRel] || '#facc15';
  const relLabel = {HIGH:'Ph\u00f9 h\u1ee3p cao',MEDIUM:'Ph\u00f9 h\u1ee3p v\u1eeba',LOW:'Ph\u00f9 h\u1ee3p th\u1ea5p','N/A':'Kh\u00f4ng \u00e1p d\u1ee5ng'}[techRel] || 'V\u1eeba';

  // ── 1. HEADER ──
  const fundName = s?.name || code;
  const headerHtml = `<div style="background:linear-gradient(135deg,var(--bg2),var(--bg3));border-radius:10px;padding:12px 14px;margin-bottom:12px;border-left:3px solid ${ftColor}">
    <div style="display:flex;justify-content:space-between;align-items:flex-start">
      <div>
        <div style="font-family:var(--mono);font-size:16px;font-weight:700;color:var(--c0)">${code}</div>
        <div style="font-size:12px;color:var(--txt2);margin-top:2px">${fundName !== code ? esc(fundName) : ''}</div>
      </div>
      <div style="text-align:right">
        <div style="font-family:var(--mono);font-size:16px;font-weight:700">${fmt(Math.round(curr))} \u0111</div>
        <div style="font-size:11px;color:var(--txt3)">${s?.nav_date || ''}</div>
      </div>
    </div>
    <div style="display:flex;gap:6px;margin-top:10px;flex-wrap:wrap;align-items:center">
      <span style="font-size:11px;background:${ftColor}22;color:${ftColor};border:1px solid ${ftColor}44;border-radius:4px;padding:3px 8px;font-family:var(--mono)">${ftLabel}</span>
      <span style="font-size:11px;background:${relColor}22;color:${relColor};border:1px solid ${relColor}44;border-radius:4px;padding:3px 8px">TA: ${relLabel}</span>
      ${pts.length ? `<span style="font-size:10px;color:var(--txt3);padding:2px 6px">${pts.length} ng\u00e0y</span>` : ''}
      <button class="hist-cmp-btn" onclick="setHistView('cmp',document.getElementById('hist-view-cmp'))" style="margin-left:auto;font-size:11px;padding:3px 10px" title="So s\u00e1nh 2 qu\u1ef9">\u2696\ufe0f So S\u00e1nh</button>
    </div>
    ${techRel === 'LOW' ? `<div style="margin-top:8px;font-size:10px;color:#60a5fa;line-height:1.5;background:#60a5fa11;border-radius:6px;padding:6px 8px">\u2139 Qu\u1ef9 tr\u00e1i phi\u1ebfu NAV t\u0103ng \u0111\u1ec1u \u2014 RSI/BB/MACD k\u00e9m hi\u1ec7u qu\u1ea3 h\u01a1n qu\u1ef9 c\u1ed5 phi\u1ebfu. T\u00edn hi\u1ec7u ch\u1ec9 c\u00f3 gi\u00e1 tr\u1ecb khi c\u00f3 bi\u1ebfn \u0111\u1ed9ng b\u1ea5t th\u01b0\u1eddng.</div>` : ''}
    ${techRel === 'N/A' ? `<div style="margin-top:8px;font-size:10px;color:#facc15;line-height:1.5;background:#facc1511;border-radius:6px;padding:6px 8px">\u2139 Qu\u1ef9 ti\u1ec1n t\u1ec7 ho\u1ea1t \u0111\u1ed9ng nh\u01b0 g\u1eedi ti\u1ebft ki\u1ec7m \u2014 NAV t\u0103ng \u1ed5n \u0111\u1ecbnh m\u1ed7i ng\u00e0y, ph\u00e2n t\u00edch k\u1ef9 thu\u1eadt kh\u00f4ng c\u00f3 \u00fd ngh\u0129a.</div>` : ''}
  </div>`;

  // ── 2. PORTFOLIO POSITION ──
  let pnlHtml = '';
  if (pfItem) {
    const nav = curr || pfItem.nav || 0;
    const units = pfItem.units || 0, cost = pfItem.cost || 0;
    const avgCost = pfItem.avg_cost || (units > 0 ? cost / units : 0);
    const mktVal = nav * units, pnl = mktVal - cost, pnlP = cost > 0 ? pnl / cost * 100 : 0;
    const t2p = s?.t2_prediction;
    pnlHtml = _mkSect('V\u1ecb TH\u1ebe \u0110ANG N\u1eafM GI\u1eef', '\u{1F4BC}', `
      <div style="background:var(--bg3);border-radius:8px;padding:12px 14px">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px 16px;margin-bottom:${t2p ? '10px' : '0'}">
          <div><div style="font-size:14px;color:var(--txt3)">Gi\u00e1 tr\u1ecb th\u1ecb tr\u01b0\u1eddng</div><div style="font-family:var(--mono);font-size:14px;font-weight:700">${(mktVal / 1e6).toFixed(2)}M \u0111</div></div>
          <div><div style="font-size:14px;color:var(--txt3)">L\u00e3i / L\u1ed7</div>
            <div class="pnl ${pnlC(pnlP)}" style="font-family:var(--mono);font-size:14px;font-weight:700">${pnl >= 0 ? '+' : ''}${(pnl / 1e6).toFixed(2)}M</div>
            <div style="font-size:14px;color:${pctColor(pnlP)}">(${pctFmt(pnlP)})</div>
          </div>
          <div><div style="font-size:14px;color:var(--txt3)">S\u1ed1 CCQ</div><div style="font-family:var(--mono);font-size:14px">${units.toFixed(4)}</div></div>
          <div><div style="font-size:14px;color:var(--txt3)">Gi\u00e1 v\u1ed1n b\u00ecnh qu\u00e2n</div><div style="font-family:var(--mono);font-size:14px">${fmt(Math.round(avgCost))} \u0111/CCQ</div></div>
        </div>
        ${t2p ? `<div style="border-top:1px solid var(--bdr);padding-top:8px;display:flex;justify-content:space-between;align-items:center">
          <span style="font-size:14px;color:var(--txt2)">D\u1ef1 b\u00e1o T+2 (gi\u00e1 tr\u1ecb danh m\u1ee5c)</span>
          <span style="font-family:var(--mono);font-size:14px;font-weight:700;color:${pctColor(t2p.pct)}">${t2p.pct >= 0 ? '+' : ''}${(t2p.pct || 0).toFixed(2)}% \u2248 ${((mktVal * (1 + t2p.pct / 100)) / 1e6).toFixed(2)}M \u0111</span>
        </div>` : ''}
      </div>
      ${(() => {
        const _sc = s?.score || 0;
        if (pnlP < -5) {
          const _toBreak = avgCost > 0 && curr > 0 ? ((avgCost - curr) / curr * 100) : 0;
          const _dcaHint = _sc >= 3
            ? ' Tín hiệu kỹ thuật tích cực — có thể DCA thêm để giảm giá vốn bình quân.'
            : _sc <= -3 ? ' Tín hiệu tiêu cực — chưa nên mua thêm, chờ xác nhận đảo chiều.'
            : ' Tín hiệu trung lập — chỉ DCA lượng nhỏ nếu tin vào quỹ dài hạn.';
          const _recovMo = s?.chg30 != null && s.chg30 > 0.1 ? Math.ceil(_toBreak / s.chg30) : null;
          const _recovNote = _recovMo != null
            ? ` Ở đà hiện tại (+${s.chg30.toFixed(1)}%/tháng), ước tính ~${_recovMo} tháng để hoà vốn.`
            : (s?.chg30 != null && s.chg30 < -0.05 ? ' Quỹ đang tiếp tục giảm — chưa thể ước tính thời gian phục hồi.' : '');
          return `<div style="background:var(--sell)11;border:1px solid var(--sell)33;border-radius:8px;padding:8px 12px;margin-top:8px;font-size:14px;color:var(--txt2)"><b style="color:var(--sell)">Hòa vốn:</b> cần NAV tăng +${_toBreak.toFixed(1)}% (về ${fmt(Math.round(avgCost))}đ/CCQ).${_dcaHint}${_recovNote}</div>`;
        }
        if (pnlP > 15 && _sc <= -3) return `<div style="background:#facc1511;border:1px solid #facc1533;border-radius:8px;padding:8px 12px;margin-top:8px;font-size:14px;color:var(--txt2)"><b style="color:#facc15">Đang lãi ${pnlP.toFixed(1)}%</b> — tín hiệu kỹ thuật đang tiêu cực. Cân nhắc chốt lời một phần để bảo vệ thành quả.</div>`;
        if (pnlP > 20) return `<div style="background:#4ade8011;border:1px solid #4ade8033;border-radius:8px;padding:8px 12px;margin-top:8px;font-size:14px;color:var(--txt2)"><b style="color:var(--buy)">Lãi tốt (${pnlP.toFixed(1)}%)</b>${_sc >= 3 ? ' — tín hiệu vẫn tốt, có thể tiếp tục nắm.' : ' — cân nhắc đặt mức chốt lời bảo vệ (trailing stop).'}</div>`;
        return '';
      })()}
      `);
  }

  // ── 3. PERFORMANCE ──
  const p7=_perfReturn(pts,7), p30=_perfReturn(pts,30), p90=_perfReturn(pts,90);
  const p180=_perfReturn(pts,180), p365=_perfReturn(pts,365), p3y=_perfReturn(pts,1095);
  const d30  = p30  ?? s?.chg30;
  const d90  = p90  ?? s?.chg90;
  const d180 = p180 ?? s?.chg180;
  const d365 = p365 ?? s?.chg1y;
  // Annualized returns
  const ann1y = d365;
  const ann3y = p3y != null ? (Math.pow(1 + p3y/100, 1/3) - 1) * 100 : null;
  // Consistency: % of weeks positive (from pts)
  const _navValsEarly = pts.map(p => p.nav); // navVals is defined later in section 5b
  let posWeeks = 0, totalWeeks = 0;
  for (let i = 7; i < _navValsEarly.length; i += 7) {
    totalWeeks++;
    if (_navValsEarly[i] > _navValsEarly[i-7]) posWeeks++;
  }
  const consistencyPct = totalWeeks >= 4 ? Math.round(posWeeks / totalWeeks * 100) : null;
  const consistencyLabel = consistencyPct == null ? null
    : consistencyPct >= 70 ? 'Rất ổn định' : consistencyPct >= 55 ? 'Ổn định' : consistencyPct >= 45 ? 'Dao động' : 'Không ổn định';
  const consistencyC = consistencyPct == null ? 'var(--txt2)'
    : consistencyPct >= 70 ? 'var(--buy)' : consistencyPct >= 45 ? '#facc15' : 'var(--sell)';
  // Cross-fund peer ranking (same fund type, from _signals)
  const allSigVals = Object.entries(_signals || {});
  const sameFtSigs = allSigVals.filter(([,fs]) => fs.fund_type === fundType);
  const rank30 = d30 != null ? sameFtSigs.filter(([,fs]) => (fs.chg30??-999) > d30).length + 1 : null;
  const total30 = sameFtSigs.filter(([,fs]) => fs.chg30 != null).length;
  const rank7  = p7 != null  ? sameFtSigs.filter(([,fs]) => (fs.chg7 ??-999) > p7 ).length + 1 : null;
  const total7  = sameFtSigs.filter(([,fs]) => fs.chg7  != null).length;
  const rankPctile30 = rank30 != null && total30 > 0 ? Math.round((1 - rank30/total30) * 100) : null;
  const rankLabel30  = rankPctile30 == null ? '' : rankPctile30 >= 80 ? 'Top 20%' : rankPctile30 >= 60 ? 'Trên trung bình' : rankPctile30 >= 40 ? 'Trung bình' : rankPctile30 >= 20 ? 'Dưới trung bình' : 'Thấp';
  const rankC30 = rankPctile30 == null ? 'var(--txt2)' : rankPctile30 >= 80 ? 'var(--buy)' : rankPctile30 >= 40 ? '#facc15' : 'var(--sell)';
  const _d30ann = d30 != null ? d30 * 12 : null;
  const _d90ann = d90 != null ? d90 *  4 : null;
  const _momTrend = (_d30ann != null && _d90ann != null && Math.abs(_d30ann - _d90ann) > 1)
    ? (_d30ann > _d90ann ? 'accelerating' : 'decelerating') : null;
  const _momC = _momTrend === 'accelerating' ? 'var(--buy)' : 'var(--sell)';
  const _momLabel = _momTrend === 'accelerating' ? '▲ Đà tăng tốc' : '▼ Đà giảm tốc';
  const _momDesc = _momTrend === 'accelerating'
    ? (_d30ann > 0 && _d90ann <= 0
      ? `Đảo chiều tích cực: ngắn hạn dương (+${_d30ann.toFixed(1)}%/năm) sau giai đoạn kém hiệu quả (${_d90ann.toFixed(1)}%/năm).`
      : `Ngắn hạn (${_d30ann>=0?'+':''}${_d30ann.toFixed(1)}%/năm) vượt trung hạn (${_d90ann>=0?'+':''}${_d90ann.toFixed(1)}%/năm) — quỹ đang lấy lại đà.`)
    : _momTrend === 'decelerating'
    ? (_d30ann <= 0 && _d90ann > 0
      ? `Cảnh báo: ngắn hạn (${_d30ann.toFixed(1)}%/năm) đã âm trong khi trung hạn vẫn dương (${_d90ann>=0?'+':''}${_d90ann.toFixed(1)}%/năm). Theo dõi kỹ.`
      : `Ngắn hạn (${_d30ann>=0?'+':''}${_d30ann.toFixed(1)}%/năm) kém trung hạn (${_d90ann>=0?'+':''}${_d90ann.toFixed(1)}%/năm) — đà tăng đang giảm dần.`)
    : '';
  const _vsBankDiff = d365 != null ? d365 - 4.5 : null;
  const _vsBankC = _vsBankDiff == null ? 'var(--txt2)' : _vsBankDiff >= 2 ? 'var(--buy)' : _vsBankDiff >= 0 ? '#facc15' : 'var(--sell)';
  // Extreme 7-day move alert (bond: >8%, equity/balanced: >15%)
  const _extremeThresh = (fundType === 'bond' || fundType === 'money_market') ? 8 : 15;
  const _extremeMove7 = p7 != null && Math.abs(p7) > _extremeThresh;
  // WEB-044: 5-day regression trend forecast (linear regression on last 30 pts)
  const _fcast5d = (() => {
    if (pts.length < 15) return null;
    const _t = pts.slice(-30), _n = _t.length;
    const _xs = _t.map((_,i)=>i), _ys = _t.map(p=>p.nav);
    const _mx = _xs.reduce((a,b)=>a+b,0)/_n, _my = _ys.reduce((a,b)=>a+b,0)/_n;
    const _cov = _xs.reduce((s,x,i)=>s+(x-_mx)*(_ys[i]-_my),0);
    const _vx = _xs.reduce((s,x)=>s+(x-_mx)**2,0);
    if (!_vx) return null;
    return _my + (_cov/_vx)*(_n-1+5-_mx);
  })();
  const _fcast5Pct = (_fcast5d && curr > 0) ? (_fcast5d - curr) / curr * 100 : null;
  const _fcast5C = _fcast5Pct == null ? 'var(--txt2)' : _fcast5Pct > 0 ? 'var(--buy)' : 'var(--sell)';
  // WEB-047: Multi-timeframe return consistency
  const _tfRets = [p7, d30, d90, d365].filter(v => v != null);
  const _tfPos = _tfRets.filter(v => v > 0).length;
  const _tfNeg = _tfRets.filter(v => v < 0).length;
  const _tfTotal = _tfRets.length;
  // WEB-052: Longest consecutive gain/loss streaks + current streak
  const _streaks = (() => {
    if (pts.length < 20) return null;
    const navs = pts.map(p => p.nav);
    let wS = 0, lS = 0, mW = 0, mL = 0, mWE = -1, mLE = -1;
    for (let i = 1; i < navs.length; i++) {
      if (navs[i] > navs[i-1]) { wS++; lS = 0; if (wS > mW) { mW = wS; mWE = i; } }
      else if (navs[i] < navs[i-1]) { lS++; wS = 0; if (lS > mL) { mL = lS; mLE = i; } }
      else { wS = 0; lS = 0; }
    }
    let cS = 0, cDir = 0;
    for (let i = navs.length - 1; i >= 1; i--) {
      const d = navs[i] > navs[i-1] ? 1 : navs[i] < navs[i-1] ? -1 : 0;
      if (i === navs.length - 1) { cDir = d; cS = d !== 0 ? 1 : 0; }
      else if (d === cDir && d !== 0) cS++;
      else break;
    }
    const _fd = d => d && d.length >= 10 ? d.slice(8,10)+'/'+d.slice(5,7)+'/'+d.slice(2,4) : '';
    return { mW, mL, cS, cDir,
      mWFrom: mWE >= mW ? _fd(pts[mWE - mW]?.date) : '', mWTo: mWE >= 0 ? _fd(pts[mWE]?.date) : '',
      mLFrom: mLE >= mL ? _fd(pts[mLE - mL]?.date) : '', mLTo: mLE >= 0 ? _fd(pts[mLE]?.date) : '' };
  })();
  const perfHtml = _mkSect('HIỆU SUẤT ĐẦU TƯ', '\u{1F4C8}', `
    <div style="background:var(--bg3);border-radius:8px;overflow:hidden;padding:2px 12px 4px">
      ${_mkPerfRow('7 ngày gần nhất', p7, rank7 != null && total7 > 1 ? `Hạng #${rank7}/${total7} ${ftLabel.replace('Quỹ ','')}` : '')}
      ${_mkPerfRow('1 tháng', d30, rank30 != null && total30 > 1 ? `Hạng #${rank30}/${total30} ${ftLabel.replace('Quỹ ','')} · ${rankLabel30}` : '')}
      ${_mkPerfRow('3 tháng', d90)}
      ${_mkPerfRow('6 tháng', d180)}
      ${_mkPerfRow('1 năm', d365, ann1y != null ? `Lợi nhuận hàng năm (không ghép lãi)` : '')}
      ${p3y != null ? _mkPerfRow('3 năm (gộp)', p3y, ann3y != null ? `Kép: ${ann3y>=0?'+':''}${ann3y.toFixed(1)}%/năm` : '') : ''}
    </div>
    ${_momTrend ? `<div style="background:${_momC}11;border:1px solid ${_momC}33;border-radius:8px;padding:8px 12px;margin-top:8px;display:flex;justify-content:space-between;align-items:center;gap:10px"><div style="flex:1"><div style="font-size:14px;font-weight:600;color:${_momC};margin-bottom:2px">${_momLabel}</div><div style="font-size:14px;color:var(--txt2);line-height:1.4">${_momDesc}</div></div><div style="text-align:right;flex-shrink:0"><div style="font-size:14px;color:var(--txt3)">1 tháng (quy đổi/năm)</div><div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${_momC}">${_d30ann>=0?'+':''}${_d30ann.toFixed(1)}%</div></div></div>` : ''}
    ${_vsBankDiff != null ? `<div style="background:${_vsBankC}11;border:1px solid ${_vsBankC}33;border-radius:8px;padding:8px 12px;margin-top:8px;display:flex;justify-content:space-between;align-items:center"><div><div style="font-size:14px;color:var(--txt2)">So với lãi tiết kiệm 4.5%/năm</div><div style="font-size:14px;color:var(--txt3)">Benchmark phi rủi ro · lãi ngân hàng kỳ hạn 12T ước tính</div></div><div style="text-align:right"><div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${_vsBankC}">${_vsBankDiff >= 0 ? '+' : ''}${_vsBankDiff.toFixed(1)}%</div><div style="font-size:14px;color:${_vsBankC}">${_vsBankDiff >= 5 ? 'Vượt trội rõ ràng — đáng đầu tư hơn gửi tiết kiệm' : _vsBankDiff >= 0 ? 'Nhỉnh hơn lãi ngân hàng' : 'Kém lãi ngân hàng — xem xét lại hiệu quả'}</div></div></div>` : ''}
    ${(rank30 != null && total30 > 1) ? `<div style="background:${rankC30}11;border:1px solid ${rankC30}33;border-radius:8px;padding:10px 12px;margin-top:8px;display:flex;align-items:center;gap:10px">
      <div style="font-size:22px;font-family:var(--mono);font-weight:700;color:${rankC30}">#${rank30}</div>
      <div>
        <div style="font-size:14px;font-weight:600;color:${rankC30}">${rankLabel30} trong nhóm ${ftLabel}</div>
        <div style="font-size:14px;color:var(--txt3)">1 tháng · xếp hạng trong ${total30} quỹ ${ftLabel.replace('Quỹ ','')} đang theo dõi</div>
      </div>
      ${rankPctile30 != null ? `<div style="margin-left:auto;text-align:right"><div style="font-size:14px;color:var(--txt3)">Đánh bại</div><div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${rankC30}">${rankPctile30}% quỹ</div></div>` : ''}
    </div>` : ''}
    ${consistencyPct != null ? `<div style="background:var(--bg3);border-radius:8px;padding:8px 12px;margin-top:8px;display:flex;justify-content:space-between;align-items:center">
      <div>
        <div style="font-size:14px;color:var(--txt2)">Tỷ lệ tuần tăng</div>
        <div style="font-size:14px;color:var(--txt3)">NAV tuần sau > tuần trước · ${totalWeeks} tuần đã đo</div>
      </div>
      <div style="text-align:right">
        <div style="font-family:var(--mono);font-size:16px;font-weight:700;color:${consistencyC}">${consistencyPct}%</div>
        <div style="font-size:14px;color:${consistencyC}">${consistencyLabel}</div>
      </div>
    </div>` : ''}
    ${_extremeMove7 ? `<div style="background:#f8717111;border:1px solid #f8717133;border-radius:8px;padding:10px 12px;margin-top:8px">
      <div style="font-size:14px;font-weight:700;color:var(--sell)">⚠️ BIẾN ĐỘNG BẤT THƯỜNG 7 NGÀY</div>
      <div style="font-size:14px;color:var(--txt2);margin-top:4px">NAV ${p7 != null && p7 > 0 ? 'tăng vọt' : 'giảm mạnh'} ${p7 != null ? Math.abs(p7).toFixed(1) : '?'}% trong 7 ngày — vượt xa mức bình thường của quỹ loại này (ngưỡng ${_extremeThresh}%). Kiểm tra nguyên nhân (thị trường chung, thay đổi fund manager, corporate action) trước khi ra quyết định giao dịch.</div>
    </div>` : ''}
    ${_fcast5Pct != null ? '<div style="background:' + _fcast5C + '11;border:1px solid ' + _fcast5C + '33;border-radius:8px;padding:8px 12px;margin-top:8px;display:flex;justify-content:space-between;align-items:center">'
      + '<div><div style="font-size:14px;color:var(--txt2)">Dự đoán xu hướng 5 ngày tới</div><div style="font-size:14px;color:var(--txt3)">Tính theo đà giá 30 ngày gần nhất · chỉ mang tính tham khảo</div></div>'
      + '<div style="text-align:right"><div style="font-family:var(--mono);font-size:14px;font-weight:700;color:' + _fcast5C + '">' + (_fcast5Pct >= 0 ? '+' : '') + _fcast5Pct.toFixed(2) + '%</div>'
      + '<div style="font-size:14px;color:' + _fcast5C + '">≈ ' + fmt(Math.round(_fcast5d)) + ' đ</div></div></div>' : ''}
    ${_tfTotal >= 2 ? (() => {
      const _frames = [['7 ngày', p7], ['1 tháng', d30], ['3 tháng', d90], ['1 năm', d365]].filter(([, v]) => v != null);
      const _vC = _tfPos === _tfTotal ? 'var(--buy)' : _tfNeg === _tfTotal ? 'var(--sell)' : _tfPos > _tfNeg ? 'var(--buy)' : _tfPos < _tfNeg ? 'var(--sell)' : '#facc15';
      const _verdict = _tfPos === _tfTotal ? 'Nhất quán tăng trên tất cả khung' : _tfNeg === _tfTotal ? 'Nhất quán giảm trên tất cả khung' : _tfPos > _tfNeg ? 'Nghiêng về tăng (' + _tfPos + '/' + _tfTotal + ' khung dương)' : _tfPos < _tfNeg ? 'Nghiêng về giảm (' + _tfNeg + '/' + _tfTotal + ' khung âm)' : 'Tín hiệu hỗn hợp — phân kỳ ngắn/dài hạn';
      return '<div style="background:var(--bg3);border-radius:8px;padding:8px 12px;margin-top:8px">'
        + '<div style="font-size:14px;color:var(--txt2);margin-bottom:5px">Nhìn chung qua nhiều khung thời gian</div>'
        + '<div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:4px">'
        + _frames.map(([l, v]) => '<span style="font-size:14px;background:' + (v > 0 ? '#4ade8022' : '#f8717122') + ';color:' + (v > 0 ? 'var(--buy)' : 'var(--sell)') + ';border-radius:4px;padding:2px 7px;font-family:var(--mono)">' + l + ' ' + (v > 0 ? '▲' : '▼') + '</span>').join('')
        + '</div><div style="font-size:14px;color:' + _vC + '">' + _verdict + '</div></div>';
    })() : ''}
    ${_streaks ? `<div style="background:var(--bg3);border-radius:8px;padding:8px 12px;margin-top:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
        <div style="font-size:14px;color:var(--txt2)">Chuỗi tăng dài nhất: <b style="color:var(--buy)">${_streaks.mW} ngày</b>${_streaks.mWFrom ? ' (' + _streaks.mWFrom + ' → ' + _streaks.mWTo + ')' : ''}</div>
        <div style="font-size:14px;color:var(--txt2)">Chuỗi giảm dài nhất: <b style="color:var(--sell)">${_streaks.mL} ngày</b>${_streaks.mLFrom ? ' (' + _streaks.mLFrom + ' → ' + _streaks.mLTo + ')' : ''}</div>
      </div>
      ${_streaks.cS >= 2 ? `<div style="font-size:14px;color:var(--txt3);margin-top:4px">Đang trong chuỗi <b style="color:${_streaks.cDir > 0 ? 'var(--buy)' : 'var(--sell)'}">${_streaks.cDir > 0 ? 'tăng' : 'giảm'} ${_streaks.cS} ngày liên tiếp</b></div>` : ''}
    </div>` : ''}
    <div style="margin-top:6px;font-size:14px;color:var(--txt3);line-height:1.5">Hiệu suất = % thay đổi NAV theo thời gian. Chưa tính phí mua/bán hoặc thuế. Xếp hạng so với các quỹ cùng loại trong danh sách đang theo dõi.</div>`);

  // ── 4. RISK METRICS ──
  const vol = _annVol(pts) ?? s?.vol_ann;
  // Current drawdown from 52-week peak (different from all-time mdd)
  const _cutDd52 = new Date(); _cutDd52.setDate(_cutDd52.getDate()-365);
  const _cutDd52S = _cutDd52.toISOString().slice(0,10);
  const _pts52r   = pts.filter(p => p.date >= _cutDd52S);
  const _peak52r  = _pts52r.length ? _pts52r.reduce((m,p)=>p.nav>m?p.nav:m,0) : 0;
  const _curDD52  = _peak52r > curr && curr > 0 ? (_peak52r - curr) / _peak52r * 100 : 0;
  const mdd = _maxDrawdown(pts);
  const sr      = _sharpe(pts, 252, 4.5);
  const sortino = _sortino(pts, 252, 4.5);
  const calmar  = _calmar(pts);
  // Monthly VaR 95% — 5th percentile of 21-day rolling returns
  const var95 = (() => {
    const navs = pts.map(p=>p.nav);
    if (navs.length < 25) return null;
    const r21 = [];
    for (let i=21; i<navs.length; i++) if(navs[i-21]>0) r21.push((navs[i]-navs[i-21])/navs[i-21]*100);
    if (r21.length < 10) return null;
    r21.sort((a,b)=>a-b);
    return -r21[Math.floor(r21.length * 0.05)]; // positive = loss
  })();
  const volC     = vol == null     ? 'var(--txt2)' : vol < 8       ? 'var(--buy)' : vol < 18    ? '#facc15' : 'var(--sell)';
  const mddC     = mdd < 5         ? 'var(--buy)'  : mdd < 15      ? '#facc15'    : 'var(--sell)';
  const srC      = sr == null      ? 'var(--txt2)' : sr > 1        ? 'var(--buy)' : sr > 0      ? '#facc15' : 'var(--sell)';
  const sortinoC = sortino == null ? 'var(--txt2)' : sortino > 1.5 ? 'var(--buy)' : sortino > 0.5 ? '#facc15' : 'var(--sell)';
  const calmarC  = calmar == null  ? 'var(--txt2)' : calmar > 0.5  ? 'var(--buy)' : calmar > 0  ? '#facc15' : 'var(--sell)';
  const var95C   = var95 == null   ? 'var(--txt2)' : var95 < 3     ? 'var(--buy)' : var95 < 8   ? '#facc15' : 'var(--sell)';
  const volDesc    = vol == null    ? '\u2014' : vol < 8      ? 'R\u1ea5t th\u1ea5p'   : vol < 12    ? 'Th\u1ea5p'    : vol < 20  ? 'Trung b\u00ecnh' : 'Cao';
  const mddDesc    = mdd < 5        ? 'R\u1ee7i ro th\u1ea5p' : mdd < 15    ? 'Trung b\u00ecnh' : 'R\u1ee7i ro cao';
  const srDesc     = sr == null     ? '\u2014' : sr > 1.5     ? 'Xu\u1ea5t s\u1eafc'  : sr > 1      ? 'T\u1ed1t'     : sr > 0    ? 'Ch\u1ea5p nh\u1eadn' : 'K\u00e9m';
  const sortinoDesc = sortino == null ? '\u2014' : sortino > 1.5 ? 'Xu\u1ea5t s\u1eafc (it l\u1ed7)' : sortino > 0.5 ? '\u1ed4n \u0111\u1ecbnh' : sortino > 0 ? 'Trung b\u00ecnh' : 'K\u00e9m';
  const calmarDesc  = calmar == null  ? '\u2014' : calmar > 1  ? 'R\u1ea5t t\u1ed1t' : calmar > 0 ? 'Ch\u1ea5p nh\u1eadn' : 'K\u00e9m';
  const var95Desc   = var95 == null   ? '\u2014' : var95 < 3   ? 'R\u1ee7i ro th\u1ea5p' : var95 < 8 ? 'Trung b\u00ecnh' : 'C\u1ea7n ch\u00fa \u00fd';
  // WEB-041: Volatility regime \u2014 short-term vs long-term vol comparison
  const _vol30d    = pts.length >= 32 ? _annVol(pts.slice(-30)) : null;
  const _volRegime = (vol != null && _vol30d != null && vol > 1.5) ? _vol30d / vol : null;
  // WEB-046: Drawdown recovery statistics — identify historical episodes ≥5%
  const _ddStats = (() => {
    if (pts.length < 60) return null;
    const navs = pts.map(p => p.nav);
    const eps = [];
    let pk = navs[0], pkI = 0, trN = navs[0], trI = 0, inDD = false;
    for (let i = 1; i < navs.length; i++) {
      if (navs[i] > pk) {
        if (inDD) {
          const dp = (pk - trN) / pk * 100;
          if (dp >= 5) eps.push({ dp, dur: trI - pkI, rec: i - trI });
          inDD = false;
        }
        pk = navs[i]; pkI = i; trN = navs[i]; trI = i;
      } else if (navs[i] < trN) {
        trN = navs[i]; trI = i;
        if ((pk - trN) / pk * 100 >= 5) inDD = true;
      }
    }
    if (inDD) { const dp = (pk - trN) / pk * 100; if (dp >= 5) eps.push({ dp, dur: trI - pkI, rec: null }); }
    if (!eps.length) return null;
    const wR = eps.filter(e => e.rec !== null);
    return { count: eps.length, avgDp: eps.reduce((s,e)=>s+e.dp,0)/eps.length,
      maxDp: Math.max(...eps.map(e=>e.dp)), avgRec: wR.length ? Math.round(wR.reduce((s,e)=>s+e.rec,0)/wR.length) : null,
      maxDur: Math.max(...eps.map(e=>e.dur)), hasOpen: eps.some(e=>e.rec===null) };
  })();
  // WEB-048: Return distribution moments \u2014 skewness and excess kurtosis of daily returns
  const _retDist = (() => {
    if (pts.length < 60) return null;
    const navs = pts.map(p => p.nav);
    const rets = [];
    for (let i = 1; i < navs.length; i++) if (navs[i-1] > 0) rets.push((navs[i] - navs[i-1]) / navs[i-1]);
    const n = rets.length;
    if (n < 30) return null;
    const mu = rets.reduce((s,r) => s+r, 0) / n;
    const sd = Math.sqrt(rets.reduce((s,r) => s + (r-mu)**2, 0) / n);
    if (sd < 1e-10) return null;
    const skew = rets.reduce((s,r) => s + ((r-mu)/sd)**3, 0) / n;
    const kurt = rets.reduce((s,r) => s + ((r-mu)/sd)**4, 0) / n - 3;
    return { skew, kurt };
  })();
  // WEB-049: Best and worst 30-day rolling windows across full history
  const _bestWorst30 = (() => {
    if (pts.length < 35) return null;
    let bR = -Infinity, wR = Infinity, bI = -1, wI = -1;
    for (let i = 30; i < pts.length; i++) {
      if (pts[i-30].nav <= 0) continue;
      const r = (pts[i].nav - pts[i-30].nav) / pts[i-30].nav * 100;
      if (r > bR) { bR = r; bI = i; }
      if (r < wR) { wR = r; wI = i; }
    }
    if (bI < 0 || wI < 0) return null;
    const _fd = d => d && d.length >= 10 ? d.slice(8,10)+'/'+d.slice(5,7)+'/'+d.slice(2,4) : '';
    return { bR, wR, bFrom: _fd(pts[bI-30]?.date), bTo: _fd(pts[bI]?.date), wFrom: _fd(pts[wI-30]?.date), wTo: _fd(pts[wI]?.date) };
  })();
  // WEB-050: Daily win rate + gain-pain ratio
  const _winRate = (() => {
    if (pts.length < 30) return null;
    const navs = pts.map(p => p.nav);
    let ups = 0, downs = 0, sumUp = 0, sumDown = 0;
    for (let i = 1; i < navs.length; i++) {
      if (navs[i-1] <= 0) continue;
      const r = (navs[i] - navs[i-1]) / navs[i-1] * 100;
      if (r > 0) { ups++; sumUp += r; }
      else if (r < 0) { downs++; sumDown += Math.abs(r); }
    }
    const total = ups + downs;
    if (total < 10) return null;
    const avgUp = ups > 0 ? sumUp / ups : 0;
    const avgDown = downs > 0 ? sumDown / downs : 0;
    return { winRate: ups / total * 100, avgUp, avgDown, gainPain: avgDown > 0 ? avgUp / avgDown : null, ups, total };
  })();
  // WEB-051: Historical vol percentile \u2014 where current 30d vol sits vs full history
  const _volPctile = (() => {
    if (pts.length < 90 || _vol30d == null) return null;
    const vols = [];
    for (let i = 30; i <= pts.length; i += 5) vols.push(_annVol(pts.slice(i - 30, i)));
    const valid = vols.filter(v => v != null);
    if (valid.length < 5) return null;
    valid.sort((a, b) => a - b);
    const pctile = valid.filter(v => v <= _vol30d).length / valid.length * 100;
    return { pctile: Math.round(pctile), min: valid[0], max: valid[valid.length - 1] };
  })();
  const riskHtml = pts.length > 30 ? _mkSect('R\u1ee6I RO & CH\u1ea4T L\u01af\u1ee2NG', '\u{1F6E1}\uFE0F', `
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:10px">
      ${_mkMetric('Dao \u0111\u1ed9ng gi\u00e1', vol != null ? vol.toFixed(1) + '%' : '\u2013', volC, volDesc)}
      ${_mkMetric('T\u1eebng l\u1ed7 t\u1ed1i \u0111a', mdd > 0 ? '-' + mdd.toFixed(1) + '%' : '\u2013', mddC, mddDesc)}
      ${_mkMetric('L\u00e3i/R\u1ee7i ro', sr != null ? sr.toFixed(2) : '\u2013', srC, srDesc)}
      ${_mkMetric('\u1ed4n \u0111\u1ecbnh khi gi\u1ea3m', sortino != null ? sortino.toFixed(2) : '\u2013', sortinoC, sortinoDesc)}
      ${_mkMetric('Ph\u1ee5c h\u1ed3i sau l\u1ed7', calmar != null ? calmar.toFixed(2) : '\u2013', calmarC, calmarDesc)}
      ${_mkMetric('M\u1ea5t nhi\u1ec1u nh\u1ea5t 1T', var95 != null ? '-' + var95.toFixed(1) + '%' : '\u2013', var95C, var95Desc)}
    </div>
    <div style="background:var(--bg3);border-radius:8px;padding:10px 12px;font-size:14px;color:var(--txt2);line-height:1.9">
      <b style="color:var(--txt1)">\ud83c\udfa2 Dao \u0111\u1ed9ng gi\u00e1</b> \u2014 Gi\u00e1 qu\u1ef9 l\u00ean xu\u1ed1ng nhi\u1ec1u hay \u00edt trong 1 n\u0103m. D\u01b0\u1edbi 8% = y\u00ean t\u00e2m ng\u1ee7 ngon. Tr\u00ean 18% = c\u1ea3m gi\u00e1c nh\u01b0 \u0111i t\u00e0u l\u01b0\u1ee3n \u2014 c\u00f3 c\u01a1 h\u1ed9i l\u1eddi to nh\u01b0ng c\u0169ng d\u1ec5 l\u1ed7 n\u1eb7ng.<br>
      <b style="color:var(--txt1)">\ud83d\udcc9 T\u1eebng l\u1ed7 t\u1ed1i \u0111a</b> \u2014 Bao gi\u1edd \u0111\u00f3, gi\u00e1 qu\u1ef9 xu\u1ed1ng th\u1ea5p nh\u1ea5t bao nhi\u00eau tr\u01b0\u1edbc khi h\u1ed3i ph\u1ee5c. V\u00ed d\u1ee5 -15% ngh\u0129a l\u00e0 c\u00f3 l\u00fac b\u1ea1n s\u1ebd th\u1ea5y t\u00e0i kho\u1ea3n \u0111\u1ecf -15%. <i>B\u1ea1n c\u00f3 ch\u1ecbu \u0111\u01b0\u1ee3c kh\u00f4ng th\u00ec m\u1edbi n\u00ean \u0111\u1ea7u t\u01b0.</i><br>
      <b style="color:var(--txt1)">\u2696\ufe0f L\u00e3i/R\u1ee7i ro</b> \u2014 C\u1ee9 m\u1ed7i % r\u1ee7i ro b\u1ea1n ch\u1ea5p nh\u1eadn, qu\u1ef9 tr\u1ea3 l\u1ea1i bao nhi\u00eau l\u1ee3i nhu\u1eadn so v\u1edbi g\u1eedi ng\u00e2n h\u00e0ng. Tr\u00ean 1 = x\u1ee9ng \u0111\u00e1ng r\u1ee7i ro. D\u01b0\u1edbi 0 = ch\u01b0a b\u1eb1ng g\u1eedi ti\u1ebft ki\u1ec7m 4.5%/n\u0103m.<br>
      <b style="color:var(--txt1)">\ud83d\udee1\ufe0f \u1ed4n \u0111\u1ecbnh khi gi\u1ea3m</b> \u2014 Qu\u1ef9 c\u00f3 hay b\u1ecb gi\u1ea3m s\u1ed1c \u0111\u1ed9t ng\u1ed9t kh\u00f4ng? Tr\u00ean 1.5 = r\u1ea5t t\u1ed1t, t\u0103ng \u0111\u1ec1u \u00edt b\u1ecb "c\u00fa gi\u1eadt". D\u01b0\u1edbi 0.5 = hay c\u00f3 nh\u1eefng \u0111\u1ee3t gi\u1ea3m b\u1ea5t ng\u1edd.<br>
      <b style="color:var(--txt1)">\ud83d\udd01 Ph\u1ee5c h\u1ed3i sau l\u1ed7</b> \u2014 M\u1ed7i khi qu\u1ef9 b\u1ecb gi\u1ea3m, n\u00f3 h\u1ed3i ph\u1ee5c nhanh hay ch\u1eadm? Tr\u00ean 1 = h\u1ed3i ph\u1ee5c nhanh, l\u1eddi nhi\u1ec1u h\u01a1n l\u1ed7. D\u01b0\u1edbi 0 = \u0111ang c\u00f2n \u0111\u1ee9ng trong v\u00f9ng l\u1ed7 so v\u1edbi ng\u00e2n h\u00e0ng.<br>
      <b style="color:var(--txt1)">\ud83d\ude2c M\u1ea5t nhi\u1ec1u nh\u1ea5t 1 th\u00e1ng</b> \u2014 Trong nh\u1eefng th\u00e1ng x\u1ea5u nh\u1ea5t (5% tr\u01b0\u1eddng h\u1ee3p t\u1ec7 nh\u1ea5t theo l\u1ecbch s\u1eed), qu\u1ef9 t\u1eebng m\u1ea5t bao nhi\u00eau % trong 1 th\u00e1ng. Con s\u1ed1 n\u00e0y gi\u00fap b\u1ea1n bi\u1ebft m\u00ecnh c\u1ea7n chu\u1ea9n b\u1ecb t\u00e2m l\u00fd \u0111\u1ebfn \u0111\u00e2u.
    </div>
    ${sr != null ? `<div style="background:${sr>1?'var(--buy)':sr>0?'#facc15':'var(--sell)'}11;border:1px solid ${sr>1?'var(--buy)':sr>0?'#facc15':'var(--sell)'}33;border-radius:8px;padding:10px 12px;margin-top:8px"><div style="font-size:14px;font-weight:600;color:${sr>1?'var(--buy)':sr>0?'#facc15':'var(--sell)'};margin-bottom:4px">📋 Nhận xét tổng thể về mức độ an toàn</div><div style="font-size:14px;color:var(--txt2);line-height:1.7">${sr > 1 ? '✅ Quỹ sinh lời tốt so với mức rủi ro phải chịu — đáng đầu tư hơn so với gửi tiết kiệm ngân hàng (4.5%/năm).' : sr > 0 ? '🟡 Quỹ có lãi nhưng mức dao động giá chưa được bù đắp xứng đáng. Vẫn hơn gửi ngân hàng nhưng cần chấp nhận giá lên xuống nhiều.' : '⚠️ Quỹ này chưa sinh lời tốt hơn gửi tiết kiệm ngân hàng (4.5%/năm) sau khi tính rủi ro. Nên cân nhắc lại hoặc chờ thêm.'}${mdd > 20 ? ` Từng có lúc giảm tới <b style="color:var(--sell)">${mdd.toFixed(1)}%</b> — bạn cần tâm lý vững để không hoảng loạn bán tháo.` : mdd > 10 ? ` Từng giảm tới ${mdd.toFixed(1)}% — mức độ trung bình, phù hợp nhà đầu tư trung hạn.` : ` Chưa bao giờ giảm quá ${mdd.toFixed(1)}% — khá ổn định.`}${sortino != null && sortino > 1.5 ? ' Quỹ có xu hướng tăng đều, ít bị giảm sốc bất ngờ.' : sortino != null && sortino < 0 ? ' Quỹ hay bị giảm nhiều hơn tăng — cần chú ý.' : ''}${_curDD52 > 5 ? ` Hiện tại giá đang thấp hơn đỉnh năm ngoái <b style="color:var(--sell)">${_curDD52.toFixed(1)}%</b> — nếu mua từ đỉnh, bạn đang lỗ ${_curDD52.toFixed(1)}% ở thời điểm này.` : _curDD52 > 1 ? ` Hiện đang thấp hơn đỉnh năm ngoái ${_curDD52.toFixed(1)}% — mức bình thường.` : ''}${calmar != null && calmar < 10 ? (calmar > 1 ? ` Sau mỗi đợt giảm, quỹ phục hồi khá nhanh.` : calmar > 0.3 ? ` Quỹ phục hồi ở mức chấp nhận được sau mỗi đợt giảm.` : calmar >= 0 ? ` Quỹ phục hồi chậm sau các đợt giảm — cần kiên nhẫn.` : '') : ''}</div></div>` : ''}
    ${var95 != null ? `<div style="background:var(--bg3);border-radius:8px;padding:8px 12px;margin-top:8px;font-size:14px;color:var(--txt2);line-height:1.6"><b style="color:var(--txt1)">😬 Nên đầu tư bao nhiêu % tiền?</b> — Trong tháng xấu nhất (5% trường hợp tệ nhất theo lịch sử), quỹ này có thể mất tới <b style="color:${var95C}">${var95.toFixed(1)}%</b>. Nếu bạn không muốn toàn bộ danh mục bị ảnh hưởng quá 2%, thì chỉ nên để tối đa <b style="color:var(--c0)">~${Math.min(99, Math.round(2/var95*100))}% tổng tiền</b> vào quỹ này.</div>` : ''}
    ${_volRegime != null && _volRegime > 1.4 ? `<div style="background:#f8717111;border:1px solid #f8717133;border-radius:8px;padding:8px 12px;margin-top:8px;font-size:14px;color:var(--txt2);line-height:1.6">⚡ <b style="color:var(--sell)">Giá đang dao động mạnh hơn bình thường</b> — 30 ngày qua giá lên xuống mạnh gấp ${_volRegime.toFixed(1)} lần so với thường ngày. Nên mua từng lần nhỏ, tránh đổ tiền lớn một lúc trong giai đoạn này.</div>` : _volRegime != null && _volRegime < 0.6 ? `<div style="background:#4ade8011;border:1px solid #4ade8033;border-radius:8px;padding:8px 12px;margin-top:8px;font-size:14px;color:var(--txt2);line-height:1.6">✅ <b style="color:var(--buy)">Giá đang rất ổn định</b> — 30 ngày qua ít dao động hơn bình thường. Thời điểm thuận lợi để vào lệnh nếu bạn đã quyết định đầu tư.</div>` : ''}
    ${_ddStats ? '<div style="background:var(--bg3);border-radius:8px;padding:10px 12px;margin-top:8px">'
      + '<div style="font-size:14px;font-weight:600;color:var(--txt1);margin-bottom:6px">📉 Lịch sử Drawdown (≥5%)</div>'
      + '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px">'
      + _mkMetric('Số đợt', String(_ddStats.count), 'var(--c0)', _ddStats.hasOpen ? 'Có đợt đang mở' : 'Đã hồi phục hết')
      + _mkMetric('Sâu nhất', '-' + _ddStats.maxDp.toFixed(1) + '%', 'var(--sell)', 'Đỉnh → Đáy')
      + _mkMetric('Phục hồi TB', _ddStats.avgRec != null ? _ddStats.avgRec + ' ngày' : '—', 'var(--buy)', _ddStats.avgRec != null ? 'Sau khi chạm đáy' : 'Chưa có dữ liệu')
      + '</div>'
      + '<div style="font-size:14px;color:var(--txt2);margin-top:6px;line-height:1.5">'
      + (_ddStats.avgRec != null
        ? 'TB mỗi đợt giảm <b style="color:var(--sell)">' + _ddStats.avgDp.toFixed(1) + '%</b>, kéo dài <b>' + _ddStats.maxDur + ' ngày</b>. Phục hồi trung bình <b style="color:var(--buy)">' + _ddStats.avgRec + ' ngày</b> sau đáy' + (_ddStats.hasOpen ? ' (đang có đợt chưa phục hồi).' : '.')
        : (_ddStats.hasOpen ? 'Đang trong đợt drawdown chưa phục hồi hoàn toàn trong dữ liệu lịch sử.' : ''))
      + '</div></div>' : ''}
    ${_retDist ? '<div style="background:var(--bg3);border-radius:8px;padding:10px 12px;margin-top:8px">'
      + '<div style="font-size:14px;font-weight:600;color:var(--txt1);margin-bottom:6px">📊 Phân phối lợi nhuận hàng ngày</div>'
      + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">'
      + _mkMetric('Skewness', _retDist.skew.toFixed(2), Math.abs(_retDist.skew) < 0.5 ? 'var(--txt2)' : _retDist.skew > 0 ? 'var(--buy)' : 'var(--sell)', Math.abs(_retDist.skew) < 0.5 ? 'Gần chuẩn' : _retDist.skew > 0.5 ? 'Lệch dương' : 'Lệch âm')
      + _mkMetric('Excess Kurtosis', _retDist.kurt.toFixed(2), Math.abs(_retDist.kurt) < 1 ? 'var(--txt2)' : _retDist.kurt > 0 ? '#facc15' : 'var(--buy)', _retDist.kurt > 1 ? 'Fat-tailed' : _retDist.kurt < -1 ? 'Thin-tailed' : 'Bình thường')
      + '</div>'
      + '<div style="font-size:14px;color:var(--txt2);margin-top:6px;line-height:1.5">'
      + (_retDist.skew < -0.5 ? '⚠️ Lệch âm (Skew ' + _retDist.skew.toFixed(2) + ') — rủi ro đuôi trái: cú giảm mạnh đột ngột xảy ra thường hơn cú tăng đột biến.' : _retDist.skew > 0.5 ? '✅ Lệch dương (Skew ' + _retDist.skew.toFixed(2) + ') — cú tăng đột biến thỉnh thoảng xảy ra, không bị chi phối bởi đuôi giảm.' : 'Phân phối lợi nhuận gần đối xứng (Skew ' + _retDist.skew.toFixed(2) + ') — rủi ro cân đối 2 chiều.')
      + (_retDist.kurt > 1 ? ' Kurtosis cao (' + _retDist.kurt.toFixed(2) + ') — fat-tailed: cú sốc cực đoan xảy ra thường hơn phân phối chuẩn dự báo.' : _retDist.kurt < -1 ? ' Kurtosis thấp (' + _retDist.kurt.toFixed(2) + ') — ít cú sốc cực đoan.' : '')
      + '</div></div>' : ''}
    ${_winRate ? '<div style="background:var(--bg3);border-radius:8px;padding:10px 12px;margin-top:8px">'
      + '<div style="font-size:14px;font-weight:600;color:var(--txt1);margin-bottom:6px">🏆 Tỷ lệ thắng/thua hàng ngày</div>'
      + '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px">'
      + _mkMetric('Ngày tăng', _winRate.winRate.toFixed(0) + '%', _winRate.winRate >= 55 ? 'var(--buy)' : _winRate.winRate >= 45 ? '#facc15' : 'var(--sell)', _winRate.ups + '/' + _winRate.total + ' ngày')
      + _mkMetric('Lãi TB ngày +', '+' + _winRate.avgUp.toFixed(3) + '%', 'var(--buy)', 'Mỗi ngày tăng')
      + _mkMetric('Gain/Pain', _winRate.gainPain != null ? _winRate.gainPain.toFixed(2) : '—', _winRate.gainPain == null ? 'var(--txt2)' : _winRate.gainPain >= 1.2 ? 'var(--buy)' : _winRate.gainPain >= 0.8 ? '#facc15' : 'var(--sell)', _winRate.gainPain == null ? '' : _winRate.gainPain >= 1.2 ? 'Hiệu quả tốt' : _winRate.gainPain >= 0.8 ? 'Trung bình' : 'Kém hiệu quả')
      + '</div>'
      + '<div style="font-size:14px;color:var(--txt2);margin-top:6px;line-height:1.5">'
      + (_winRate.gainPain != null
        ? (_winRate.gainPain >= 1.2 ? 'Gain/Pain ' + _winRate.gainPain.toFixed(2) + ' — quỹ kiếm nhiều hơn lỗ trên từng ngày giao dịch: mỗi ngày tăng bù đắp tốt các ngày giảm.'
          : _winRate.gainPain >= 0.8 ? 'Gain/Pain ' + _winRate.gainPain.toFixed(2) + ' — gần cân bằng: lãi và lỗ hàng ngày bù trừ tương đương nhau.'
          : 'Gain/Pain ' + _winRate.gainPain.toFixed(2) + ' — mỗi ngày giảm gây thiệt hại lớn hơn lợi ích từ ngày tăng: quỹ cần nhiều ngày xanh để bù đắp.')
        : '')
      + '</div></div>' : ''}
    ${_volPctile ? '<div style="background:var(--bg3);border-radius:8px;padding:8px 12px;margin-top:8px;font-size:14px;color:var(--txt2);line-height:1.6">'
      + '<b style="color:var(--txt1)">Phân vị biến động lịch sử</b> — Biến động 30 ngày hiện tại <b style="color:' + (_volPctile.pctile >= 75 ? 'var(--sell)' : _volPctile.pctile <= 25 ? 'var(--buy)' : '#facc15') + '">' + _vol30d.toFixed(1) + '%/năm</b> cao hơn <b>' + _volPctile.pctile + '%</b> giai đoạn lịch sử của quỹ'
      + ' (min: ' + _volPctile.min.toFixed(1) + '%, max: ' + _volPctile.max.toFixed(1) + '%).'
      + (_volPctile.pctile >= 75 ? ' Đang ở vùng biến động cao — rủi ro lớn hơn bình thường.' : _volPctile.pctile <= 25 ? ' Đang ở vùng biến động thấp — ổn định hơn lịch sử.' : ' Biến động ở mức trung bình so với lịch sử.')
      + '</div>' : ''}
`) : '';
  // ── 5. 52-WEEK RANGE ──
  const cut52D = new Date(); cut52D.setDate(cut52D.getDate() - 365);
  const cut52 = cut52D.toISOString().slice(0, 10);
  const nav52 = pts.filter(p => p.date >= cut52);
  const hi52 = nav52.length ? Math.max(...nav52.map(p => p.nav)) : curr;
  const lo52 = nav52.length ? Math.min(...nav52.map(p => p.nav)) : curr;
  const pct52 = hi52 > lo52 ? Math.round((curr - lo52) / (hi52 - lo52) * 100) : 50;
  const _up52 = hi52 > curr ? ((hi52 - curr) / curr * 100) : 0;
  const _dn52 = curr > lo52 ? ((curr - lo52) / curr * 100) : 0;
  const _rr52 = _dn52 > 0.1 ? (_up52 / _dn52) : null;
  const pct52Desc = pct52 < 20
    ? `Giá đang ở vùng THẤP trong năm qua — có thể tăng thêm +${_up52.toFixed(1)}% để về đỉnh, nhưng chỉ còn cách đáy −${_dn52.toFixed(1)}%. Tiềm năng tăng lớn hơn rủi ro giảm${_rr52 ? ` (${_rr52.toFixed(1)} lần)` : ''}. Có thể xem xét mua nếu không có tin xấu.`
    : pct52 > 80
    ? `Giá đang ở vùng CAO trong năm qua — còn có thể tăng thêm +${_up52.toFixed(1)}% nữa, nhưng nếu giảm có thể xuống −${_dn52.toFixed(1)}%. Rủi ro giảm cao hơn tiềm năng tăng${_rr52 ? ` (${_rr52.toFixed(1)} lần)` : ''}. Cẩn thận khi mua thêm lúc này.`
    : `Giá đang ở VÙNG TRUNG BÌNH trong năm qua — có thể tăng thêm +${_up52.toFixed(1)}% hoặc giảm −${_dn52.toFixed(1)}%${_rr52 ? `. Tiềm năng tăng ${_rr52>=1.5?'thuận lợi hơn':_rr52<1?'kém hơn':'gần ngang bằng'} rủi ro giảm` : ''}.`
  const _lo52Pt = nav52.length ? nav52.reduce((m,p) => p.nav <= m.nav ? p : m, nav52[0]) : null;
  const _hi52Pt = nav52.length ? nav52.reduce((m,p) => p.nav >= m.nav ? p : m, nav52[0]) : null;
  const _fmtD52 = d => d && d.length >= 10 ? d.slice(8,10)+'/'+d.slice(5,7) : '';
  const rangeHtml = nav52.length > 10 ? _mkSect('V\u00d9NG GI\u00c1 52 TU\u1ea6N', '\u{1F4CF}', `
    <div style="background:var(--bg3);border-radius:8px;padding:12px 14px">
      <div style="display:flex;justify-content:space-between;font-size:14px;color:var(--txt3);margin-bottom:8px">
        <span style="display:inline-flex;flex-direction:column"><span>\u0110\u00e1y: <b style="color:var(--sell);font-family:var(--mono)">${fmt(Math.round(lo52))}</b></span><span style="font-size:14px;color:var(--txt3);font-family:var(--mono)">${_fmtD52(_lo52Pt?.date)}</span></span>
        <span>Hi\u1ec7n t\u1ea1i: <b style="color:var(--c0);font-family:var(--mono)">${fmt(Math.round(curr))}</b></span>
        <span style="display:inline-flex;flex-direction:column;align-items:flex-end"><span>\u0110\u1ec9nh: <b style="color:var(--buy);font-family:var(--mono)">${fmt(Math.round(hi52))}</b></span><span style="font-size:14px;color:var(--txt3);font-family:var(--mono);text-align:right">${_fmtD52(_hi52Pt?.date)}</span></span>
      </div>
      <div style="height:10px;background:linear-gradient(90deg,var(--sell)33,#facc1533,var(--buy)33);border-radius:5px;position:relative;margin-bottom:8px">
        <div style="position:absolute;top:-3px;left:calc(${pct52}% - 8px);width:16px;height:16px;background:var(--c0);border-radius:50%;border:2px solid var(--bg);box-shadow:0 0 6px var(--c0)"></div>
      </div>
      <div style="font-size:14px;color:var(--txt2);text-align:center">${pct52}% t\u1eeb \u0111\u00e1y \u2014 ${pct52Desc}</div>
      ${_bestWorst30 ? `<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px">
        ${_mkMetric('30 ng\u00e0y t\u1ed1t nh\u1ea5t', '+' + _bestWorst30.bR.toFixed(1) + '%', 'var(--buy)', _bestWorst30.bFrom + ' \u2192 ' + _bestWorst30.bTo)}
        ${_mkMetric('30 ng\u00e0y t\u1ec7 nh\u1ea5t', _bestWorst30.wR.toFixed(1) + '%', 'var(--sell)', _bestWorst30.wFrom + ' \u2192 ' + _bestWorst30.wTo)}
      </div>` : ''}
    </div>`) : '';

  // ── 5b. ADVANCED TECHNICAL ANALYSIS ──
  const _ma = (arr, n) => arr.length >= n ? arr.slice(-n).reduce((a,b)=>a+b,0)/n : null;
  const navVals = pts.map(p=>p.nav);
  const ma20val = _ma(navVals, 20);
  const ma50val = _ma(navVals, 50);
  const ma20prev = navVals.length >= 21 ? _ma(navVals.slice(0,-1), 20) : null;
  const ma50prev = navVals.length >= 51 ? _ma(navVals.slice(0,-1), 50) : null;
  // MA crossover detection
  let maCrossSignal = null;
  if (ma20val && ma50val && ma20prev && ma50prev) {
    if (ma20prev <= ma50prev && ma20val > ma50val) maCrossSignal = 'golden';
    else if (ma20prev >= ma50prev && ma20val < ma50val) maCrossSignal = 'death';
    else if (ma20val > ma50val) maCrossSignal = 'above';
    else maCrossSignal = 'below';
  }
  // Bollinger Band Width (volatility)
  const bbW = (() => {
    if (navVals.length < 20) return null;
    const last20 = navVals.slice(-20);
    const m = last20.reduce((a,b)=>a+b,0)/20;
    const std = Math.sqrt(last20.reduce((a,v)=>a+(v-m)**2,0)/20);
    const prev20 = navVals.length >= 40 ? navVals.slice(-40,-20) : null;
    const prevW = prev20 ? (() => { const pm=prev20.reduce((a,b)=>a+b,0)/20; const ps=Math.sqrt(prev20.reduce((a,v)=>a+(v-pm)**2,0)/20); return 4*ps/pm*100; })() : null;
    const currW = 4*std/m*100;
    return {curr:currW, prev:prevW, expanding: prevW ? currW > prevW : null};
  })();
  // Fibonacci levels from 52-week range
  const fibLevels = nav52.length > 10 ? [0,23.6,38.2,50,61.8,78.6,100].map(f => ({
    f, nav: lo52 + (hi52-lo52)*f/100,
    label: f===0?'Đáy 52T':f===100?'Đỉnh 52T':`Fib ${f}%`
  })) : [];
  const nearFib = fibLevels.filter(fl => Math.abs(curr-fl.nav)/Math.max(curr,1) < 0.015);
  // RSI Divergence — proper implementation using historical RSI at local extrema
  const _rsiAt = (arr, endIdx, period=14) => {
    const slice = arr.slice(Math.max(0, endIdx - period - 1), endIdx + 1);
    if (slice.length < period + 1) return null;
    let gains = 0, losses = 0;
    for (let i = 1; i <= period; i++) {
      const d = slice[i] - slice[i-1];
      if (d > 0) gains += d; else losses -= d;
    }
    const avgG = gains / period, avgL = losses / period;
    return avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
  };
  const _findExtrema = (arr, lookback=5) => {
    const minima = [], maxima = [];
    for (let i = lookback; i < arr.length - lookback; i++) {
      let isMin = true, isMax = true;
      for (let j = i - lookback; j <= i + lookback; j++) {
        if (j !== i) { if (arr[j] <= arr[i]) isMin = false; if (arr[j] >= arr[i]) isMax = false; }
      }
      if (isMin) minima.push(i);
      if (isMax) maxima.push(i);
    }
    return {minima, maxima};
  };
  let rsiDivergence = null, rsiDivergenceDesc = '';
  if (pts.length >= 40) {
    const _d60 = navVals.slice(-60), _d60off = navVals.length - _d60.length;
    const {minima: _dMin, maxima: _dMax} = _findExtrema(_d60, 5);
    if (_dMin.length >= 2) {
      const m1 = _dMin[_dMin.length-2], m2 = _dMin[_dMin.length-1];
      const r1 = _rsiAt(navVals, _d60off+m1), r2 = _rsiAt(navVals, _d60off+m2);
      if (r1!=null && r2!=null && _d60[m2] < _d60[m1]*0.998 && r2 > r1+4) {
        rsiDivergence = 'bullish';
        rsiDivergenceDesc = `Áp lực bán suy yếu: giá tạo đáy mới thấp hơn nhưng RSI ở đáy mới cao hơn (${r2.toFixed(0)} > ${r1.toFixed(0)}) — tín hiệu đảo chiều tăng.`;
      }
    }
    if (!rsiDivergence && _dMax.length >= 2) {
      const mx1 = _dMax[_dMax.length-2], mx2 = _dMax[_dMax.length-1];
      const r1 = _rsiAt(navVals, _d60off+mx1), r2 = _rsiAt(navVals, _d60off+mx2);
      if (r1!=null && r2!=null && _d60[mx2] > _d60[mx1]*1.002 && r2 < r1-4) {
        rsiDivergence = 'bearish';
        rsiDivergenceDesc = `Đà mua cạn kiệt: giá tạo đỉnh mới cao hơn nhưng RSI ở đỉnh mới thấp hơn (${r2.toFixed(0)} < ${r1.toFixed(0)}) — cảnh báo đảo chiều giảm.`;
      }
    }
  }
  const advHtml = pts.length >= 20 ? _mkSect('PHÂN TÍCH KỸ THUẬT NÂNG CAO', '🔬', `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
      ${ma20val ? `<div style="background:var(--bg3);border-radius:8px;padding:10px 12px">
        <div style="font-size:14px;color:var(--txt3);margin-bottom:4px">GIÁ SO VỚI TRUNG BÌNH 20/50 NGÀY</div>
        <div style="font-size:14px;color:var(--txt2);margin-bottom:6px">MA20 <b style="color:${curr > ma20val ? 'var(--buy)' : 'var(--sell)'};font-family:var(--mono)">${fmt(Math.round(ma20val))}</b></div>
        ${ma50val ? `<div style="font-size:14px;color:var(--txt2);margin-bottom:6px">MA50 <b style="color:${curr > ma50val ? 'var(--buy)' : 'var(--sell)'};font-family:var(--mono)">${fmt(Math.round(ma50val))}</b></div>` : ''}
        ${maCrossSignal === 'golden' ? `<div style="color:var(--buy);font-size:14px;font-weight:700">✨ TÍN HIỆU MUA MẠNH — Trung bình 20 ngày vừa vượt qua trung bình 50 ngày. Điều này xảy ra rất hiếm và thường báo hiệu xu hướng tăng dài hạn.</div>` :
          maCrossSignal === 'death'  ? `<div style="color:var(--sell);font-size:14px;font-weight:700">⚠️ CẢNH BÁO GIẢM — Trung bình 20 ngày vừa chui xuống trung bình 50 ngày. Xu hướng có thể đang chuyển sang giảm.</div>` :
          maCrossSignal === 'above'  ? `<div style="color:var(--buy);font-size:14px">📈 Xu hướng trung hạn đang tốt — giá trung bình ngắn hạn (20 ngày) cao hơn trung hạn (50 ngày).${curr>ma20val?' Giá hiện tại còn cao hơn cả hai → rất tích cực.':curr>ma50val?' Giá đang lùi nhẹ về mức trung bình — bình thường trong xu hướng tăng.':' Giá đang dưới cả hai mức trung bình — cẩn thận dù xu hướng vẫn tốt.'}</div>` :
          maCrossSignal === 'below'  ? `<div style="color:var(--sell);font-size:14px">📉 Xu hướng trung hạn đang xấu — giá trung bình ngắn hạn (20 ngày) thấp hơn trung hạn (50 ngày).${curr<ma20val?' Giá còn thấp hơn cả hai → xu hướng giảm rõ ràng, chưa nên mua thêm.':curr<ma50val?' Giá đang hồi phục ngắn hạn trong xu hướng giảm — chưa chắc đã xong.':' Giá đang tạm trên mức trung bình — theo dõi thêm.'}</div>` : ''}
        <div style="font-size:14px;color:var(--txt3);margin-top:5px;line-height:1.4">Trung bình 20 ngày = giá trung bình trong 20 ngày gần nhất. Trung bình 50 ngày = 50 ngày gần nhất. Khi giá > cả hai = xu hướng tăng toàn diện.</div>
      </div>` : '<div></div>'}
      ${bbW ? `<div style="background:var(--bg3);border-radius:8px;padding:10px 12px">
        <div style="font-size:14px;color:var(--txt3);margin-bottom:4px">ĐỘ BIẾN ĐỘNG (BB WIDTH)</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${bbW.curr < 3 ? 'var(--buy)' : bbW.curr > 10 ? 'var(--sell)' : '#facc15'};margin-bottom:4px">${bbW.curr.toFixed(2)}%</div>
        <div style="font-size:14px;color:var(--txt2);margin-bottom:6px">${bbW.expanding === true ? '↑ Đang mở rộng — biến động tăng' : bbW.expanding === false ? '↓ Đang thu hẹp — áp lực tích lũy' : ''}</div>
        <div style="height:4px;background:var(--bdr);border-radius:2px;margin-bottom:6px"><div style="height:100%;width:${Math.min(bbW.curr/15*100,100)}%;background:${bbW.curr>8?'var(--sell)':bbW.curr>4?'#facc15':'var(--buy)'};border-radius:2px"></div></div>
        <div style="font-size:14px;color:var(--txt3);line-height:1.4">${bbW.curr < 3 ? `Dải hẹp — thường xảy ra trước breakout. ${(s?.macd_hist??s?.macd??0)>0?'MACD dương → breakout tăng khả thi, theo dõi sát.':(s?.macd_hist??s?.macd??0)<0?'MACD âm → cẩn thận breakout theo chiều giảm.':'MACD gần 0 — hướng breakout chưa rõ, chờ xác nhận.'}` : bbW.curr > 10 ? 'Dải rộng: biến động rất cao, rủi ro cả hai chiều — nên giảm size nếu đang nắm nhiều.' : 'Dải bình thường: biến động trong ngưỡng trung bình.'}</div>
      </div>` : ''}
    </div>
    ${fibLevels.length ? `<div style="background:var(--bg3);border-radius:8px;padding:10px 12px;margin-bottom:8px">
      <div style="font-size:14px;color:var(--txt3);margin-bottom:8px">FIBONACCI HỖ TRỢ & KHÁNG CỰ (từ biên độ 52 tuần)</div>
      <div style="position:relative;height:20px;background:linear-gradient(90deg,var(--sell)33,#facc1533,var(--buy)33);border-radius:4px;margin-bottom:10px">
        ${fibLevels.filter(fl=>fl.f>0&&fl.f<100).map(fl=>`<div style="position:absolute;top:0;left:${fl.f}%;width:1px;height:100%;background:#ffffff22"></div>`).join('')}
        <div style="position:absolute;top:-3px;left:calc(${pct52}% - 6px);width:12px;height:26px;background:var(--c0);border-radius:2px;opacity:.8"></div>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:4px">
        ${fibLevels.map(fl => {
          const isNear = Math.abs(curr-fl.nav)/Math.max(curr,1) < 0.02;
          const isSupport = fl.nav < curr;
          return `<div style="background:${isNear?'#facc1522':'var(--bg2)'};border:1px solid ${isNear?'#facc1566':isSupport?'#4ade8033':'#f8717133'};border-radius:4px;padding:3px 8px;text-align:center">
            <div style="font-size:14px;color:${isNear?'#facc15':isSupport?'var(--buy)':'var(--sell)'}">${fl.label}</div>
            <div style="font-family:var(--mono);font-size:14px;font-weight:700">${fmt(Math.round(fl.nav))}</div>
            ${isNear?'<div style="font-size:8px;color:#facc15">← Hiện tại</div>':''}
          </div>`;
        }).join('')}
      </div>
      <div style="font-size:14px;color:var(--txt3);margin-top:8px;line-height:1.4">Fibonacci: các mức hỗ trợ/kháng cự tự nhiên — giá thường phản ứng tại 38.2%, 50%, 61.8%. Vị trí hiện tại (${pct52}% từ đáy 52T) ${nearFib.length ? `gần <b>Fib ${nearFib[0].f}%</b> (${fmt(Math.round(nearFib[0].nav))}đ) — ${nearFib[0].nav<=curr?'<b style="color:var(--buy)">hỗ trợ bên dưới</b>':'<b style="color:var(--sell)">kháng cự phía trên</b>'}. ${nearFib[0].nav<=curr&&(s?.rsi??50)<40?'RSI thấp + Fib support = vùng mua kỹ thuật tốt.':nearFib[0].nav>curr&&(s?.rsi??50)>60?'RSI cao + Fib resistance = cân nhắc chốt lời một phần.':'Theo dõi phản ứng NAV tại mức này.'}` : 'giữa các Fib — chưa có tín hiệu rõ từ Fibonacci.'}</div>
    </div>` : ''}
    ${rsiDivergence === 'bullish' ? `<div style="background:#4ade8011;border:1px solid #4ade8033;border-radius:6px;padding:8px 12px;font-size:14px;line-height:1.6"><div style="color:var(--buy);font-weight:700;margin-bottom:4px">📊 PHÂN KỲ DƯƠNG (Bullish Divergence)</div><div style="color:var(--txt2)">${rsiDivergenceDesc}</div><div style="color:var(--txt3);font-size:14px;margin-top:4px">Phân kỳ dương — giá tạo đáy mới thấp hơn nhưng lực bán suy yếu dần. Kết hợp với RSI < 40 và MACD bắt đầu quay đầu để có xác nhận mạnh hơn.</div></div>` : rsiDivergence === 'bearish' ? `<div style="background:#f8717111;border:1px solid #f8717133;border-radius:6px;padding:8px 12px;font-size:14px;line-height:1.6"><div style="color:var(--sell);font-weight:700;margin-bottom:4px">⚠️ PHÂN KỲ ÂM (Bearish Divergence)</div><div style="color:var(--txt2)">${rsiDivergenceDesc}</div><div style="color:var(--txt3);font-size:14px;margin-top:4px">Phân kỳ âm — giá tạo đỉnh mới cao hơn nhưng lực mua cạn kiệt dần. Không nên mua thêm; nếu đang có lãi, cân nhắc chốt một phần.</div></div>` : ''}
  `) : '';

  // ── 6. TECHNICAL INDICATORS ──
  const rsi   = s?.rsi ?? 50;
  const bb    = s?.bb_pct ?? s?.bb ?? 50;
  const macd  = s?.macd_hist ?? s?.macd ?? 0;
  const score = s?.score || 0;
  const details = s?.details || [];
  const rsiColor = rsi < 35 ? 'var(--buy)' : rsi > 65 ? 'var(--sell)' : 'var(--txt2)';
  const bbColor  = bb  < 30 ? 'var(--buy)' : bb  > 70 ? 'var(--sell)' : 'var(--txt2)';
  const macdColor= macd > 0 ? 'var(--buy)' : macd < 0 ? 'var(--sell)' : 'var(--txt2)';
  const scoreColor = score >= 3 ? 'var(--buy)' : score <= -3 ? 'var(--sell)' : '#facc15';
  const scoreLabel = score >= 6 ? 'MUA M\u1ea0NH' : score >= 3 ? 'MUA' : score <= -6 ? 'B\u00c1N M\u1ea0NH' : score <= -3 ? 'B\u00c1N' : 'TRUNG L\u1eacP';
  const rsiInterp = rsi < 30
    ? `<b>B\u00e1n th\u00e1o m\u1ea1nh.</b> Trong 14 ng\u00e0y qua, \u00e1p l\u1ef1c b\u00e1n r\u1ea5t l\u1edbn \u0111\u1ea9y gi\u00e1 xu\u1ed1ng th\u1ea5p b\u1ea5t th\u01b0\u1eddng. L\u1ecbch s\u1eed cho th\u1ea5y \u0111\u00e2y th\u01b0\u1eddng l\u00e0 <b style="color:var(--buy)">v\u00f9ng \u0111\u00e1y ng\u1eafn h\u1ea1n t\u1ed1t \u0111\u1ec3 b\u1eaft \u0111\u1ea7u mua d\u1ea7n</b>. Tuy nhi\u00ean: n\u1ebfu c\u00f3 tin x\u1ea5u c\u01a1 b\u1ea3n (th\u1ecb tr\u01b0\u1eddng chung suy gi\u1ea3m, ch\u00ednh s\u00e1ch th\u1eaft ch\u1eb7t), xu h\u01b0\u1edbng gi\u1ea3m c\u00f3 th\u1ec3 k\u00e9o d\u00e0i h\u01a1n. <i>Khuy\u1ebfn ngh\u1ecb: chia 2\u20133 l\u1ea7n mua thay v\u00ec mua m\u1ed9t l\u1ea7n.</i>`
    : rsi < 40
    ? `<b>\u00c1p l\u1ef1c b\u00e1n l\u1ea5n \u00e1t.</b> NAV \u0111\u00e3 gi\u1ea3m trong 2 tu\u1ea7n qua. \u0110\u00e2y l\u00e0 <b style="color:var(--buy)">v\u00f9ng t\u01b0\u01a1ng \u0111\u1ed1i r\u1ebb</b> \u0111\u1ec3 mua th\u00eam n\u1ebfu b\u1ea1n tin v\u00e0o qu\u1ef9 d\u00e0i h\u1ea1n. R\u1ee7i ro ng\u1eafn h\u1ea1n v\u1eabn c\u00f2n \u2014 n\u00ean mua chia nh\u1ecf. Khi RSI h\u1ed3i v\u1ec1 45\u201350, xu h\u01b0\u1edbng \u0111ang \u0111\u1ea3o chi\u1ec1u.`
    : rsi < 60
    ? `<b>C\u00e2n b\u1eb1ng, kh\u00f4ng c\u00f3 t\u00edn hi\u1ec7u r\u00f5.</b> L\u1ef1c mua v\u00e0 b\u00e1n \u0111ang t\u01b0\u01a1ng \u0111\u01b0\u01a1ng nhau. NAV dao \u0111\u1ed9ng trung t\u00ednh. Ch\u1ec9 s\u1ed1 RSI kh\u00f4ng cho t\u00edn hi\u1ec7u r\u00f5 r\u00e0ng \u1edf v\u00f9ng n\u00e0y \u2014 h\u00e3y d\u1ef1a th\u00eam v\u00e0o BB%B v\u00e0 MACD \u0111\u1ec3 quy\u1ebft \u0111\u1ecbnh.`
    : rsi < 70
    ? `<b>Xu h\u01b0\u1edbng t\u0103ng t\u1ed1t.</b> L\u1ef1c mua \u0111ang th\u1ed1ng tr\u1ecb. N\u1ebfu ch\u01b0a c\u00f3 v\u1ecb th\u1ebf: gi\u00e1 \u0111ang trong xu h\u01b0\u1edbng t\u1ed1t nh\u01b0ng <i>kh\u00f4ng c\u00f2n r\u1ebb</i>. N\u1ebfu \u0111ang n\u1eafm: \u0111\u00e2y l\u00e0 <b style="color:var(--buy)">t\u00edn hi\u1ec7u gi\u1eef</b>, kh\u00f4ng c\u1ea7n v\u1ed9i b\u00e1n. Khi RSI v\u01b0\u1ee3t 70 th\u00ec b\u1eaft \u0111\u1ea7u th\u1eadn tr\u1ecdng h\u01a1n.`
    : `<b>T\u0103ng qu\u00e1 nhanh, r\u1ee7i ro \u0111i\u1ec1u ch\u1ec9nh.</b> Gi\u00e1 \u0111\u00e3 t\u0103ng m\u1ea1nh li\u00ean t\u1ee5c trong 2 tu\u1ea7n \u2014 nhi\u1ec1u ng\u01b0\u1eddi \u0111ang tranh nhau mua theo \u0111\u00e0. \u1ede v\u00f9ng RSI > 70, x\u00e1c su\u1ea5t \u0111i\u1ec1u ch\u1ec9nh ng\u1eafn h\u1ea1n cao. <b style="color:var(--sell)">Tr\u00e1nh mua th\u00eam nhi\u1ec1u m\u1ed9t l\u00fac</b>; n\u1ebfu \u0111ang n\u1eafm l\u00e3i, c\u00e2n nh\u1eafc ch\u1ed1t m\u1ed9t ph\u1ea7n.`;
  const bbInterp = bb < 20
    ? `<b>D\u01b0\u1edbi d\u1ea3i d\u01b0\u1edbi \u2014 b\u1ea5t th\u01b0\u1eddng gi\u1ea3m.</b> NAV xu\u1ed1ng d\u01b0\u1edbi Bollinger Band d\u01b0\u1edbi, th\u1ea5p h\u01a1n 95% c\u00e1c ng\u00e0y b\u00ecnh th\u01b0\u1eddng trong 20 ng\u00e0y qua. Theo th\u1ed1ng k\u00ea, th\u01b0\u1eddng s\u1ebd h\u1ed3i ph\u1ee5c v\u1ec1 gi\u1eefa d\u1ea3i. <b style="color:var(--buy)">T\u00edn hi\u1ec7u mua k\u1ef9 thu\u1eadt m\u1ea1nh</b> \u2014 nh\u01b0ng c\u1ea7n k\u1ebft h\u1ee3p v\u1edbi RSI v\u00e0 b\u1ed1i c\u1ea3nh th\u1ecb tr\u01b0\u1eddng \u0111\u1ec3 x\u00e1c nh\u1eadn.`
    : bb < 40
    ? `<b>Ph\u1ea7n th\u1ea5p c\u1ee7a d\u1ea3i \u2014 v\u00f9ng mua h\u1ea5p d\u1eabn.</b> NAV \u0111ang <i>t\u01b0\u01a1ng \u0111\u1ed1i r\u1ebb</i> so v\u1edbi xu h\u01b0\u1edbng ng\u1eafn h\u1ea1n. K\u1ebft h\u1ee3p RSI th\u1ea5p + BB%B th\u1ea5p = <b style="color:var(--buy)">t\u00edn hi\u1ec7u mua kh\u00e1 m\u1ea1nh</b>. D\u1ea3i Bollinger \u0111\u01b0\u1ee3c t\u00ednh t\u1eeb MA20 \u00b1 2 \u0111\u1ed9 l\u1ec7ch chu\u1ea9n.`
    : bb < 60
    ? `<b>V\u00f9ng gi\u1eefa d\u1ea3i \u2014 trung t\u00ednh.</b> NAV kh\u00f4ng r\u1ebb c\u0169ng kh\u00f4ng \u0111\u1eaft theo k\u1ef9 thu\u1eadt. Kh\u00f4ng c\u00f3 t\u00edn hi\u1ec7u \u0111\u1ecbnh h\u01b0\u1edbng t\u1eeb BB%B. K\u1ebft h\u1ee3p v\u1edbi c\u00e1c ch\u1ec9 s\u1ed1 kh\u00e1c \u0111\u1ec3 c\u00f3 b\u1ee9c tranh \u0111\u1ea7y \u0111\u1ee7 h\u01a1n.`
    : bb < 80
    ? `<b>Ph\u1ea7n cao c\u1ee7a d\u1ea3i \u2014 ti\u1ebfp c\u1eadn v\u00f9ng b\u00e1n.</b> NAV \u0111ang t\u01b0\u01a1ng \u0111\u1ed1i \u0111\u1eaft so v\u1edbi xu h\u01b0\u1edbng ng\u1eafn h\u1ea1n. N\u1ebfu \u0111ang c\u00f3 l\u00e3i, \u0111\u00e2y l\u00e0 l\u00fac c\u00f3 th\u1ec3 xem x\u00e9t ch\u1ed1t m\u1ed9t ph\u1ea7n. N\u1ebfu ch\u01b0a c\u00f3 v\u1ecb th\u1ebf: ch\u1edd NAV \u0111i\u1ec1u ch\u1ec9nh v\u1ec1 v\u00f9ng gi\u1eefa (40\u201360) s\u1ebd thu\u1eadn l\u1ee3i h\u01a1n.`
    : `<b>Tr\u00ean d\u1ea3i tr\u00ean \u2014 t\u0103ng b\u1ea5t th\u01b0\u1eddng.</b> NAV v\u01b0\u1ee3t Bollinger Band tr\u00ean, cao h\u01a1n 95% c\u00e1c ng\u00e0y b\u00ecnh th\u01b0\u1eddng. Kh\u1ea3 n\u0103ng \u0111i\u1ec1u ch\u1ec9nh v\u1ec1 gi\u1eefa d\u1ea3i r\u1ea5t cao. <b style="color:var(--sell)">Kh\u00f4ng n\u00ean mua th\u00eam</b> \u1edf v\u00f9ng n\u00e0y; c\u00e2n nh\u1eafc ch\u1ed1t l\u1eddi n\u1ebfu \u0111ang n\u1eafm.`;
  // MACD strength normalized by NAV for cross-fund comparison
  const _macdPctNAV = curr > 0 ? Math.abs(macd) / curr * 100 : 0;
  const macdInterp = macd > 0
    ? `<b>MACD d\u01b0\u01a1ng \u2014 \u0111\u00e0 t\u0103ng.</b> EMA ng\u1eafn h\u1ea1n (12 ng\u00e0y) cao h\u01a1n trung h\u1ea1n (26 ng\u00e0y). ${
        _macdPctNAV > 0.3 ? `Histogram <b>l\u1edbn</b> (${_macdPctNAV.toFixed(2)}% NAV) \u2014 \u0111\u00e0 t\u0103ng r\u00f5 r\u00e0ng v\u00e0 m\u1ea1nh.`
        : _macdPctNAV > 0.05 ? `Histogram v\u1eeba ph\u1ea3i (${_macdPctNAV.toFixed(2)}% NAV) \u2014 \u0111\u00e0 t\u0103ng \u1ed5n \u0111\u1ecbnh.`
        : `Histogram r\u1ea5t nh\u1ecf (${_macdPctNAV.toFixed(2)}% NAV) \u2014 \u0111\u00e0 t\u0103ng y\u1ebfu, c\u1ea7n x\u00e1c nh\u1eadn th\u00eam t\u1eeb RSI v\u00e0 BB.`
      } T\u00edn hi\u1ec7u t\u1ed1t nh\u1ea5t khi MACD v\u1eeba chuy\u1ec3n d\u01b0\u01a1ng (Golden Cross MACD).`
    : _macdPctNAV > 0.5
    ? `<b>MACD \u00e2m m\u1ea1nh</b> (${_macdPctNAV.toFixed(2)}% NAV) \u2014 l\u1ef1c gi\u1ea3m r\u1ea5t l\u1edbn. K\u1ec3 c\u1ea3 RSI/BB \u0111\u00e3 v\u00e0o v\u00f9ng qu\u00e1 b\u00e1n, <b style="color:var(--sell)">\u0111\u1eebng v\u00e0o l\u1ec7nh l\u1edbn m\u1ed9t l\u1ea7n</b> \u2014 chia 3\u20134 l\u1ea7n mua d\u1ea7n. T\u00edn hi\u1ec7u mua \u0111\u1ea7y \u0111\u1ee7 khi MACD b\u1eaft \u0111\u1ea7u thu h\u1eb9p v\u00e0 ti\u1ec7m c\u1eadn 0.`
    : _macdPctNAV > 0.1
    ? `<b>MACD \u00e2m v\u1eeba</b> (${_macdPctNAV.toFixed(2)}% NAV) \u2014 \u0111\u00e0 gi\u1ea3m \u0111ang ho\u1ea1t \u0111\u1ed9ng nh\u01b0ng kh\u00f4ng qu\u00e1 m\u1ea1nh. <b style="color:var(--sell)">Ch\u01b0a n\u00ean mua nhi\u1ec1u</b>. Ch\u1edd histogram thu h\u1eb9p v\u00e0 MACD ti\u1ec7m c\u1eadn 0 \u0111\u1ec3 x\u00e1c nh\u1eadn \u0111\u1ea3o chi\u1ec1u.`
    : `<b>MACD g\u1ea7n 0</b> (histogram ${Math.abs(macd).toFixed(2)}, nh\u1ecf h\u01a1n 0.1% NAV) \u2014 \u0111\u00e0 gi\u1ea3m s\u1eafp c\u1ea1n ki\u1ec7t. <i style="color:#facc15">Theo d\u00f5i s\u00e1t: MACD chuy\u1ec3n d\u01b0\u01a1ng l\u00e0 t\u00edn hi\u1ec7u mua m\u1ea1nh, \u0111\u1eb7c bi\u1ec7t khi RSI c\u0169ng \u0111ang t\u0103ng.</i>`;
  const _rsiCurr  = _rsiAt(navVals, navVals.length - 1);
  const _rsiPrev7 = navVals.length > 22 ? _rsiAt(navVals, navVals.length - 1 - 7) : null;
  const _rsiDelta  = (_rsiCurr != null && _rsiPrev7 != null) ? Math.round(_rsiCurr - _rsiPrev7) : null;
  const techNotice = techRel === 'LOW' || techRel === 'N/A'
    ? `<div style="background:#60a5fa11;border:1px solid #60a5fa33;border-radius:6px;padding:7px 10px;margin-bottom:10px;font-size:14px;color:#60a5fa">\u26a0 V\u1edbi qu\u1ef9 tr\u00e1i phi\u1ebfu/ti\u1ec1n t\u1ec7, c\u00e1c ch\u1ec9 s\u1ed1 k\u1ef9 thu\u1eadt c\u00f3 \u0111\u1ed9 tin c\u1eady th\u1ea5p h\u01a1n so v\u1edbi qu\u1ef9 c\u1ed5 phi\u1ebfu.</div>` : '';

  const indHtml = s ? _mkSect('T\u00cdN HI\u1ec6U K\u1ef8 THU\u1eacT', '\u26a1', `
    ${techNotice}
    <div style="background:var(--bg3);border-radius:8px;padding:12px 14px;margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <div style="font-size:14px;color:var(--txt3)">Smart Score \u2014 T\u1ed5ng h\u1ee3p t\u1ea5t c\u1ea3 t\u00edn hi\u1ec7u</div>
        <div style="font-family:var(--mono);font-size:18px;font-weight:700;color:${scoreColor}">${score > 0 ? '+' : ''}${score}</div>
      </div>
      <div style="height:8px;background:linear-gradient(90deg,var(--sell),#facc15,var(--buy));border-radius:4px;position:relative;margin-bottom:6px">
        <div style="position:absolute;top:-3px;left:calc(${Math.round((score + 6) / 12 * 100)}% - 7px);width:14px;height:14px;background:var(--c0);border-radius:50%;border:2px solid var(--bg)"></div>
      </div>
      <div style="text-align:center;font-size:14px;font-weight:700;color:${scoreColor}">${scoreLabel}</div>
    </div>
    <div style="display:grid;grid-template-columns:1fr;gap:6px;margin-bottom:8px">
      <div style="background:var(--bg3);border-radius:8px;padding:10px 12px">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
          <div><span style="font-size:14px;color:var(--txt3)">\u0110\u00c0 MUA/B\u00c1N \u2014 th\u1ecb tr\u01b0\u1eddng \u0111ang nghi\u00eang v\u1ec1 \u0111\u00e2u?</span><span style="margin-left:8px;font-family:var(--mono);font-size:14px;font-weight:700;color:${rsiColor}">${rsi.toFixed(1)}</span></div>
          <span style="font-size:14px;color:${rsiColor}">${rsi < 35 ? '\ud83d\udfe2 \u0110ANG B\u1eca B\u00c1N NHI\u1ec0U \u2192 th\u01b0\u1eddng l\u00e0 c\u01a1 h\u1ed9i mua' : rsi > 65 ? '\ud83d\udd34 \u0110ANG \u0110\u01af\u1ee2C MUA NHI\u1ec0U \u2192 c\u1ea9n th\u1eadn mua th\u00eam' : '\u26aa C\u00c2N B\u1eb0NG \u2014 kh\u00f4ng thi\u00ean v\u1ec1 b\u00ean n\u00e0o'}</span>
        </div>
        <div style="height:5px;background:linear-gradient(90deg,var(--buy),#facc15,var(--sell));border-radius:3px;position:relative;margin-bottom:6px">
          <div style="position:absolute;top:-2px;left:${Math.min(rsi, 100)}%;width:9px;height:9px;background:var(--c0);border-radius:50%;transform:translateX(-50%)"></div>
        </div>
        <div style="font-size:14px;color:var(--txt2);line-height:1.5">${rsiInterp}</div>
        ${_rsiDelta != null && Math.abs(_rsiDelta) >= 2 ? ('<div style="margin-top:5px;font-size:14px;color:'+(_rsiDelta>0?'var(--buy)':'var(--sell)')+'">'+(_rsiDelta>0?'↑ ':'↓ ')+'So với 7 ngày trước: đà mua/bán '+(_rsiDelta>0?'tăng +':'giảm ')+Math.abs(_rsiDelta)+' điểm — '+(_rsiDelta>0?'ngày càng có nhiều người mua hơn.':'ngày càng có nhiều người bán hơn.')+'</div>') : ''}
      </div>
      <div style="background:var(--bg3);border-radius:8px;padding:10px 12px">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
          <div><span style="font-size:14px;color:var(--txt3)">V\u1eca TR\u00cd GI\u00c1 \u2014 \u0111ang \u1edf v\u00f9ng r\u1ebb hay \u0111\u1eaft so v\u1edbi 20 ng\u00e0y qua?</span><span style="margin-left:8px;font-family:var(--mono);font-size:14px;font-weight:700;color:${bbColor}">${bb.toFixed(1)}%</span></div>
          <span style="font-size:14px;color:${bbColor}">${bb < 30 ? '\ud83d\udfe2 GI\u00c1 \u0110ANG TH\u1ea4P (r\u1ebb h\u01a1n b\u00ecnh th\u01b0\u1eddng)' : bb > 70 ? '\ud83d\udd34 GI\u00c1 \u0110ANG CAO (\u0111\u1eaft h\u01a1n b\u00ecnh th\u01b0\u1eddng)' : '\u26aa GI\u00c1 \u1ede M\u1ee8C B\u00ccNH TH\u01af\u1edcNG'}</span>
        </div>
        <div style="height:5px;background:linear-gradient(90deg,var(--buy),#facc15,var(--sell));border-radius:3px;position:relative;margin-bottom:6px">
          <div style="position:absolute;top:-2px;left:${Math.min(Math.max(bb, 0), 100)}%;width:9px;height:9px;background:var(--c0);border-radius:50%;transform:translateX(-50%)"></div>
        </div>
        <div style="font-size:14px;color:var(--txt2);line-height:1.5">${bbInterp}</div>
      </div>
      <div style="background:var(--bg3);border-radius:8px;padding:10px 12px">
        <div style="display:flex;justify-content:space-between;align-items:flex-start">
          <div><span style="font-size:14px;color:var(--txt3)">XU H\u01af\u1edaNG \u2014 qu\u1ef9 \u0111ang t\u0103ng t\u1ed1c hay gi\u1ea3m t\u1ed1c?</span><span style="margin-left:8px;font-family:var(--mono);font-size:14px;font-weight:700;color:${macdColor}">${macd >= 0 ? '+' : ''}${(macd || 0).toFixed(2)}</span></div>
          <span style="font-size:14px;color:${macdColor}">${macd > 0 ? '\u25b2 \u0110ANG T\u0102NG \u2014 \u0111\u00e0 t\u1ed1t' : macd < 0 ? '\u25bc \u0110ANG GI\u1ea2M \u2014 ch\u01b0a n\u00ean v\u1ed9i mua' : '= GI\u1eee NGUY\u00caN \u2014 ch\u1edd th\u00eam t\u00edn hi\u1ec7u'}</span>
        </div>
        <div style="margin-top:6px;font-size:14px;color:var(--txt2);line-height:1.5">${macdInterp}</div>
      </div>
    </div>
    ${details.length ? `<div style="background:var(--bg3);border-radius:6px;padding:8px 12px">
      <div style="font-size:14px;color:var(--txt3);margin-bottom:6px">Chi ti\u1ebft t\u00ednh \u0111i\u1ec3m</div>
      <div style="display:flex;flex-wrap:wrap;gap:4px">${details.map(d => {
        const isBull = /qu\u00e1 b\u00e1n|\u0111\u00e1y|\u25b2|mua|t\u00edch c\u1ef1c|h\u1ed7 tr\u1ee3/.test(d);
        const isBear = /qu\u00e1 mua|\u0111\u1ec9nh|\u25bc|b\u00e1n|c\u1ea9n th\u1eadn|cao|tr\u00ean band/.test(d);
        const bg = isBull ? '#4ade8022' : isBear ? '#f8717122' : 'var(--bg2)';
        const col = isBull ? 'var(--buy)' : isBear ? 'var(--sell)' : 'var(--txt2)';
        return `<span style="display:inline-block;background:${bg};color:${col};border:1px solid ${col}44;border-radius:12px;padding:2px 8px;font-size:14px;font-family:var(--mono)">${d}</span>`;
      }).join('')}</div>
    </div>` : ''}`) : '';

  // ── 7. PREDICTION ──
  const t2Api  = s?.t2_prediction;
  const t5Api  = s?.t5_prediction;
  const predNav  = t2Api?.nav  || _smartPredict(pts, 2);
  const predNav5 = t5Api?.nav  || _smartPredict(pts, 5);
  const predPct  = predNav && curr  ? (predNav  - curr) / curr * 100 : (t2Api?.pct || null);
  const predPct5 = predNav5 && curr ? (predNav5 - curr) / curr * 100 : (t5Api?.pct || null);
  const r2 = t2Api?.r2;
  const confLabel = r2 == null ? '' : r2 > 0.8 ? '(\u0111\u1ed9 tin c\u1eady cao)' : r2 > 0.5 ? '(\u0111\u1ed9 tin c\u1eady trung b\u00ecnh)' : '(\u0111\u1ed9 tin c\u1eady th\u1ea5p)';
  const acc = _checkPredAccuracy(code, pts);
  if (predNav && curr) {
    const pd = new Date(); pd.setDate(pd.getDate() + 2);
    _savePrediction(code, predNav, pd.toISOString().slice(0, 10));
  }
  const predMethodLabel = fundType === 'bond'
    ? 'H\u1ed3i quy 60 ng\u00e0y (70%) + Momentum 10 ng\u00e0y (20%) + 5 ng\u00e0y (10%)'
    : 'H\u1ed3i quy 30 ng\u00e0y (40%) + Momentum 5 ng\u00e0y (35%) + 3 ng\u00e0y (25%)';
  // Compute model components for display
  const _linRegSlope = (arr) => {
    const n = arr.length; if (n < 3) return 0;
    const xm = (n-1)/2, ym = arr.reduce((a,b)=>a+b,0)/n;
    const ss = arr.reduce((a,v,i)=>a+(i-xm)*(v-ym),0);
    const sx = arr.reduce((a,_,i)=>a+(i-xm)**2,0);
    return sx > 0 ? ss/sx : 0;
  };
  const regN = fundType === 'bond' ? 60 : 30;
  const momN1 = fundType === 'bond' ? 10 : 5;
  const momN2 = fundType === 'bond' ? 5 : 3;
  const regW  = fundType === 'bond' ? 0.7 : 0.4;
  const momW1 = fundType === 'bond' ? 0.2 : 0.35;
  const momW2 = fundType === 'bond' ? 0.1 : 0.25;
  const regSlope = navVals.length >= regN ? _linRegSlope(navVals.slice(-regN)) : null;
  const mom1 = _perfReturn(pts, momN1);
  const mom2 = _perfReturn(pts, momN2);
  const regContrib  = regSlope != null ? regW * (2 * regSlope / Math.max(curr, 1) * 100) : null;
  const mom1Contrib = mom1 != null ? momW1 * mom1 : null;
  const mom2Contrib = mom2 != null ? momW2 * mom2 : null;
  // Confidence interval from historical accuracy or from volatility
  const maeVal = acc?.mae;
  const sigma = (() => { if (navVals.length < 20) return null; const l=navVals.slice(-20),m=l.reduce((a,b)=>a+b,0)/l.length; return Math.sqrt(l.reduce((a,v)=>a+(v-m)**2,0)/l.length)/m*100; })();
  const ciRange = maeVal || sigma;
  const bullNav = predNav && ciRange ? Math.round(predNav * (1 + ciRange/100)) : null;
  const bearNav = predNav && ciRange ? Math.round(predNav * (1 - ciRange/100)) : null;


  // ── 7b. HISTORICAL PATTERN ANALYSIS ──
  // Rolling RSI (Cutler's simple method, O(n*period), consistent with _rsiAt)
  const _rollingRSI = (arr, period=14) => {
    const rsiArr = new Array(arr.length).fill(null);
    for (let i = period; i < arr.length; i++) {
      let g = 0, l = 0;
      for (let j = i - period + 1; j <= i; j++) {
        const d = arr[j] - arr[j-1];
        if (d > 0) g += d; else l -= d;
      }
      const ag = g/period, al = l/period;
      rsiArr[i] = al === 0 ? 100 : 100 - 100/(1 + ag/al);
    }
    return rsiArr;
  };
  // histPatternData: computed once, used by histPatternHtml AND conclusion
  const histPatternData = (() => {
    if (!s || pts.length < 120) return null;
    const apiRSI = s.rsi ?? 50;
    if (apiRSI >= 35 && apiRSI <= 65) return null;
    const rsiArr = _rollingRSI(navVals, 14);
    const rsiRange = 8;
    const instances = [];
    for (let i = 14; i < navVals.length - 62; i++) {
      if (rsiArr[i] == null) continue;
      if (Math.abs(rsiArr[i] - apiRSI) <= rsiRange) {
        const ret30 = (navVals[i+30] - navVals[i]) / navVals[i] * 100;
        const ret60 = (navVals[i+60] - navVals[i]) / navVals[i] * 100;
        instances.push({rsi: rsiArr[i], ret30, ret60});
      }
    }
    if (instances.length < 5) return null;
    const n30pos = instances.filter(x => x.ret30 > 0).length;
    const n60pos = instances.filter(x => x.ret60 > 0).length;
    return {
      n: instances.length,
      apiRSI,
      avg30:    instances.reduce((a,x)=>a+x.ret30,0)/instances.length,
      avg60:    instances.reduce((a,x)=>a+x.ret60,0)/instances.length,
      best30:   Math.max(...instances.map(x=>x.ret30)),
      worst30:  Math.min(...instances.map(x=>x.ret30)),
      winRate30: Math.round(n30pos/instances.length*100),
      winRate60: Math.round(n60pos/instances.length*100),
    };
  })();
  const histPatternHtml = histPatternData ? (() => {
    const {n, apiRSI, avg30, avg60, best30, worst30, winRate30, winRate60} = histPatternData;
    const avgC30 = avg30 >= 0 ? 'var(--buy)' : 'var(--sell)';
    const avgC60 = avg60 >= 0 ? 'var(--buy)' : 'var(--sell)';
    const winC30 = winRate30 >= 60 ? 'var(--buy)' : winRate30 >= 40 ? '#facc15' : 'var(--sell)';
    const winC60 = winRate60 >= 60 ? 'var(--buy)' : winRate60 >= 40 ? '#facc15' : 'var(--sell)';
    const zone = apiRSI < 35 ? `RSI < 35 (vùng quá bán)` : `RSI > 65 (vùng quá mua)`;
    const insight = avg30 >= 0 && winRate30 >= 60
      ? `⚡ Tín hiệu lịch sử tích cực: trong ${winRate30}% trường hợp, quỹ đã phục hồi sau 30 ngày (TB ${avg30.toFixed(1)}%). Tích lũy dần có thể hiệu quả.`
      : avg30 < 0 && winRate30 <= 40
      ? `⚠ Lịch sử cho thấy quỹ tiếp tục giảm sau 30 ngày trong ${100-winRate30}% trường hợp (TB ${avg30.toFixed(1)}%). Cẩn trọng khi mua thêm.`
      : winRate30 >= 55
      ? `ℹ️ Nhẹ nghiêng phục hồi: ${winRate30}% lần tăng, TB ${avg30>=0?'+':''}${avg30.toFixed(1)}% sau 30 ngày. Không đủ mạnh để kết luận rõ ràng.`
      : `ℹ️ Kết quả lịch sử hỗn hợp (${winRate30}% lần tăng, TB ${avg30>=0?'+':''}${avg30.toFixed(1)}%) — khó dự đoán dựa trên RSI đơn thuần.`;
    return _mkSect('LỊCH SỬ TÍN HIỆU TƯƠNG TỰ', '📊', `
      <div style="font-size:14px;color:var(--txt3);margin-bottom:8px">Trong ${n} lần lịch sử có ${zone} — hiệu suất trung bình của quỹ trong các giai đoạn tiếp theo:</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px">
        <div style="background:var(--bg3);border-radius:8px;padding:10px 12px;text-align:center">
          <div style="font-size:14px;color:var(--txt3);margin-bottom:4px;font-family:var(--mono)">SAU 30 NGÀY</div>
          <div style="font-family:var(--mono);font-size:18px;font-weight:700;color:${avgC30}">${avg30>=0?'+':''}${avg30.toFixed(1)}%</div>
          <div style="font-size:14px;color:var(--txt3);margin-top:2px">trung bình</div>
          <div style="font-size:14px;color:${winC30};margin-top:5px;font-family:var(--mono)">${winRate30}% lần tăng</div>
        </div>
        <div style="background:var(--bg3);border-radius:8px;padding:10px 12px;text-align:center">
          <div style="font-size:14px;color:var(--txt3);margin-bottom:4px;font-family:var(--mono)">SAU 60 NGÀY</div>
          <div style="font-family:var(--mono);font-size:18px;font-weight:700;color:${avgC60}">${avg60>=0?'+':''}${avg60.toFixed(1)}%</div>
          <div style="font-size:14px;color:var(--txt3);margin-top:2px">trung bình</div>
          <div style="font-size:14px;color:${winC60};margin-top:5px;font-family:var(--mono)">${winRate60}% lần tăng</div>
        </div>
      </div>
      <div style="display:flex;gap:5px;margin-bottom:8px">
        <div style="background:var(--bg3);border-radius:6px;padding:5px 10px;font-size:14px;flex:1;text-align:center">
          <span style="color:var(--txt3);font-size:14px">Tốt nhất (30N)</span>
          <span style="font-family:var(--mono);color:var(--buy);margin-left:5px">${best30>=0?'+':''}${best30.toFixed(1)}%</span>
        </div>
        <div style="background:var(--bg3);border-radius:6px;padding:5px 10px;font-size:14px;flex:1;text-align:center">
          <span style="color:var(--txt3);font-size:14px">Xấu nhất (30N)</span>
          <span style="font-family:var(--mono);color:var(--sell);margin-left:5px">${worst30.toFixed(1)}%</span>
        </div>
      </div>
      <div style="background:${avg30>=0&&winRate30>=60?'#4ade8011':avg30<0&&winRate30<=40?'#f8717111':'var(--bg3)'};border:1px solid ${avg30>=0&&winRate30>=60?'#4ade8033':avg30<0&&winRate30<=40?'#f8717133':'var(--bdr)'};border-radius:6px;padding:7px 10px;font-size:14px;color:var(--txt2);line-height:1.5">${insight}</div>
      <div style="font-size:14px;color:var(--txt3);margin-top:6px;line-height:1.5">Dựa trên NAV lịch sử của chính quỹ này. Quá khứ không đảm bảo tương lai — bối cảnh thị trường thay đổi có thể tạo ra kết quả khác.</div>
    `);
  })() : '';
  const predHtml = predNav ? _mkSect('DỰ BÁO GIÁ TRỊ (ENSEMBLE MODEL)', '🔮', `
    <div style="background:linear-gradient(135deg,var(--bg3),#0a1628);border:1px solid #facc1533;border-radius:10px;padding:14px">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
        <div style="background:var(--bg2);border-radius:8px;padding:12px;text-align:center">
          <div style="font-size:14px;color:var(--txt3);margin-bottom:4px">Dự báo T+2 (2 ngày tới)</div>
          <div style="font-family:var(--mono);font-size:17px;font-weight:700;color:#facc15">${fmt(Math.round(predNav))}</div>
          ${predPct != null ? `<div class="pnl ${pnlC(predPct)}" style="font-size:14px;font-weight:700;margin-top:4px">${predPct >= 0 ? '+' : ''}${predPct.toFixed(2)}%</div>` : ''}
          <div style="font-size:14px;color:var(--txt3);margin-top:4px">NAV dự báo khi lệnh mua hôm nay khớp T+2</div>
        </div>
        <div style="background:var(--bg2);border-radius:8px;padding:12px;text-align:center">
          <div style="font-size:14px;color:var(--txt3);margin-bottom:4px">Dự báo T+5 (1 tuần)</div>
          <div style="font-family:var(--mono);font-size:17px;font-weight:700;color:#facc15">${predNav5 ? fmt(Math.round(predNav5)) : '–'}</div>
          ${predPct5 != null ? `<div class="pnl ${pnlC(predPct5)}" style="font-size:14px;font-weight:700;margin-top:4px">${predPct5 >= 0 ? '+' : ''}${predPct5.toFixed(2)}%</div>` : ''}
          <div style="font-size:14px;color:var(--txt3);margin-top:4px">Xu hướng ngắn hạn 1 tuần</div>
        </div>
      </div>
      ${r2 != null ? `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <span style="font-size:14px;color:var(--txt3)">Độ khớp R²</span>
        <div style="flex:1;margin:0 8px;height:4px;background:var(--bdr);border-radius:2px"><div style="height:100%;width:${(r2 * 100).toFixed(0)}%;background:${r2 > 0.7 ? 'var(--buy)' : '#facc15'};border-radius:2px"></div></div>
        <span style="font-size:14px;font-family:var(--mono);color:${r2 > 0.7 ? 'var(--buy)' : '#facc15'}">${r2.toFixed(2)} ${confLabel}</span>
      </div>` : ''}
      ${(bullNav && bearNav) ? `<div style="border-top:1px solid var(--bdr);padding-top:10px;margin-top:2px">
        <div style="font-size:14px;color:var(--txt3);margin-bottom:6px;font-family:var(--mono);letter-spacing:.05em">KỊCH BẢN T+2 (±${(ciRange||0).toFixed(1)}% khoảng tin cậy)</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px">
          <div style="background:#4ade8011;border:1px solid #4ade8033;border-radius:6px;padding:8px;text-align:center">
            <div style="font-size:14px;color:var(--buy);margin-bottom:3px">📈 Tích cực</div>
            <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:var(--buy)">${fmt(bullNav)}</div>
            <div style="font-size:14px;color:var(--txt3)">+${((bullNav-curr)/curr*100).toFixed(2)}%</div>
          </div>
          <div style="background:#facc1511;border:1px solid #facc1533;border-radius:6px;padding:8px;text-align:center">
            <div style="font-size:14px;color:#facc15;margin-bottom:3px">📊 Cơ sở</div>
            <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:#facc15">${fmt(Math.round(predNav))}</div>
            <div style="font-size:14px;color:var(--txt3)">${predPct >= 0 ? '+' : ''}${(predPct||0).toFixed(2)}%</div>
          </div>
          <div style="background:#f8717111;border:1px solid #f8717133;border-radius:6px;padding:8px;text-align:center">
            <div style="font-size:14px;color:var(--sell);margin-bottom:3px">📉 Tiêu cực</div>
            <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:var(--sell)">${fmt(bearNav)}</div>
            <div style="font-size:14px;color:var(--txt3)">${((bearNav-curr)/curr*100).toFixed(2)}%</div>
          </div>
        </div>
      </div>` : ''}
    </div>
    <div style="background:var(--bg3);border-radius:8px;padding:10px 12px;margin-top:8px">
      <div style="font-size:14px;color:var(--txt3);margin-bottom:8px;font-family:var(--mono);letter-spacing:.05em">PHÂN RÃ MÔ HÌNH ENSEMBLE</div>
      ${[
        {label:`Hồi quy tuyến tính (${regN}d)`, w:regW, contrib:regContrib, desc:`Xu hướng dài hạn từ ${regN} ngày gần nhất (trọng số ${Math.round(regW*100)}%)`},
        {label:`Momentum ngắn hạn (${momN1}d)`, w:momW1, contrib:mom1Contrib, desc:`Đà biến động ${momN1} ngày gần nhất (trọng số ${Math.round(momW1*100)}%)`},
        {label:`Momentum siêu ngắn (${momN2}d)`, w:momW2, contrib:mom2Contrib, desc:`Phản ứng giá ${momN2} ngày gần nhất (trọng số ${Math.round(momW2*100)}%)`},
      ].map(({label, w, contrib, desc}) => {
        const c = contrib;
        const cStr = c != null ? `${c >= 0 ? '+' : ''}${c.toFixed(3)}%` : '–';
        const col = c == null ? 'var(--txt3)' : c > 0.01 ? 'var(--buy)' : c < -0.01 ? 'var(--sell)' : 'var(--txt2)';
        const barW = c != null ? Math.min(Math.abs(c) / 0.1 * 50, 50) : 0;
        return `<div style="margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px">
            <span style="font-size:14px;color:var(--txt2)">${label}</span>
            <span style="font-family:var(--mono);font-size:14px;font-weight:700;color:${col}">${cStr}</span>
          </div>
          <div style="height:3px;background:var(--bdr);border-radius:2px;position:relative;margin-bottom:3px">
            <div style="position:absolute;${c>=0?'left:50%':'right:50%'};width:${barW}%;height:100%;background:${col};border-radius:2px"></div>
          </div>
          <div style="font-size:14px;color:var(--txt3)">${desc}</div>
        </div>`;
      }).join('')}
      <div style="border-top:1px solid var(--bdr);padding-top:6px;font-size:14px;color:var(--txt3)">
        ${acc ? `📊 Sai số lịch sử: ±${acc.mae.toFixed(2)}% trên ${acc.count} dự báo đã kiểm chứng · ` : ''}
        R² ${r2 != null ? r2.toFixed(3) : 'N/A'} · ${predMethodLabel}
      </div>
    </div>
    <div style="margin-top:6px;font-size:14px;color:var(--txt3);line-height:1.5">⚠️ Dự báo dựa trên xu hướng lịch sử NAV, không phải đảm bảo. Các sự kiện bất ngờ (thay đổi chính sách, khủng hoảng thị trường) có thể làm NAV lệch so với dự báo. Kịch bản "tích cực" và "tiêu cực" chỉ là phạm vi có thể xảy ra, không phải cam kết.</div>`) : '';

  // ── 8. CONCLUSION ──
  // ── 8. CONCLUSION ──
  const apiConclusion = s?.conclusion || '';
  const scoreDesc = score >= 6 ? 'MUA MẠNH' : score >= 3 ? 'MUA' : score <= -6 ? 'BÁN MẠNH' : score <= -3 ? 'BÁN' : 'TRUNG LẬP';
  // histConf: one-sentence confirmation from historical pattern (appended to summaryLine)
  const histConf = histPatternData && histPatternData.n >= 10
    ? (histPatternData.winRate30 >= 65 && histPatternData.avg30 >= 0.3
       ? ` Lịch sử xác nhận: ${histPatternData.winRate30}% khả năng tăng sau 30 ngày (TB +${histPatternData.avg30.toFixed(1)}%).`
       : histPatternData.winRate30 <= 35 || (histPatternData.avg30 < -0.5 && histPatternData.winRate30 < 45)
       ? ` Lịch sử cảnh báo: chỉ ${histPatternData.winRate30}% khả năng tăng sau 30 ngày (TB ${histPatternData.avg30.toFixed(1)}%).`
       : '')
    : '';
  const summaryLine = (() => {
    const cheapTech = rsi < 42 && bb < 42;
    const expTech   = rsi > 62 && bb > 62;
    const _mac = typeof maCrossSignal !== 'undefined' ? maCrossSignal : '';
    const _maCtx = _mac === 'golden' ? ' Golden Cross MA vừa xuất hiện — xác nhận xu hướng tăng mạnh.'
      : _mac === 'death' ? ' Death Cross MA vừa xuất hiện — cẩn thận rủi ro giảm tiếp.'
      : _mac === 'above' && ma20val && ma50val ? ` MA20 trên MA50 (+${((ma20val-ma50val)/ma50val*100).toFixed(1)}%) — xu hướng tăng duy trì.`
      : _mac === 'below' && ma20val && ma50val ? ` MA20 dưới MA50 (−${Math.abs((ma20val-ma50val)/ma50val*100).toFixed(1)}%) — xu hướng giảm trung hạn.`
      : '';
    const _nf = typeof nearFib !== 'undefined' && nearFib.length ? nearFib[0] : null;
    const _fibCtx = _nf ? (_nf.nav <= curr ? ` Fib ${_nf.f}% hỗ trợ gần đây.` : ` Fib ${_nf.f}% kháng cự phía trên.`) : '';
    const _p52 = typeof pct52 !== 'undefined' ? pct52 : 50;
    const _rangeCtx = _p52 < 15 ? ' Giá đang ở vùng đáy 52 tuần — cơ hội tích lũy dài hạn.' : _p52 > 85 ? ' Giá gần đỉnh 52 tuần — hạn chế mua thêm lớn.' : '';
    // RSI divergence — strong reversal signal
    const _divCtx = typeof rsiDivergence !== 'undefined' && rsiDivergence === 'bullish'
      ? ' ⚡ Phân kỳ dương RSI — lực bán đang suy yếu dù giá tạo đáy mới: khả năng đảo chiều tăng cao hơn bình thường.'
      : typeof rsiDivergence !== 'undefined' && rsiDivergence === 'bearish'
      ? ' ⚠️ Phân kỳ âm RSI — lực mua cạn kiệt dù giá tạo đỉnh mới: rủi ro đảo chiều giảm tăng cao.'
      : '';
    // Volatility regime context
    const _volRCtx = typeof _volRegime !== 'undefined' && _volRegime != null && _volRegime > 1.5
      ? ` Biến động đang tăng cao (${_volRegime.toFixed(1)}x bình thường) — chia nhỏ lệnh thay vì mua/bán một lần lớn.`
      : '';
    if (score >= 5 && cheapTech) return `Tín hiệu kỹ thuật rất tích cực: giá đang ở vùng rẻ (RSI ${rsi.toFixed(0)}, BB ${bb.toFixed(0)}%) và đà tăng đang hình thành.${_maCtx}${_rangeCtx}${_divCtx}${histConf}${_volRCtx}`;
    if (score >= 3 && macd > 0)  return `Tín hiệu mua — đà tăng đang mạnh${cheapTech ? ', giá còn ở vùng hấp dẫn' : ''}.${_maCtx}${_fibCtx}${_divCtx}${histConf}${_volRCtx}`;
    if (score <= -5 && expTech)  return `Tín hiệu kỹ thuật tiêu cực: giá đang ở vùng đắt (RSI ${rsi.toFixed(0)}, BB ${bb.toFixed(0)}%) và đà giảm đang hình thành.${_maCtx}${_rangeCtx}${_divCtx}${_volRCtx}`;
    if (score <= -3 && macd < 0) return `Tín hiệu bán — đà giảm đang mạnh${expTech ? ', giá ở vùng cao' : ''}. Thận trọng khi mua thêm.${_maCtx}${_fibCtx}${_divCtx}${_volRCtx}`;
    if (score === 0)             return `Tín hiệu trung lập. Các chỉ số kỹ thuật không nghiêng hẳn về chiều nào.${_maCtx}${_divCtx}${histConf}`;
    return score > 0 ? `Tín hiệu nhẹ nghiêng về mua — chưa đủ điều kiện mua mạnh.${_maCtx}${_fibCtx}${_divCtx}${histConf}${_volRCtx}` : `Tín hiệu nhẹ nghiêng về bán — chờ thêm xác nhận.${_maCtx}${_fibCtx}${_divCtx}${_volRCtx}`;
  })();
  const _summaryRsiCtx = _rsiDelta != null && Math.abs(_rsiDelta) >= 5
    ? (_rsiDelta >= 8 && rsi < 50
      ? ` RSI đang phục hồi mạnh (<b style="color:var(--buy)">+${_rsiDelta}pts/7 ngày</b>) từ vùng ${rsi.toFixed(0)} — đà bán đang suy yếu, chuẩn bị đảo chiều.`
      : _rsiDelta <= -5 && rsi <= 20
      ? ` RSI cực kỳ quá bán (${rsi.toFixed(0)}) vẫn đang giảm (<b style="color:var(--sell)">−${Math.abs(_rsiDelta)}pts/7 ngày</b>) — chờ RSI ổn định hoặc bật lên trước khi mua mạnh.`
      : _rsiDelta <= -8 && rsi > 45
      ? ` RSI đang giảm nhanh (<b style="color:var(--sell)">−${Math.abs(_rsiDelta)}pts/7 ngày</b>) — cẩn thận áp lực bán gia tăng.`
      : _rsiDelta >= 5 && rsi < 40
      ? ` RSI bắt đầu hồi từ đáy (<b style="color:var(--buy)">+${_rsiDelta}pts/7 ngày</b>) — dấu hiệu áp lực bán suy yếu.`
      : _rsiDelta <= -5 && rsi > 62
      ? ` RSI rời vùng quá mua (<b style="color:var(--sell)">−${Math.abs(_rsiDelta)}pts/7 ngày</b>) — cẩn thận chốt lời.`
      : '')
    : '';
  _lastStrategyHtml = '';  // reset before computing
  const strategyHtml = (() => {
    const cheapTech = rsi < 45 && bb < 45;
    const expTech   = rsi > 60 && bb > 65;
    const isBond    = fundType === 'bond' || fundType === 'money_market';
    // Position sizing hint based on score strength + volatility
    const vol = _annVol(pts);
    const sizingHint = (() => {
      const baseAmt = score >= 5 ? '30–50%' : score >= 3 ? '15–30%' : score >= 1 ? '5–15%' : null;
      if (!baseAmt) return null;
      if (vol && vol > 20) return `${baseAmt} số vốn dự kiến — chia 3 lần (biến động cao ${vol.toFixed(0)}%, tránh mua 1 lần)`;
      if (vol && vol > 12) return `${baseAmt} số vốn dự kiến — có thể chia 2 lần`;
      return `${baseAmt} số vốn dự kiến — quỹ ổn định, có thể mua 1–2 lần`;
    })();
    // Key price levels from Fibonacci (defined in section 5b)
    const fibSupport = typeof fibLevels !== 'undefined' && fibLevels.length
      ? fibLevels.filter(f => f.nav < curr).slice(-2)  // 2 levels below current
      : [];
    const fibResist = typeof fibLevels !== 'undefined' && fibLevels.length
      ? fibLevels.filter(f => f.nav > curr).slice(0, 2)  // 2 levels above current
      : [];
    let rows = [];
    if (score >= 3) {
      rows.push(['ℹ️ Chưa có vị thế', cheapTech
        ? `Thời điểm tốt để mua vào — kỹ thuật thuận chiều, giá đang ở vùng hấp dẫn. Có thể mua 1 lần hoặc chia 2 lần trong 2 tuần.`
        : `Xu hướng tốt nhưng giá không còn rẻ. Nên mua chia nhỏ 2–3 lần để giảm rủi ro thời điểm.`]);
      if (sizingHint) rows.push(['📐 Gợi ý tỷ trọng', sizingHint]);
      // DCA ladder: specific Fib support levels as entry price targets
      if (rsi < 50 && fibSupport.length >= 1 && !isBond) {
        const _lvls = fibSupport.slice(-2).reverse(); // nearest support first
        const _alloc = _lvls.length >= 2 ? ['50%','30%','20%'] : ['60%','40%'];
        let _dcaStr = `Lần 1 — NAV hiện tại ${fmt(Math.round(curr))}đ (${_alloc[0]} vốn dự kiến).`;
        _lvls.forEach((fl, i) => {
          const _dp = ((curr - fl.nav) / curr * 100).toFixed(1);
          _dcaStr += ` Lần ${i+2} — ${fl.label}: ${fmt(Math.round(fl.nav))}đ (−${_dp}%) = ${_alloc[i+1]||'20%'} vốn nếu NAV giảm tới mức hỗ trợ này.`;
        });
        rows.push(['📉 Lịch DCA theo Fibonacci', _dcaStr + ' Chia vốn theo thang để tối ưu giá vốn bình quân.']);
      }
      if (histPatternData && histPatternData.n >= 10 && histPatternData.winRate30 >= 60) {
        rows.push(['📊 Xác suất lịch sử', `${histPatternData.n} lần trong quá khứ có RSI tương tự: ${histPatternData.winRate30}% lần tăng sau 30 ngày, TB ${histPatternData.avg30>=0?'+':''}${histPatternData.avg30.toFixed(1)}%. Dữ liệu lịch sử ủng hộ việc mua vào.`]);
      } else if (histPatternData && histPatternData.n >= 10 && histPatternData.winRate30 <= 40) {
        rows.push(['📊 Cảnh báo lịch sử', `${histPatternData.n} lần trong quá khứ có RSI tương tự: chỉ ${histPatternData.winRate30}% lần tăng sau 30 ngày, TB ${histPatternData.avg30.toFixed(1)}%. Lịch sử không ủng hộ — nên thận trọng.`]);
      }
    } else if (score <= -3) {
      rows.push(['ℹ️ Chưa có vị thế', `Chờ tín hiệu đảo chiều rõ hơn (RSI hồi về 40–50, MACD cắt lên) trước khi mua vào. Không nên bắt dao đang rơi.`]);
    } else {
      rows.push(['ℹ️ Chưa có vị thế', `Tín hiệu trung lập — có thể mua một phần nhỏ (thử nghiệm) nếu đây là quỹ bạn muốn tích lũy dài hạn.`]);
    }
    if (pfItem) {
      const pnlPct = pfItem.avg_cost > 0 ? (curr - pfItem.avg_cost) / pfItem.avg_cost * 100 : 0;
      if (score <= -3 && expTech) {
        rows.push(['💼 Đang nắm giữ', `Cân nhắc chốt một phần lời${pnlPct > 5 ? ` (hiện đang lãi ${pnlPct.toFixed(1)}%)` : ''}. Kỹ thuật đang tiêu cực và giá ở vùng cao.`]);
      } else if (score >= 3 && cheapTech) {
        rows.push(['💼 Đang nắm giữ', `Tiếp tục nắm — tín hiệu kỹ thuật tốt. Có thể mua thêm để tăng vị thế${isBond ? ' (quỹ trái phiếu phù hợp tích lũy đều)' : ''}.`]);
        if (sizingHint) rows.push(['📐 Tỷ trọng mua thêm', sizingHint]);
      } else {
        rows.push(['💼 Đang nắm giữ', `Giữ vị thế hiện tại. Chưa có lý do kỹ thuật rõ ràng để mua thêm hoặc bán bớt.`]);
      }
      // Stop-loss guidance using Fibonacci support
      if (fibSupport.length && pfItem.avg_cost > 0) {
        const stopLevel = fibSupport[fibSupport.length - 1]; // Nearest support below
        const stopPct = (stopLevel.nav - pfItem.avg_cost) / pfItem.avg_cost * 100;
        if (Math.abs(stopPct) < 25) { // Only show if reasonable
          rows.push(['🛑 Mức tham khảo thoát', `Hỗ trợ Fibonacci ${stopLevel.label}: ${fmt(Math.round(stopLevel.nav))} đ${stopPct < 0 ? ` (−${Math.abs(stopPct).toFixed(1)}% so với giá vốn)` : ''}. Nếu NAV phá xuống vùng này, đáng xem xét cắt lỗ một phần.`]);
        }
      }
      // WEB-044: Forward P&L scenarios — show concrete gain/loss at key Fib levels
      if (pfItem.units > 0 && pfItem.avg_cost > 0 && pfItem.cost > 0) {
        const _u = pfItem.units, _c = pfItem.cost, _ac = pfItem.avg_cost;
        const _scen = [];
        if (fibResist.length) {
          const _t = fibResist[0];
          const _tP = (_t.nav - _ac) / _ac * 100, _tV = (_t.nav * _u - _c) / 1e6;
          if (Math.abs(_tP) < 50) _scen.push('Đạt ' + _t.label + ' (' + fmt(Math.round(_t.nav)) + 'đ): <b style="color:' + (_tP>=0?'var(--buy)':'var(--sell)') + '">' + (_tP>=0?'+':'') + _tP.toFixed(1) + '% (' + (_tV>=0?'+':'') + _tV.toFixed(2) + 'M₫)</b>');
        }
        if (fibSupport.length) {
          const _s = fibSupport[0];
          const _sP = (_s.nav - _ac) / _ac * 100, _sV = (_s.nav * _u - _c) / 1e6;
          if (Math.abs(_sP) < 50) _scen.push('Về ' + _s.label + ' (' + fmt(Math.round(_s.nav)) + 'đ): <b style="color:' + (_sP>=0?'var(--buy)':'var(--sell)') + '">' + (_sP>=0?'+':'') + _sP.toFixed(1) + '% (' + (_sV>=0?'+':'') + _sV.toFixed(2) + 'M₫)</b>');
        }
        if (_scen.length) rows.push(['📊 Kịch bản P&L', _scen.join('  •  ')]);
      }
    }
    // Target price (upside) from Fibonacci resistance
    if (score >= 2 && fibResist.length) {
      const target = fibResist[0]; // Nearest resistance above
      const upside = (target.nav - curr) / curr * 100;
      if (upside > 0.5 && upside < 30) {
        rows.push(['🎯 Mục tiêu giá', `Kháng cự Fibonacci ${target.label}: ${fmt(Math.round(target.nav))} đ (+${upside.toFixed(1)}% từ NAV hiện tại). Đây là vùng giá chốt lời ngắn hạn hợp lý.`]);
      }
    }
    const watchConds = [];
    if (rsi < 20)              watchConds.push(`RSI vượt 25 từ vùng cực quá bán (hiện ${rsi.toFixed(0)}) — xác nhận lực bán suy yếu, dấu hiệu đảo chiều sắp xảy ra`);
    else if (rsi < 35)         watchConds.push(`RSI hồi về 40–45 từ vùng quá bán (hiện ${rsi.toFixed(0)}) — xác nhận đảo chiều ngắn hạn`);
    if (_rsiDelta != null && _rsiDelta <= -8) watchConds.push(`RSI đang giảm nhanh (−${Math.abs(_rsiDelta)}pts/7 ngày) — chờ đà giảm RSI chậm lại trước khi mua vào`);
    if (rsi < 50 && macd < 0) watchConds.push('MACD cắt lên 0 (đà giảm kết thúc)');
    if (rsi > 65)             watchConds.push('RSI giảm về dưới 60 (áp lực mua hạ nhiệt)');
    if (bb < 30 || bb > 80)  watchConds.push('BB%B về vùng 30–70 (giá trở về bình thường)');
    if (Math.abs(score) <= 2) watchConds.push('Score đạt ≥3 hoặc ≤−3');
    if (typeof maCrossSignal !== 'undefined' && maCrossSignal === 'below') watchConds.push('MA20 cắt lên MA50 (Golden Cross)');
    if (typeof fibResist !== 'undefined' && fibResist.length && score >= 2) {
      const _fr = fibResist[0]; const _pctFr = ((_fr.nav-curr)/curr*100).toFixed(1);
      watchConds.push(`NAV vượt kháng cự ${_fr.label} (+${_pctFr}% = ${fmt(Math.round(_fr.nav))}đ) → xác nhận breakout tăng`);
    }
    if (typeof bbW !== 'undefined' && bbW && bbW.curr < 4 && bbW.expanding === false) {
      const _macdDir = (s?.macd_hist??s?.macd??0);
      watchConds.push(`Breakout từ dải hẹp (BB Width ${bbW.curr.toFixed(1)}%) — MACD ${_macdDir>0?'dương → hướng tăng khả thi':_macdDir<0?'âm → cẩn thận hướng giảm':'gần 0 → hướng chưa rõ'}`);
    }
    if (watchConds.length) rows.push(['👀 Theo dõi khi', watchConds.join('; ')]);
    return rows.map(([lbl, txt]) => `
      <div style="border-top:1px solid var(--bdr);padding:8px 0">
        <div style="font-size:14px;font-weight:700;color:var(--txt3);margin-bottom:3px;font-family:var(--mono);letter-spacing:.04em">${lbl}</div>
        <div style="font-size:14px;color:var(--txt1);line-height:1.6">${txt}</div>
      </div>`).join('');
  })();
  _lastStrategyHtml = strategyHtml;
  // WEB-040: Monthly seasonality — avg return per calendar month from historical NAV
  const _seasonData = (() => {
    if (pts.length < 120) return null;
    const ymMap = {};
    for (const p of pts) {
      const ym = p.date.slice(0, 7);
      if (!ymMap[ym]) ymMap[ym] = {first: p.nav, last: p.nav, m: parseInt(p.date.slice(5, 7))};
      else ymMap[ym].last = p.nav;
    }
    const buckets = {};
    for (const {first, last, m} of Object.values(ymMap)) {
      if (first > 0) { if (!buckets[m]) buckets[m] = []; buckets[m].push((last - first) / first * 100); }
    }
    const rows = [];
    for (let m = 1; m <= 12; m++) {
      const rets = buckets[m];
      if (rets && rets.length >= 2) rows.push({m, n: rets.length, avg: rets.reduce((a,b)=>a+b,0)/rets.length, winRate: Math.round(rets.filter(r=>r>0).length/rets.length*100)});
    }
    return rows.length >= 8 ? rows : null;
  })();
  const seasonHtml = _seasonData ? (() => {
    const ML = ['T1','T2','T3','T4','T5','T6','T7','T8','T9','T10','T11','T12'];
    const curM = new Date().getMonth() + 1;
    const sorted = [..._seasonData].sort((a,b) => b.avg - a.avg);
    const bestMs = sorted.slice(0, 2).map(r => r.m);
    const worstMs = sorted.slice(-2).map(r => r.m);
    const cells = _seasonData.map(r => {
      const isCur = r.m === curM, isBest = bestMs.includes(r.m), isWorst = worstMs.includes(r.m);
      const c  = isCur ? 'var(--c0)' : isBest ? 'var(--buy)' : isWorst ? 'var(--sell)' : r.avg >= 0 ? '#4ade8088' : '#f8717188';
      const bg = isCur ? '#00e5ff22' : isBest ? '#4ade8022' : isWorst ? '#f8717122' : 'var(--bg2)';
      return '<div style="background:' + bg + ';border:1px solid ' + c + '33;border-radius:6px;padding:5px 4px;text-align:center">'
        + '<div style="font-size:14px;color:' + (isCur ? 'var(--c0)' : 'var(--txt3)') + ';font-family:var(--mono)">' + ML[r.m-1] + '</div>'
        + '<div style="font-size:14px;font-weight:700;color:' + c + ';font-family:var(--mono);margin-top:2px">' + (r.avg >= 0 ? '+' : '') + r.avg.toFixed(1) + '%</div>'
        + '<div style="font-size:8px;color:var(--txt3)">' + r.winRate + '%↑</div>'
        + '</div>';
    }).join('');
    const bestDesc  = sorted.slice(0, 2).map(r => ML[r.m-1] + ' (' + (r.avg >= 0 ? '+' : '') + r.avg.toFixed(1) + '%)').join(', ');
    const worstDesc = sorted.slice(-2).reverse().map(r => ML[r.m-1] + ' (' + r.avg.toFixed(1) + '%)').join(', ');
    const curRow = _seasonData.find(r => r.m === curM);
    const curDesc = curRow ? (curRow.avg >= 0 ? '+' : '') + curRow.avg.toFixed(1) + '% trung bình · ' + curRow.winRate + '% số năm tăng (' + curRow.n + ' năm dữ liệu)' : 'chưa đủ dữ liệu';
    return _mkSect('MÙA VỤ THEO THÁNG', '\u{1F4C5}', '<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:4px;margin-bottom:10px">' + cells + '</div>'
      + '<div style="font-size:14px;color:var(--txt2);line-height:1.8">'
      + '<span style="color:var(--buy)">▲ Mạnh nhất:</span> ' + bestDesc + '  ·  <span style="color:var(--sell)">▼ Yếu nhất:</span> ' + worstDesc + '.<br>'
      + 'Tháng này (<b style="color:var(--c0)">' + ML[curM-1] + '</b>): ' + curDesc + '.'
      + '<br><span style="color:var(--txt3)">Dựa trên lịch sử NAV — không đảm bảo lặp lại.</span>'
      + '</div>');
  })() : '';
  // WEB-045: Entry Zone Quality Score — composite 0-100 from RSI/BB/52W/vol
  const _entryQualHtml = (s && techRel !== 'N/A' && pts.length >= 30) ? (() => {
    const _rsiQ = (s.rsi ?? 50) < 30 ? 100 : (s.rsi ?? 50) < 40 ? 80 : (s.rsi ?? 50) < 50 ? 60 : (s.rsi ?? 50) < 60 ? 40 : (s.rsi ?? 50) < 70 ? 20 : 5;
    const _bbQ  = (s.bb_pct ?? 50) < 10 ? 100 : (s.bb_pct ?? 50) < 25 ? 80 : (s.bb_pct ?? 50) < 40 ? 65 : (s.bb_pct ?? 50) < 60 ? 45 : (s.bb_pct ?? 50) < 75 ? 20 : 5;
    const _52Q  = pct52 < 10 ? 100 : pct52 < 25 ? 80 : pct52 < 40 ? 65 : pct52 < 60 ? 45 : pct52 < 75 ? 25 : 10;
    const _vBn  = _volRegime == null ? 0 : _volRegime < 0.6 ? 8 : _volRegime > 1.4 ? -8 : 0;
    const _eq   = Math.min(100, Math.max(0, Math.round(_rsiQ * 0.38 + _bbQ * 0.27 + _52Q * 0.27 + (_vBn * 0.08 + 4))));
    const _eqC  = _eq >= 70 ? 'var(--buy)' : _eq >= 50 ? '#facc15' : 'var(--sell)';
    const _eqLb = _eq >= 75 ? 'Xuất sắc — vùng tích lũy tốt' : _eq >= 60 ? 'Tốt — đáng cân nhắc mua vào' : _eq >= 45 ? 'Trung bình — nên chờ thêm tín hiệu' : 'Thấp — chưa phải vùng mua tốt';
    return '<div style="background:var(--bg3);border-radius:8px;padding:10px 12px;margin-bottom:10px">'
      + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
      + '<div style="font-size:14px;color:var(--txt2)">Chất lượng vùng mua hiện tại</div>'
      + '<div style="font-family:var(--mono);font-size:18px;font-weight:700;color:' + _eqC + '">' + _eq + '<span style="font-size:14px;font-weight:400;color:var(--txt3)">/100</span></div>'
      + '</div>'
      + '<div style="height:5px;background:var(--bdr);border-radius:3px;margin-bottom:5px">'
      + '<div style="height:100%;width:' + _eq + '%;background:' + _eqC + ';border-radius:3px"></div>'
      + '</div>'
      + '<div style="font-size:14px;color:' + _eqC + ';margin-bottom:3px">' + _eqLb + '</div>'
      + '<div style="font-size:14px;color:var(--txt3)">RSI ' + ((s.rsi ?? 50)).toFixed(0) + ' (38%) · BB% ' + ((s.bb_pct ?? 50)).toFixed(0) + '% (27%) · Vị trí 52T: ' + pct52 + '% (27%) · Biến động (8%)</div>'
      + '</div>';
  })() : '';
  // WEB-053: Lag-1 return autocorrelation — momentum vs mean-reversion signal
  const _autoCorr = (() => {
    if (pts.length < 40) return null;
    const navs = pts.map(p => p.nav);
    const rets = [];
    for (let i = 1; i < navs.length; i++) if (navs[i-1] > 0) rets.push((navs[i] - navs[i-1]) / navs[i-1]);
    const n = rets.length - 1;
    if (n < 20) return null;
    const mu = rets.reduce((s,r) => s+r, 0) / rets.length;
    const v = rets.reduce((s,r) => s + (r-mu)**2, 0) / rets.length;
    if (v < 1e-12) return null;
    let cov = 0;
    for (let i = 0; i < n; i++) cov += (rets[i] - mu) * (rets[i+1] - mu);
    return (cov / n) / v;
  })();
  const conclusionHtml = _mkSect('KẾT LUẬN & KHUYẾN NGHỊ', '💡', `
    <div style="background:${score >= 3 ? '#4ade8011' : score <= -3 ? '#f8717111' : '#facc1511'};border:1px solid ${score >= 3 ? '#4ade8033' : score <= -3 ? '#f8717133' : '#facc1533'};border-radius:10px;padding:14px;margin-bottom:10px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
        <div style="font-family:var(--mono);font-size:20px;font-weight:700;color:${scoreColor}">${score > 0 ? '+' : ''}${score}</div>
        <div>
          <div style="font-size:16px;font-weight:700;color:${scoreColor}">${scoreDesc}</div>
          <div style="font-size:14px;color:var(--txt3)">${ftLabel} · TA ${relLabel}</div>
        </div>
      </div>
      <div style="font-size:14px;color:var(--txt1);line-height:1.7;font-weight:500${apiConclusion ? ';margin-bottom:10px' : ''}">${summaryLine}${_summaryRsiCtx}</div>
      ${apiConclusion ? `<div style="font-size:14px;color:var(--txt2);line-height:1.7;border-top:1px solid var(--bdr);padding-top:8px">${esc(apiConclusion)}</div>` : ''}
    </div>
    ${s?.tech_reliability === 'LOW' ? `<div style="background:#facc1511;border:1px solid #facc1533;border-radius:8px;padding:8px 12px;margin-bottom:8px;display:flex;gap:8px;align-items:flex-start"><span style="font-size:14px">⚠️</span><div style="font-size:14px;color:var(--txt2);line-height:1.6"><b style="color:#facc15">TA độ tin cậy THẤP</b> — ${s?.fund_type === 'bond' ? 'Quỹ trái phiếu có NAV biến động nhỏ và phân phối đều: RSI/MACD/BB được thiết kế cho cổ phiếu, ít hiệu quả hơn với trái phiếu. Ưu tiên xem Hiệu suất dài hạn và Sharpe ratio; tín hiệu kỹ thuật chỉ mang tính tham khảo.' : 'Tín hiệu kỹ thuật hiện ít tin cậy — cân nhắc thêm yếu tố cơ bản.'}</div></div>` : ''}
    ${_entryQualHtml}
    ${_autoCorr != null ? `<div style="background:var(--bg3);border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:14px;color:var(--txt2);line-height:1.6">
      <b style="color:var(--txt1)">Xu hướng hiện tại có bền không?</b> —
      ${Math.abs(_autoCorr) <= 0.1 ? 'Quỹ này lên xuống khá ngẫu nhiên, không có xu hướng rõ ràng trong ngắn hạn. Nên nhìn tín hiệu trung và dài hạn thay vì giao dịch ngắn hạn.'
        : _autoCorr > 0.1 ? 'Xu hướng có xu hướng bền vững — nếu đang tăng thì thường tiếp tục tăng, nếu đang giảm thì thường tiếp tục giảm. Không nên "đánh ngược" xu hướng khi chưa có dấu hiệu đảo chiều rõ ràng.'
        : 'Quỹ hay tự phục hồi sau mỗi cú giảm — các đợt xuống mạnh thường không kéo dài. Đây là đặc điểm tốt cho chiến lược DCA (mua đều đặn).'}
    </div>` : ''}
    <div style="margin-top:8px;background:#facc1511;border:1px solid #facc1522;border-radius:6px;padding:8px 12px;font-size:14px;color:var(--txt3);line-height:1.6">
      ⚠️ Phân tích dựa trên dữ liệu kỹ thuật lịch sử NAV. Không phải lời khuyên đầu tư tài chính. Quỹ mở có thể bị ảnh hưởng bởi thị trường chung, chính sách tiền tệ, và yếu tố vĩ mô ngoài tầm dự báo của chỉ báo kỹ thuật.
    </div>
    <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
      <button onclick="_quickTrade('${code}','buy')" style="flex:1;min-width:100px;background:${score>=3?'var(--buy)':'var(--bg3)'};color:${score>=3?'#000':'var(--txt1)'};border:1px solid ${score>=3?'var(--buy)':'var(--bdr)'};border-radius:7px;padding:9px 12px;font-size:14px;font-weight:700;cursor:pointer;font-family:var(--sans)">📈 Mua ${code}</button>
      ${pfItem ? `<button onclick="_quickTrade('${code}','sell')" style="flex:1;min-width:100px;background:${score<=-3?'var(--sell)':'var(--bg3)'};color:${score<=-3?'#fff':'var(--txt1)'};border:1px solid ${score<=-3?'var(--sell)':'var(--bdr)'};border-radius:7px;padding:9px 12px;font-size:14px;font-weight:700;cursor:pointer;font-family:var(--sans)">📉 Bán bớt</button>` : ''}
    </div>`);

  // Compact 3-tile indicator row — always visible at top
  const _rsi = s?.rsi ?? null, _bb = s?.bb_pct ?? null, _macd = s?.macd_hist ?? null;
  const _rsiC = _rsi==null?'var(--txt2)':_rsi<30?'var(--buy)':_rsi>70?'var(--sell)':'var(--txt1)';
  const _rsiLbl = _rsi==null?'—':_rsi<25?'Bán quá nhiều → có thể mua':_rsi<40?'Đang bị bán nhiều':_rsi<60?'Cân bằng':_rsi<75?'Đang được mua nhiều':'Mua quá nhiều → cẩn thận';
  const _bbC = _bb==null?'var(--txt2)':_bb<20?'var(--buy)':_bb>80?'var(--sell)':'var(--txt1)';
  const _bbLbl = _bb==null?'—':_bb<20?'Giá đang rất thấp → cơ hội mua':_bb>80?'Giá đang rất cao → cẩn thận':'Giá ở mức bình thường';
  const _macdC = _macd==null?'var(--txt2)':_macd>0?'var(--buy)':'var(--sell)';
  const _macdLbl = _macd==null?'—':_macd>50?'Tăng mạnh':_macd>0?'Đang tăng dần':_macd>-50?'Đang giảm dần':'Giảm mạnh';
  const _mkTile = (label,techName,val,color,sublabel) => `<div style="background:var(--bg2);border-radius:8px;padding:10px 8px;text-align:center;border:1px solid var(--bdr)"><div style="font-size:14px;color:var(--txt1);margin-bottom:1px;font-family:var(--mono);letter-spacing:.04em;font-weight:600">${label}</div><div style="font-size:14px;color:var(--txt3);margin-bottom:5px;font-family:var(--mono)">${techName}</div><div style="font-size:20px;font-weight:700;font-family:var(--mono);color:${color};line-height:1.1">${val}</div><div style="font-size:14px;color:${color};margin-top:4px;font-weight:600;line-height:1.3">${sublabel}</div></div>`;
  const compactIndRow = s ? `<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:12px">${_mkTile('ĐÀ MUA/BÁN','RSI (14)',_rsi!=null?_rsi.toFixed(1):'—',_rsiC,_rsiLbl)}${_mkTile('VỊ TRÍ GIÁ','BB %B',_bb!=null?_bb.toFixed(1)+'%':'—',_bbC,_bbLbl)}${_mkTile('XU HƯỚNG','MACD Hist.',_macd!=null?(_macd>0?'+':'')+_macd.toFixed(0):'—',_macdC,_macdLbl)}</div>` : '';

  // Collapsible section wrapper — strips _mkSect outer div if present to avoid double headers
  const _col = (title, emoji, html, open=false) => {
    if (!html?.trim()) return '';
    // _mkSect wraps in <div style="margin-bottom:..."><div style="font-size:14px...">TITLE</div>BODY</div>
    // Strip that wrapper so _col's <summary> is the only header
    let body = html.replace(/^[\s]*<div[^>]*margin-bottom:\d+px[^>]*>[\s]*<div[^>]*font-size:\d+px[^>]*>[\s\S]*?<\/div>[\s]*/,'').replace(/[\s]*<\/div>[\s]*$/,'');
    if (!body.trim()) body = html; // fallback if regex didn't match
    return `<details${open?' open':''} style="margin-bottom:1px"><summary class="collapsible-hdr"><span>${emoji}</span><span>${title}</span><span class="collapsible-arrow">›</span></summary><div class="collapsible-body">${body}</div></details>`;
  };

  // PI compact strip — show portfolio summary above fund analysis
  const _piStrip = document.getElementById('hist-pi-compact');
  if (_piStrip) {
    const _pf = _me?.portfolio;
    if (_pf?.items?.length) {
      const _pfTotal = _pf.total_value || 0;
      const _pfCost = _pf.items.reduce((s,h)=>s+(h.cost||0),0);
      const _pfPnl = _pfTotal - _pfCost;
      const _pfPnlP = _pfCost > 0 ? _pfPnl/_pfCost*100 : 0;
      const _pfC = _pfPnlP >= 0 ? 'var(--buy)' : 'var(--sell)';
      const _alerts = _pf.items.filter(h=>{const sg=_signals?.[h.code]||_marketData?.[h.code];return sg&&(sg.score>=4||sg.score<=-4);});
      _piStrip.style.display = '';
      _piStrip.innerHTML = `<div style="display:flex;align-items:center;gap:10px;padding:8px 14px;background:var(--bg2);border-bottom:1px solid var(--bdr);flex-wrap:wrap;cursor:pointer" onclick="_researchCode=null;document.getElementById('hist-pi-compact').style.display='none'">
        <span style="font-size:14px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;flex-shrink:0">DANH MỤC</span>
        <span style="font-family:var(--mono);font-size:14px;font-weight:700;color:${_pfC}">${_pfPnlP>=0?'+':''}${_pfPnlP.toFixed(1)}%</span>
        <span style="font-size:14px;color:${_pfC}">${_pfPnl>=0?'+':''}${(_pfPnl/1e6).toFixed(2)}M đ</span>
        ${_alerts.length ? `<span style="font-size:14px;background:#facc1522;color:#facc15;border:1px solid #facc1544;border-radius:4px;padding:2px 7px;font-family:var(--mono)">${_alerts.length} tín hiệu ⚡</span>` : ''}
        <span style="margin-left:auto;font-size:14px;color:var(--txt3)">${_pf.items.length} quỹ · Tổng ${(_pfTotal/1e6).toFixed(1)}M đ</span>
      </div>`;
    } else {
      _piStrip.style.display = 'none';
    }
  }

  panel.innerHTML = `<div style="padding:8px 0 20px">
    ${headerHtml}
    ${compactIndRow}
    ${pnlHtml}
    ${conclusionHtml}
    ${_col('NÊN MUA, BÁN, HAY GIỮ?','⚡',indHtml,true)}
    ${_col('SINH LỜI BAO NHIÊU?','📈',perfHtml,true)}
    ${_col('QUỸ NÀY AN TOÀN KHÔNG?','🛡️',riskHtml)}
    ${_col('GIÁ ĐANG CAO HAY THẤP?','📍',rangeHtml)}
    ${_col('THÁNG NÀO THƯỜNG TĂNG?','📅',seasonHtml)}
    ${_col('CHI TIẾT KỸ THUẬT NÂNG CAO','🔬',advHtml)}
    ${_col('DỰ BÁO TRƯỚC CÓ ĐÚNG KHÔNG?','📊',histPatternHtml)}
    ${_col('DỰ ĐOÁN GIÁ TỚI ĐÂY','🔮',predHtml)}
  </div>`;
  // Re-render below-chart now that strategyHtml is ready
  _renderBelowChart(_histPageCode);
}

// WEB-011: Gold analysis in Phân Tích tab ──────────────────────────────────────
async function loadGoldAnalysis() {
  _histPageCode = 'GOLD_SJC';
  const lbl = document.getElementById('hist-fund-label');
  if (lbl) lbl.textContent = '🥇 VÀNG SJC';
  // Update chart column header immediately so it doesn't show previous fund
  const navHdr = document.getElementById('hist-nav-header');
  if (navHdr) navHdr.innerHTML = '<div style="display:flex;align-items:center;gap:8px"><span style="font-family:var(--mono);font-size:14px;font-weight:700;color:#fbbf24">🥇 VÀNG SJC</span></div>';
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
    r.classList.toggle('active', !!r.getAttribute('onclick')?.includes('GOLD_SJC'));
  });
  const chartEl=document.getElementById('hist-chart-area'); if(!chartEl) return;
  chartEl.innerHTML=spin();
  try {
    if (!_goldData) {
      const d=await apiFetch(`/api/gold?user_id=${USER_ID}`);
      if(d?.portfolio?.portfolio!==undefined)d.portfolio=d.portfolio.portfolio;
      _goldData=d;
    }
    const prod='VANGTODAYAPI:SJC_1L';
    const hist=await apiFetch('/api/gold/price_history/'+encodeURIComponent(prod)).catch(()=>({history:[]}));
    let history=hist.history||[];
    if (_histRange && _histRange !== 'ALL') {
      const days={'1M':30,'3M':90,'6M':180,'1Y':365,'3Y':1095}[_histRange]||30;
      const cutoff=new Date(); cutoff.setDate(cutoff.getDate()-days);
      const cut=cutoff.toISOString().slice(0,10);
      history=history.filter(h=>h.date>=cut);
    }
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
      chartEl.innerHTML='<div style="color:var(--txt2);font-size:14px;padding:24px;text-align:center;line-height:1.7">📊<br>Chưa có lịch sử giá vàng SJC.<br><span style="font-size:14px;color:var(--txt3)">Dữ liệu lịch sử chưa được tải.</span></div>';
    }
  } catch(e) { if(chartEl) chartEl.innerHTML=renderErr('Lỗi: '+e.message); }
  _renderGoldAnalysisPanel();
  _renderBelowChart('GOLD_SJC');
}

function _renderGoldAnalysisPanel() {
  const panel=document.getElementById('hist-analysis-panel'); if(!panel) return;
  const s=_goldData?.signals;
  const hasData = s && (s.price || s.rsi != null);
  if (!hasData) {
    panel.innerHTML=`<div style="color:var(--txt2);font-size:14px;padding:16px;text-align:center;line-height:1.7">
      <div style="font-size:22px;margin-bottom:8px">🥇</div>
      <div style="color:var(--txt1);font-weight:600;font-family:var(--mono);font-size:14px;margin-bottom:6px">VÀNG SJC</div>
      <div>Chưa có dữ liệu tín hiệu vàng.<br><span style="font-size:14px;color:var(--txt3)">Cần fetch giá SJC để tính RSI/BB%/MACD.</span></div>
    </div>`;
    return;
  }
  const rsi=s.rsi||50, bb=s.bb_pct||50, score=s.score||0;
  const rsiColor=rsi<35?'var(--buy)':rsi>65?'var(--sell)':'var(--txt2)';
  const rsiLabel=rsi<33?'Quá bán':rsi<48?'Yếu':rsi>70?'Quá mua':rsi>55?'Mạnh':'Trung tính';
  const bbColor=bb<25?'var(--buy)':bb>75?'var(--sell)':'var(--txt2)';
  const priceHtml=s.price?`
    <div style="background:var(--bg3);border-radius:8px;padding:10px 12px;margin-bottom:10px">
      <div style="font-size:14px;font-family:var(--mono);color:var(--txt2);letter-spacing:.05em;margin-bottom:6px">GIÁ VÀNG SJC HIỆN TẠI</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
        <div><div style="font-size:14px;color:var(--txt3)">Giá bán</div><div style="font-family:var(--mono);font-size:14px;font-weight:600">${fmt(s.price)} đ/lượng</div></div>
        <div><div style="font-size:14px;color:var(--txt3)">Thay đổi ngày</div><div class="pnl ${pnlC(s.chg_pct||0)}" style="font-family:var(--mono);font-size:14px;font-weight:600">${fmtP(s.chg_pct||0)}</div></div>
        ${s.ma20?`<div><div style="font-size:14px;color:var(--txt3)">MA20</div><div style="font-family:var(--mono);font-size:14px">${fmt(s.ma20)} đ</div></div>`:''}
        ${s.ma50?`<div><div style="font-size:14px;color:var(--txt3)">MA50</div><div style="font-family:var(--mono);font-size:14px">${fmt(s.ma50)} đ</div></div>`:''}
      </div>
    </div>`:'';
  const indHtml=`
    <div style="font-size:14px;font-family:var(--mono);color:var(--txt2);letter-spacing:.05em;margin-bottom:8px">CHỈ SỐ KỸ THUẬT — VÀNG SJC</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
      <div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:14px;color:var(--txt3);margin-bottom:4px">RSI (14)</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${rsiColor}">${rsi.toFixed?rsi.toFixed(1):rsi}</div>
        <div style="font-size:14px;color:${rsiColor};margin-top:2px">${rsiLabel}</div>
        <div style="height:4px;background:var(--bdr);border-radius:2px;margin-top:6px"><div style="height:100%;width:${Math.min(rsi,100)}%;background:${rsiColor};border-radius:2px"></div></div>
      </div>
      <div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:14px;color:var(--txt3);margin-bottom:4px">BB %B</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${bbColor}">${bb.toFixed?bb.toFixed(1):bb}%</div>
        <div style="font-size:14px;color:${bbColor};margin-top:2px">${bb<25?'Gần band dưới':bb>75?'Gần band trên':'Giữa dải'}</div>
        <div style="height:4px;background:var(--bdr);border-radius:2px;margin-top:6px"><div style="height:100%;width:${Math.min(bb,100)}%;background:${bbColor};border-radius:2px"></div></div>
      </div>
      <div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:14px;color:var(--txt3);margin-bottom:4px">Score</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${score>0?'var(--buy)':score<0?'var(--sell)':'var(--txt2)'}">${score>0?'+':''}${score}</div>
        <div style="font-size:14px;color:var(--txt3);margin-top:2px">Thang vàng (max ±4)</div>
      </div>
      ${s.ma20?`<div style="background:var(--bg3);border-radius:8px;padding:8px 10px">
        <div style="font-size:14px;color:var(--txt3);margin-bottom:4px">Xu hướng MA</div>
        <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${s.price>s.ma20?'var(--buy)':'var(--sell)'}">
          ${s.price>s.ma20?'↑ Trên MA20':'↓ Dưới MA20'}
        </div>
        <div style="font-size:14px;color:var(--txt3);margin-top:2px">${s.ma50?(s.price>s.ma50?'↑ Trên MA50':'↓ Dưới MA50'):''}</div>
      </div>`:'' }
    </div>`;
  const scoreDesc=score>=3?'MUA':score>=1?'TÍCH LŨY':score<=-2?'THẬN TRỌNG':'HOLD';
  const scoreColor=score>=1?'var(--buy)':score<=-2?'var(--sell)':'var(--txt2)';
  const conclusionHtml=`
    <div style="background:var(--bg3);border-radius:8px;padding:8px 12px;text-align:center">
      <div style="font-size:14px;font-family:var(--mono);color:var(--txt3);letter-spacing:.06em;margin-bottom:4px">KẾT LUẬN — VÀNG SJC</div>
      <div style="font-family:var(--mono);font-size:14px;font-weight:700;color:${scoreColor}">${s.signal||('Score '+(score>0?'+':'')+score+' — '+scoreDesc)}</div>
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
        el.innerHTML=`<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:12px;padding:32px;text-align:center">
          <div style="font-size:36px;opacity:.3">⏱</div>
          <div style="font-size:14px;font-weight:600;color:var(--txt1)">${code} — Chưa có lịch sử T+2</div>
          <div style="font-size:14px;color:var(--txt3);max-width:320px;line-height:1.7">Biểu đồ T+2 so sánh NAV dự báo vs thực tế. Dữ liệu tích lũy sau khi pipeline T+2 chạy đủ ngày trên Railway.<br>Trên môi trường local, dữ liệu T+2 chưa có.</div>
        </div>`;
        const st=document.getElementById('hist-stats');
        if(st) st.innerHTML=`<div class="sum-row"><span class="sum-label">Quỹ</span><span class="sum-val">${code}</span></div><div style="font-size:14px;color:var(--txt2);margin-top:8px">Chưa có dữ liệu chấm điểm T+2</div>`;
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
    <div style="margin-top:8px;font-size:14px;color:var(--txt2)">Đường xanh = Thực tế · Vàng đứt = T+2 dự báo</div>`;
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
    if(st) st.innerHTML=`<div style="font-size:14px;color:var(--txt2)">Giá vàng ${prods.length} sản phẩm · ${days} phiên</div>`;
    return;
  }
  try{
    const prods=Object.keys(_goldData?.portfolio?.by_product||{});
    if(!prods.length){el.innerHTML='<div style="padding:24px;text-align:center;color:var(--txt2)">Chưa có vàng trong danh mục</div>';return;}
    const histories=await Promise.all(prods.map(p=>apiFetch('/api/gold/price_history/'+encodeURIComponent(p)).catch(()=>({history:[]}))));
    const labelsSet=new Set();
    histories.forEach(h=>(h.history||[]).forEach(p=>labelsSet.add(p.date)));
    let allLabels=[...labelsSet].sort();
    if (_histRange && _histRange !== 'ALL') {
      const days={'1M':30,'3M':90,'6M':180,'1Y':365,'3Y':1095}[_histRange]||30;
      const cutoff=new Date(); cutoff.setDate(cutoff.getDate()-days);
      const cut=cutoff.toISOString().slice(0,10);
      allLabels=allLabels.filter(d=>d>=cut);
    }
    const datasets=prods.map((prod,i)=>{
      const h=histories[i]?.history||[];
      const byDate=Object.fromEntries(h.map(p=>[p.date,p.sell??p.buy??p.price??null]));
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
  // Keyboard shortcut: '/' focuses market search (skip if already in input)
  document.addEventListener('keydown', e => {
    if (e.key === '/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)) {
      const search = document.getElementById('market-search');
      if (search) { e.preventDefault(); search.focus(); search.select(); }
    }
    // Escape clears search
    if (e.key === 'Escape') {
      const search = document.getElementById('market-search');
      if (search && document.activeElement === search) { search.value = ''; search.blur(); renderMarket(); }
    }
  });
});
