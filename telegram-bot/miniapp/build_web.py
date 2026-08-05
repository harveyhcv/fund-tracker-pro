OUT = r"P:\NGCG\Vibe Coding\Fund Tracker Pro\telegram-bot\miniapp\web.html"

HEAD = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fund Tracker Pro</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#060b14;--bg2:#0c1626;--bg3:#111e30;--bg4:#0a1020;--c0:#00e5ff;--buy:#4ade80;--sell:#f87171;--hold:#facc15;--txt:#e2e8f0;--txt2:#94a3b8;--txt3:#4a6080;--bdr:#1e3050;--mono:'IBM Plex Mono',monospace;--sans:'DM Sans',sans-serif;}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--txt);font-family:var(--sans);font-size:14px;display:flex}
#toast{position:fixed;top:16px;left:50%;transform:translateX(-50%);background:#1a2e4a;border:1px solid var(--c0);color:var(--txt);padding:10px 18px;border-radius:8px;font-size:13px;z-index:999;display:none;max-width:80vw;text-align:center}
#tier-bar{display:none}
.tier-chip{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:20px;font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.03em;white-space:nowrap}
.tier-chip.free{background:#1a1a2e;color:#8888aa;border:1px solid #333355}
.tier-chip.pro{background:#001a2e;color:var(--c0);border:1px solid var(--c0)}
.tier-chip.admin{background:#1a0a2e;color:#c084fc;border:1px solid #9333ea}
.tier-exp{font-size:10px;color:var(--txt2);margin-left:4px}
.tier-upgrade-hint{font-size:10px;color:var(--txt2);cursor:pointer;text-decoration:underline;text-underline-offset:2px}
/* ── Sidebar ───────────────────────────────── */
.sidebar{width:200px;min-width:200px;background:var(--bg2);border-right:1px solid var(--bdr);display:flex;flex-direction:column;height:100vh;flex-shrink:0}
.sidebar-logo{padding:16px 16px 12px;border-bottom:1px solid var(--bdr)}
.logo-mark{font-family:var(--mono);font-size:14px;font-weight:700;color:var(--c0);letter-spacing:.05em}
.logo-sub{font-family:var(--mono);font-size:8px;color:var(--txt3);letter-spacing:.12em;margin-top:2px;text-transform:uppercase}
.sidebar-nav{flex:1;padding:10px 8px;overflow-y:auto}
.nav-section-lbl{font-family:var(--mono);font-size:9px;color:var(--txt3);text-transform:uppercase;letter-spacing:.1em;padding:4px 8px 6px}
#nav{display:contents}
.nav-btn{width:100%;display:flex;align-items:center;gap:10px;padding:9px 10px;background:none;border:none;border-left:2px solid transparent;border-radius:0 6px 6px 0;color:var(--txt2);font-size:12px;font-family:var(--sans);cursor:pointer;transition:all .15s;text-align:left;position:relative}
.nav-btn:hover{color:var(--txt);background:rgba(255,255,255,.04)}
.nav-btn.active{color:var(--c0);background:rgba(0,229,255,.07);border-left-color:var(--c0)}
.nav-btn svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex-shrink:0}
.nav-badge{position:absolute;right:8px;top:50%;transform:translateY(-50%);background:var(--bg3);border:1px solid var(--bdr);color:var(--txt2);font-size:9px;font-family:var(--mono);padding:1px 5px;border-radius:10px}
.sidebar-footer{padding:10px 12px;border-top:1px solid var(--bdr);flex-shrink:0}
.sidebar-user{display:flex;align-items:center;gap:8px}
.user-avatar{width:28px;height:28px;border-radius:50%;background:var(--bg3);border:1px solid var(--bdr);display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:12px;font-weight:700;color:var(--c0);flex-shrink:0}
.user-meta{flex:1;min-width:0}
.user-name-text{font-size:12px;font-weight:600;color:var(--txt);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* ── Main ─────────────────────────────────── */
.main{flex:1;display:flex;flex-direction:column;height:100vh;overflow:hidden;min-width:0}
#app{flex:1;display:flex;flex-direction:column;overflow:hidden}
.header{height:52px;background:var(--bg2);border-bottom:1px solid var(--bdr);display:flex;align-items:center;padding:0 16px;gap:14px;flex-shrink:0;z-index:10}
.header-title{font-family:var(--mono);font-size:11px;font-weight:700;color:var(--c0);letter-spacing:.1em;text-transform:uppercase;white-space:nowrap;min-width:100px}
.header-search{flex:1;max-width:320px;position:relative}
.header-search input{background:var(--bg3);border:1px solid var(--bdr);border-radius:8px;padding:7px 10px 7px 34px;color:var(--txt);font-family:var(--mono);font-size:12px;outline:none;width:100%;box-sizing:border-box}
.header-search input:focus{border-color:var(--c0)}
.si{position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--txt3);font-size:14px;pointer-events:none}
.header-right{display:flex;align-items:center;gap:8px;margin-left:auto}
.header-chip{font-family:var(--mono);font-size:10px;color:var(--txt2);background:var(--bg3);border:1px solid var(--bdr);border-radius:6px;padding:3px 8px;white-space:nowrap}
.header-chip.live{color:var(--buy);border-color:#166534}
.content{flex:1;overflow:hidden;position:relative}
/* ── Pages ────────────────────────────────── */
.page{display:none;height:100%}
.page.active{display:flex;height:100%}
/* ── 3-col home ───────────────────────────── */
.three-col{display:flex;width:100%;height:100%;overflow:hidden}
.col{border-right:1px solid var(--bdr);display:flex;flex-direction:column;height:100%;overflow:hidden}
.col:last-child{border-right:none}
.col-portfolio{width:500px;min-width:360px;overflow-y:auto}
.col-chart{flex:1;min-width:340px;display:flex;flex-direction:column;overflow:hidden}
.col-market{flex:1.2;min-width:320px;display:flex;flex-direction:column;overflow:hidden}
#chart-col-content{flex:1;overflow-y:auto;padding:0}
#market-content{flex:1;overflow-y:auto}
/* ── Chart time range bar ── */
.chart-range-bar{display:flex;gap:4px;align-items:center}
.range-btn{background:none;border:1px solid var(--bdr);border-radius:4px;color:var(--txt2);font-family:var(--mono);font-size:10px;padding:3px 7px;cursor:pointer;transition:all .15s}
.range-btn:hover{border-color:var(--c0);color:var(--c0)}
.range-btn.active{background:rgba(0,229,255,.12);border-color:var(--c0);color:var(--c0);font-weight:600}
.market-toolbar{padding:8px 12px 0;flex-shrink:0;border-bottom:1px solid var(--bdr)}
.col-head{padding:10px 14px 8px;border-bottom:1px solid var(--bdr);flex-shrink:0;background:var(--bg2)}
.col-head-row{display:flex;justify-content:space-between;align-items:center}
.col-title{font-family:var(--mono);font-size:10px;font-weight:700;color:var(--c0);letter-spacing:.08em;text-transform:uppercase}
.col-sub{font-size:10px;color:var(--txt2);margin-top:2px}
.col-action{background:none;border:none;color:var(--txt2);font-size:12px;cursor:pointer;padding:2px 6px;border-radius:4px;font-family:var(--mono)}
.col-action:hover{color:var(--c0);background:rgba(0,229,255,.08)}
.chart-empty-state{display:flex;flex-direction:column;align-items:center;justify-content:center;height:60%;color:var(--txt2);font-size:12px;text-align:center;padding:20px;gap:10px;line-height:1.6}
.chart-empty-icon{font-size:36px;opacity:.4}
/* ── Trade grid ───────────────────────────── */
.trade-grid{display:flex;width:100%;height:100%;overflow:hidden}
.trade-col{border-right:1px solid var(--bdr);overflow:hidden;display:flex;flex-direction:column;height:100%;flex:1}
.trade-col:last-child{border-right:none}
.trade-col-left{background:var(--bg);overflow-y:auto;flex:1}
.trade-col-mid{background:var(--bg4);flex:1}
.trade-col-right{background:var(--bg);overflow:hidden;flex:1;display:flex;flex-direction:column}
.trade-right-dca{flex:1;overflow-y:auto;min-height:0;background:var(--bg)}
.trade-right-gold{flex:0 0 52%;overflow-y:auto;border-top:2px solid #fbbf24;background:rgba(251,191,36,.02)}
.col-head-gold{background:rgba(251,191,36,.08);border-bottom:1px solid rgba(251,191,36,.2);border-top:2px solid #fbbf24;flex-shrink:0}
.trade-form-area{flex:1;display:flex;flex-direction:column;overflow:hidden}
.trade-history-head{padding:8px 12px;border-bottom:1px solid var(--bdr);display:flex;justify-content:space-between;align-items:center;flex-shrink:0;background:var(--bg4);position:sticky;top:0;z-index:2}
.trade-history-scroll{flex:1;overflow-y:auto}
#order-sub-history{margin:0!important;padding:0!important}
/* ── User page ────────────────────────────── */
.user-page-scroll{overflow-y:auto;width:100%;height:100%;padding:20px}
.user-page-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:1400px}
.admin-inline-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:1400px}
.acct-card{background:var(--bg2);border:1px solid var(--bdr);border-radius:10px;padding:16px}
.acct-card-title{font-family:var(--mono);font-size:10px;color:var(--txt3);text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px;display:flex;align-items:center;gap:6px}
.acct-card-title svg{stroke:var(--txt3)}
.full-col{grid-column:1/-1}
/* ── Admin section (inline dưới user page) ── */
.admin-section{margin-top:20px;padding-top:16px;border-top:1px solid var(--bdr)}
.admin-section-hdr{font-family:var(--mono);font-size:10px;color:var(--c0);text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px;opacity:.8}
.au-card{max-width:1400px}
.au-search{background:var(--bg2);border:1px solid var(--bdr);border-radius:6px;color:var(--txt);font-family:var(--sans);font-size:12px;padding:5px 10px;outline:none;width:180px}
.au-search:focus{border-color:var(--c0)}
.au-table{width:100%;border-collapse:collapse;font-size:12px}
.au-table th{font-family:var(--mono);font-size:10px;color:var(--txt2);text-transform:uppercase;letter-spacing:.06em;padding:6px 8px;border-bottom:1px solid var(--bdr);text-align:left;white-space:nowrap}
.au-table td{padding:8px 8px;border-bottom:1px solid var(--bdr);vertical-align:middle;white-space:nowrap}
.au-row:last-child td{border-bottom:none}
.au-row:hover td{background:var(--bg2)}
.au-id{font-family:var(--mono);font-size:11px;color:var(--txt2)}
.au-name{font-weight:500}
.au-badge-admin{display:inline-block;margin-left:6px;padding:1px 5px;border-radius:3px;font-family:var(--mono);font-size:9px;background:rgba(0,229,255,.15);color:var(--c0);letter-spacing:.04em}
.section-label{font-family:var(--mono);font-size:11px;color:var(--txt2);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px;border-bottom:1px solid var(--bdr);padding-bottom:4px}
.section-ccq{color:var(--c0);border-color:rgba(0,229,255,.25)}
.section-gold{color:#fbbf24;border-color:rgba(251,191,36,.25)}
.col-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.refresh-btn{background:none;border:none;color:var(--c0);font-size:12px;font-family:var(--mono);cursor:pointer;padding:0}
.hdr{font-family:var(--mono);font-size:12px;color:var(--c0);letter-spacing:.08em;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center}
.hdr-sub{color:var(--txt2);font-size:11px}
.card{background:var(--bg2);border:1px solid var(--bdr);border-radius:10px;padding:12px;margin-bottom:6px}
.card-title{font-family:var(--mono);font-size:12px;color:var(--txt2);margin-bottom:8px;text-transform:uppercase;letter-spacing:.06em}
.badge{display:inline-block;padding:3px 8px;border-radius:20px;font-size:12px;font-family:var(--mono);font-weight:600}
.badge.buy{background:#052e1a;color:var(--buy);border:1px solid #166534}
.badge.sell{background:#2d0a0a;color:var(--sell);border:1px solid #7f1d1d}
.badge.hold{background:#2d2700;color:var(--hold);border:1px solid #713f12}
.badge.na{background:var(--bg3);color:var(--txt2);border:1px solid var(--bdr)}
.pnl{font-family:var(--mono);font-weight:600}
.pnl.pos{color:var(--buy)}.pnl.neg{color:var(--sell)}.pnl.zero{color:var(--txt2)}
.sum-row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--bdr)}
.sum-row:last-child{border:none}
.sum-row-toggle{cursor:pointer}.sum-row-toggle:active{opacity:.7}
.sum-label{color:var(--txt2);font-size:12px}
.sum-val{font-family:var(--mono);font-size:13px}
.sum-chevron{display:inline-block;font-size:9px;margin-left:2px;transition:transform .15s}
.sum-chevron.open{transform:rotate(180deg)}
.sum-detail{padding:2px 0 8px 4px;display:flex;flex-direction:column;gap:4px}
.sum-detail-row{display:flex;justify-content:space-between;font-size:11px;color:var(--txt2);font-family:var(--mono)}
.sum-detail-pct{opacity:.6;font-size:10px}
.fund-row{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--bdr);gap:8px;cursor:pointer;transition:background .15s;border-radius:6px;padding:8px 4px}
.fund-row:last-child{border:none}
.fund-row:active{background:var(--bg3)}
.fund-code{font-family:var(--mono);font-weight:700;font-size:14px;flex:0 0 auto;white-space:nowrap;background:var(--bg3);border:1px solid var(--bdr);border-radius:5px;padding:2px 7px}
.fund-info{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px}
.fund-top{display:grid;grid-template-columns:auto 1fr auto;align-items:baseline;gap:6px}
.fund-nav{font-family:var(--mono);font-size:15px;font-weight:600;color:var(--txt);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fund-sub{font-size:12px;color:var(--txt2);display:flex;align-items:center;gap:5px;white-space:nowrap;overflow:hidden}
.fund-right{text-align:right;flex:0 0 88px;display:flex;flex-direction:column;gap:4px;align-items:flex-end}
details>summary{list-style:none;cursor:pointer}
details>summary::-webkit-details-marker{display:none}
.collapsible-hdr{display:flex;align-items:center;gap:6px;padding:10px 2px;font-size:10px;font-family:var(--mono);letter-spacing:.08em;color:var(--txt2);border-top:1px solid var(--bdr)}
.collapsible-arrow{margin-left:auto;font-size:12px;transition:transform .2s;color:var(--txt3)}
details[open] .collapsible-arrow{transform:rotate(90deg)}
details .collapsible-body{padding-bottom:4px}
.sig-row{display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:center;padding:9px 4px;border-bottom:1px solid var(--bdr);cursor:pointer;border-radius:6px;transition:background .15s}
.sig-row:last-child{border:none}
.sig-row:active{background:var(--bg3)}
.sig-code{font-family:var(--mono);font-size:14px;font-weight:600}
.sig-meters{display:flex;gap:6px;align-items:center}
.meter{display:flex;flex-direction:column;align-items:center;gap:1px}
.meter-lbl{font-size:9px;color:var(--txt2);text-transform:uppercase}
.meter-bar{width:36px;height:5px;border-radius:3px;background:var(--bg3);overflow:hidden}
.meter-fill{height:100%;border-radius:3px;transition:width .4s}
.meter-val{font-size:10px;font-family:var(--mono);color:var(--txt)}
.tlog-row{background:var(--bg2);border:1px solid var(--bdr);border-radius:8px;padding:10px 12px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:flex-start}
.tlog-left{flex:1;min-width:0}
.tlog-code{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--c0)}
.tlog-meta{font-size:11px;color:var(--txt2);margin-top:2px}
.tlog-actions{display:flex;gap:6px;margin-left:8px;flex-shrink:0}
.tlog-btn{padding:4px 8px;border-radius:6px;border:none;font-size:11px;cursor:pointer;font-family:var(--sans)}
.tlog-edit{background:#1e3a5f;color:#93c5fd}
.tlog-del{background:#3b0f0f;color:#f87171}
.dca-fund{padding:10px 0;border-bottom:1px solid var(--bdr)}
.dca-fund:last-child{border:none}
.dca-fund-row{display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:center}
.dca-bar-wrap{height:5px;background:var(--bg3);border-radius:3px;margin-top:6px}
.dca-bar{height:100%;border-radius:3px;transition:width .5s}
.dca-reason{font-size:11px;color:var(--txt2);margin-top:3px}
.style-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:12px}
.style-btn{padding:8px 4px;border-radius:8px;border:1px solid var(--bdr);background:var(--bg3);color:var(--txt2);font-size:11px;font-family:var(--mono);cursor:pointer;text-align:center;line-height:1.3;transition:all .15s}
.style-btn.active{background:#001a33;border-color:var(--c0);color:var(--c0)}
.style-btn span{display:block;font-size:9px;color:var(--txt2);margin-top:2px}
.style-desc{background:var(--bg3);border-radius:8px;padding:10px;margin-bottom:12px;font-size:12px;color:var(--txt2);line-height:1.5}
.style-desc b{color:var(--txt)}
.subtab-bar{display:flex;gap:6px;margin-bottom:12px}
.subtab{flex:1;padding:9px 8px;text-align:center;border-radius:8px;border:1px solid var(--bdr);background:var(--bg3);color:var(--txt2);font-size:12px;font-family:var(--mono);cursor:pointer;transition:all .15s}
.subtab.active{background:var(--c0);color:#000;border-color:var(--c0);font-weight:600}
.tab-bar{display:flex;gap:6px;margin-bottom:12px;overflow-x:auto;padding-bottom:2px}
.tab-bar::-webkit-scrollbar{display:none}
.tab{padding:6px 14px;border-radius:20px;border:1px solid var(--bdr);font-size:12px;font-family:var(--mono);color:var(--txt2);background:none;cursor:pointer;white-space:nowrap}
.tab.active{background:var(--c0);color:#000;border-color:var(--c0)}
input:not([type=checkbox]),select,textarea{width:100%;padding:10px 12px;background:var(--bg3);border:1px solid var(--bdr);border-radius:8px;color:var(--txt);font-family:var(--mono);font-size:13px;outline:none;-webkit-appearance:none}
input:focus,select:focus,textarea:focus{border-color:var(--c0)}
.header-search input[type=text]{padding:7px 10px 7px 34px;font-size:12px;width:100%}
label{display:block;color:var(--txt2);font-size:11px;margin:10px 0 4px;text-transform:uppercase;letter-spacing:.05em}
.btn{width:100%;padding:13px;border:none;border-radius:10px;font-family:var(--sans);font-size:15px;font-weight:600;cursor:pointer;transition:opacity .15s;margin-top:8px}
.btn-buy{background:var(--buy);color:#000}.btn-sell{background:var(--sell);color:#000}.btn-primary{background:var(--c0);color:#000}
.btn:active{opacity:.7}.btn:disabled{opacity:.4;cursor:not-allowed}
.type-toggle{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:4px}
.type-btn{padding:10px;border-radius:8px;border:1px solid var(--bdr);background:var(--bg3);color:var(--txt2);font-family:var(--sans);font-weight:600;font-size:14px;cursor:pointer;text-align:center;transition:all .15s}
.type-btn.buy.active{background:#052e1a;border-color:var(--buy);color:var(--buy)}
.type-btn.sell.active{background:#2d0a0a;border-color:var(--sell);color:var(--sell)}
.type-btn.div.active{background:#1e0a3e;border-color:#7c3aed;color:#a78bfa}
.loading{text-align:center;padding:40px 20px;color:var(--txt2);font-size:13px}
.spinner{width:24px;height:24px;border:2px solid var(--bdr);border-top-color:var(--c0);border-radius:50%;animation:spin .6s linear infinite;margin:0 auto 10px}
@keyframes spin{to{transform:rotate(360deg)}}
.total-banner{background:var(--bg2);border:1px solid var(--c0);border-radius:12px;padding:14px 16px;margin-bottom:12px;text-align:center}
.total-val{font-family:var(--mono);font-size:22px;font-weight:600;color:var(--c0)}
.total-lbl{font-size:12px;color:var(--txt2);margin-bottom:4px}
.total-pnl{font-family:var(--mono);font-size:14px;margin-top:4px}
.alloc-wrap{margin-bottom:12px;background:var(--bg2);border:1px solid var(--bdr);border-radius:10px;padding:10px 12px}
.alloc-track{height:8px;border-radius:4px;overflow:hidden;display:flex;margin:6px 0;background:var(--bg3)}
.alloc-ccq{height:100%;background:var(--c0);transition:width .5s}
.alloc-gold{height:100%;background:#fbbf24;transition:width .5s}
.filter-bar{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}
.filter-btn{padding:4px 12px;border-radius:14px;border:1px solid var(--bdr);background:var(--bg3);font-size:11px;font-family:var(--mono);color:var(--txt2);cursor:pointer;transition:all .15s}
.filter-btn.active{background:var(--c0);color:#000;border-color:var(--c0);font-weight:600}
.chart-wrap{height:150px;margin:8px 0 4px;position:relative}
canvas{width:100%!important;height:100%!important}
.school-card{background:var(--bg3);border-radius:8px;padding:10px;margin-bottom:8px;border-left:3px solid var(--bdr)}
.school-card.buy{border-color:var(--buy)}.school-card.sell{border-color:var(--sell)}.school-card.hold{border-color:var(--hold)}
.school-hdr{display:flex;justify-content:space-between;align-items:flex-start;cursor:pointer;gap:8px}
.school-title{font-size:12px;font-weight:700;flex:1}.school-subtitle{font-size:10px;color:var(--txt2);margin-top:1px;font-family:var(--mono)}
.school-chevron{font-size:14px;color:var(--txt2);transition:transform .2s;flex-shrink:0}
.school-card.open .school-chevron{transform:rotate(180deg)}
.school-summary{font-size:11px;color:var(--txt2);margin-top:4px}
.school-detail{display:none;margin-top:10px;border-top:1px solid var(--bdr);padding-top:10px}
.school-card.open .school-detail{display:block}
.school-body{font-size:11px;color:var(--txt);line-height:1.7}
.school-action{margin-top:8px;padding:6px 10px;border-radius:6px;font-size:11px;font-weight:600;font-family:var(--mono)}
.school-action.buy{background:#052e1a;color:var(--buy);border-left:2px solid var(--buy)}
.school-action.sell{background:#2d0a0a;color:var(--sell);border-left:2px solid var(--sell)}
.school-action.hold{background:var(--bg2);color:var(--hold);border-left:2px solid var(--hold)}
.ind-row{display:flex;gap:6px;align-items:flex-start;font-size:12px;color:var(--txt2);padding:3px 0}
.ind-lbl{font-family:var(--mono);font-size:11px;min-width:52px;color:var(--txt2)}
/* ── Research indicator panel ── */
.res-header{display:flex;justify-content:space-between;align-items:flex-start;padding:12px 14px 10px;border-bottom:1px solid var(--bdr)}
.res-nav{font-size:20px;font-weight:700;font-family:var(--mono);color:var(--txt)}
.res-inds{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px;padding:10px 14px;border-bottom:1px solid var(--bdr);background:var(--bg2)}
.res-ind{display:flex;flex-direction:column;gap:4px}
.res-ind-lbl{font-size:9px;font-family:var(--mono);color:var(--txt2);letter-spacing:.06em;text-transform:uppercase}
.res-ind-val{font-size:14px;font-weight:700;font-family:var(--mono)}
.res-ind-desc{font-size:10px;color:var(--txt2)}
.res-score{text-align:center;padding:0 10px;border-left:1px solid var(--bdr)}
.res-score-val{font-size:26px;font-weight:800;font-family:var(--mono);line-height:1}
.res-conclusion{padding:8px 14px;font-size:12px;color:var(--txt2);line-height:1.6;border-bottom:1px solid var(--bdr)}
.ind-val{flex:1;color:var(--txt)}
.range-bar-wrap{height:6px;background:var(--bg3);border-radius:3px;margin:4px 0 2px;position:relative}
.range-bar-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--buy),var(--hold),var(--sell))}
.range-marker{position:absolute;top:-3px;width:12px;height:12px;background:var(--c0);border-radius:50%;transform:translateX(-50%)}
.conclusion{background:var(--bg3);border-radius:8px;padding:10px;font-size:12px;line-height:1.6;border-left:3px solid var(--c0)}
.section{margin-bottom:14px}
.section-hdr{font-family:var(--mono);font-size:11px;color:var(--c0);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;display:flex;align-items:center;gap:6px;white-space:nowrap;overflow-x:auto;scrollbar-width:none}
.section-hdr::-webkit-scrollbar{display:none}
.section-hdr::after{content:'';flex:1;height:1px;background:var(--bdr);min-width:12px}
.verdict{font-size:13px;font-weight:600;margin-bottom:6px}
.upgrade-feature{display:flex;align-items:center;gap:8px;font-size:13px;padding:6px 0;color:var(--txt)}
.upgrade-feature .chk{color:var(--buy);font-weight:700}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:200;display:none;align-items:flex-end}
.modal-overlay.open{display:flex}
.modal-sheet{background:var(--bg2);border-radius:16px 16px 0 0;width:100%;max-height:88vh;overflow-y:auto;padding:0 0 env(safe-area-inset-bottom);animation:slideUp .25s ease}
@keyframes slideUp{from{transform:translateY(100%)}to{transform:translateY(0)}}
.modal-handle{width:36px;height:4px;background:var(--bdr);border-radius:2px;margin:12px auto 0}
.modal-header{padding:12px 16px 8px;border-bottom:1px solid var(--bdr);display:flex;justify-content:space-between;align-items:center}
.modal-title{font-family:var(--mono);font-size:15px;font-weight:600;color:var(--c0);display:flex;align-items:baseline;gap:8px;min-width:0;flex:1;overflow:hidden}
.modal-title-code{flex-shrink:0}
.modal-title-name-wrap{overflow:hidden;white-space:nowrap;flex:1;min-width:0}
.modal-title-name{display:inline-block;color:var(--txt2);font-size:12px;font-weight:400;white-space:nowrap}
.modal-title-name.marquee{animation:titleMarquee 6s ease-in-out infinite alternate}
@keyframes titleMarquee{0%,12%{transform:translateX(0)}88%,100%{transform:translateX(var(--marquee-dist,0))}}
.modal-close{background:none;border:none;color:var(--txt2);font-size:20px;cursor:pointer;padding:4px 8px}
.modal-body{padding:12px 16px 16px}
.budget-row{display:flex;gap:8px;align-items:flex-end;margin-bottom:8px}
.budget-row input{flex:1}
.budget-row .btn{width:auto;margin:0;padding:10px 16px;flex:0 0 auto}
.gp-btn{flex:1;padding:5px 0;border-radius:6px;border:1px solid var(--bdr);font-size:11px;font-family:var(--mono);color:var(--txt2);background:var(--bg3);cursor:pointer}
.gp-btn.gp-active{background:var(--c0);color:#000;border-color:var(--c0);font-weight:700}
.ref-box{display:flex;gap:8px;align-items:center;margin-bottom:6px}
/* ── Watch Modal ─────────────────────────── */
.watch-item{display:flex;align-items:center;gap:10px;padding:8px 4px;border-bottom:1px solid var(--bdr);cursor:pointer;border-radius:4px}
.watch-item:hover{background:rgba(0,229,255,.04)}
.watch-check{width:18px;height:18px;border-radius:4px;border:1.5px solid var(--bdr);display:flex;align-items:center;justify-content:center;font-size:11px;color:transparent;flex-shrink:0;transition:all .15s}
.watch-check.on{background:var(--c0);border-color:var(--c0);color:#000}
/* ── History Page ────────────────────────── */
.trade-form-inner{flex:1;overflow-y:auto;padding:0 14px;min-height:0}
.hist-page-layout{display:flex;height:100%;overflow:hidden}
.hist-page-left{width:340px;min-width:260px;border-right:1px solid var(--bdr);display:flex;flex-direction:column;overflow:hidden}
.hist-page-right{flex:1;min-width:0;display:flex;overflow:hidden}
/* Chart sub-column */
.hist-chart-col{flex:1;min-width:0;display:flex;flex-direction:column;overflow:hidden;border-right:1px solid var(--bdr)}
/* Analysis sub-column — fixed width on desktop, full width stacked on mobile */
.hist-analysis-col{width:400px;min-width:320px;flex-shrink:0;display:flex;flex-direction:column;overflow:hidden}
.hist-nav-header{padding:10px 14px 8px;border-bottom:1px solid var(--bdr);flex-shrink:0;background:var(--bg2)}
.hist-nav-hval{font-family:var(--mono);font-size:18px;font-weight:700;color:var(--txt)}
.hist-nav-hchg{font-family:var(--mono);font-size:13px;font-weight:600;margin-left:8px}
.hist-nav-right{flex:1;min-width:0;display:flex;flex-direction:column;overflow:hidden}
#hist-chart-area{height:260px;max-height:300px;min-height:180px;flex-shrink:0;position:relative;padding:8px}
#hist-chart-area canvas{width:100%!important;height:100%!important}
/* hist-fund-row inherits sig-row grid layout; active/hover states */
.hist-fund-row{border-left:3px solid transparent}
.hist-fund-row:hover,.hist-fund-row.active{background:rgba(0,229,255,.06)}
.hist-fund-row.active{border-left-color:var(--c0)!important}
/* Manual NAV entry — make summary row look like a section header */
#manual-nav-panel summary{background:var(--bg2);border-top:1px solid var(--bdr);font-size:11px;color:var(--c0);letter-spacing:.05em;font-weight:600}
#manual-nav-panel summary:hover{background:var(--bg3)}
.hist-fund-code{font-family:var(--mono);font-size:15px;font-weight:700;min-width:68px}
.hist-fund-nav{font-family:var(--mono);font-size:13px;color:var(--txt);flex:1}
.hist-fund-held{font-size:10px;color:var(--c0);font-family:var(--mono);border:1px solid var(--c0);border-radius:3px;padding:0 4px;flex-shrink:0}
/* ── NAV Import ──────────────────────────── */
.nav-import-row{display:flex;gap:6px;align-items:center}
.nav-import-row input{flex:1;font-size:12px;padding:6px 8px}
/* ── Gold School Btn ─────────────────────── */
.gp-school-btn.active{background:rgba(0,229,255,.15);border-color:var(--c0);color:var(--c0)}
/* ── Hist filter panel fix ───────────────── */
#hist-filter-panel select,#hist-filter-panel input{background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:6px}
/* ── Bulk NAV entry ──────────────────────── */
.bulk-nav-row{display:grid;grid-template-columns:2fr 2fr 2fr 20px;gap:4px;margin-bottom:5px;align-items:center}
.bulk-nav-row input{font-size:11px;padding:5px 6px;background:var(--bg);border:1px solid var(--bdr);color:var(--txt);border-radius:6px;font-family:var(--mono);width:100%;box-sizing:border-box}
.bulk-nav-row input:focus{border-color:var(--c0);outline:none}
/* ── Hist range buttons ──────────────────── */
.hist-range-btn{background:var(--bg3);border:1px solid var(--bdr);color:var(--txt2);border-radius:5px;padding:4px 8px;font-size:11px;font-family:var(--mono);cursor:pointer;transition:all .15s}
.hist-range-btn.active,.hist-range-btn:hover{background:rgba(0,229,255,.12);border-color:var(--c0);color:var(--c0)}
/* ── Responsive ──────────────────────────── */
@media(max-width:900px){
  .three-col{flex-direction:column}
  .col-portfolio,.col-market{width:100%;min-width:0;max-width:none;height:auto;overflow-y:visible;border-right:none;border-bottom:1px solid var(--bdr)}
  .col-chart{min-width:0;height:60vw;min-height:260px;max-height:400px}
  .trade-grid{flex-direction:column}
  .trade-col{min-width:0;border-right:none;border-bottom:1px solid var(--bdr)}
  .hist-page-layout{flex-direction:column}
  .hist-page-left{width:100%;min-width:0;border-right:none;border-bottom:1px solid var(--bdr);max-height:280px;overflow-y:auto}
  .hist-page-right{flex-direction:column;height:auto}
  .hist-chart-col{border-right:none;border-bottom:1px solid var(--bdr);height:56vw;min-height:240px;max-height:380px}
  .hist-analysis-col{width:100%;min-width:0;flex-shrink:1;height:60vw;min-height:300px}
  .sidebar{width:100%;height:54px;flex-direction:row;overflow-x:auto;border-right:none;border-top:1px solid var(--bdr);position:fixed;bottom:0;left:0;right:0;z-index:100;background:var(--bg2);padding:0}
  .nav-btn{flex-direction:column;padding:6px 12px;font-size:9px;gap:2px;min-width:60px;white-space:nowrap}
  .nav-btn svg{width:18px;height:18px}
  .main{margin-left:0;padding-bottom:60px}
}
@media(min-width:901px) and (max-width:1200px){
  .col-portfolio{width:400px;min-width:320px}
  .col-market{min-width:280px;max-width:420px}
  .col-chart{min-width:300px}
}
/* Phân Tích: on medium screens (901-1349px) stack analysis below chart */
@media(min-width:901px) and (max-width:1349px){
  .hist-page-right{flex-direction:column}
  .hist-chart-col{border-right:none;border-bottom:1px solid var(--bdr);height:300px;flex-shrink:0}
  .hist-analysis-col{width:100%;min-width:0;flex:1;flex-shrink:1}
}
@media(min-width:1600px){
  :root{font-size:15px}
  .col-portfolio{width:460px}
  .col-market{max-width:560px}
  .fund-nav{font-size:16px}
  .res-nav{font-size:26px}
  .total-val{font-size:28px}
  .card{border-radius:14px}
}
@media(min-width:2000px){
  :root{font-size:16px}
  .col-portfolio{width:390px}
}
</style>
</head>"""

BODY = open(r"P:\NGCG\Vibe Coding\Fund Tracker Pro\telegram-bot\miniapp\web_body.html", encoding='utf-8').read()
JS   = open(r"P:\NGCG\Vibe Coding\Fund Tracker Pro\telegram-bot\miniapp\web_js.js",   encoding='utf-8').read()

# Inline JS so the server doesn't need to serve web_js.js as a static file
BODY = BODY.replace('<script src="web_js.js"></script>', f'<script>\n{JS}\n</script>')

with open(OUT, 'w', encoding='utf-8') as f:
    f.write(HEAD + BODY)
print(f'Done: {len(HEAD)+len(BODY)} chars')
