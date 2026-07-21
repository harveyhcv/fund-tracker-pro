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
:root{--bg:#060b14;--bg2:#0c1626;--bg3:#111e30;--c0:#00e5ff;--buy:#4ade80;--sell:#f87171;--hold:#facc15;--txt:#e2e8f0;--txt2:#94a3b8;--bdr:#1e3050;--mono:'IBM Plex Mono',monospace;--sans:'DM Sans',sans-serif;}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{min-height:100%}
body{background:var(--bg);color:var(--txt);font-family:var(--sans);font-size:14px;overflow-x:hidden}
#toast{position:fixed;top:16px;left:50%;transform:translateX(-50%);background:#1a2e4a;border:1px solid var(--c0);color:var(--txt);padding:10px 18px;border-radius:8px;font-size:13px;z-index:999;display:none;max-width:90vw;text-align:center}
#tier-bar{display:none;align-items:center;justify-content:space-between;padding:6px 14px 5px;background:var(--bg2);border-bottom:1px solid var(--bdr);font-size:12px;position:sticky;top:0;z-index:50}
#tier-bar.visible{display:flex}
.tier-name{color:var(--txt);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:45vw}
.tier-chip{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:20px;font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.03em;white-space:nowrap}
.tier-chip.free{background:#1a1a2e;color:#8888aa;border:1px solid #333355}
.tier-chip.pro{background:#001a2e;color:var(--c0);border:1px solid var(--c0)}
.tier-chip.admin{background:#1a0a2e;color:#c084fc;border:1px solid #9333ea}
.tier-exp{font-size:10px;color:var(--txt2);margin-left:4px}
.tier-upgrade-hint{font-size:10px;color:var(--txt2);cursor:pointer;text-decoration:underline;text-underline-offset:2px}
#nav{position:fixed;bottom:0;left:0;right:0;background:var(--bg2);border-top:1px solid var(--bdr);display:flex;z-index:100;padding-bottom:env(safe-area-inset-bottom)}
.nav-btn{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;padding:10px 4px 8px;background:none;border:none;color:var(--txt2);font-size:10px;font-family:var(--sans);cursor:pointer;transition:color .2s}
.nav-btn.active{color:var(--c0)}
.nav-btn svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
#app{padding:12px 12px 72px;max-width:720px;margin:0 auto}
.page{display:none}.page.active{display:block}
.hdr{font-family:var(--mono);font-size:12px;color:var(--c0);letter-spacing:.08em;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center}
.hdr-sub{color:var(--txt2);font-size:11px}
.card{background:var(--bg2);border:1px solid var(--bdr);border-radius:10px;padding:12px;margin-bottom:8px}
.card-title{font-family:var(--mono);font-size:11px;color:var(--txt2);margin-bottom:8px;text-transform:uppercase;letter-spacing:.06em}
.badge{display:inline-block;padding:2px 7px;border-radius:20px;font-size:11px;font-family:var(--mono);font-weight:600}
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
.fund-row{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--bdr);gap:8px;cursor:pointer;transition:background .15s;border-radius:6px;padding:10px 4px}
.fund-row:last-child{border:none}
.fund-row:active{background:var(--bg3)}
.fund-code{font-family:var(--mono);font-weight:700;font-size:12px;flex:0 0 auto;background:var(--bg3);border:1px solid var(--bdr);border-radius:5px;padding:2px 6px}
.fund-info{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px}
.fund-top{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}
.fund-nav{font-family:var(--mono);font-size:14px;font-weight:600;color:var(--txt)}
.fund-sub{font-size:11px;color:var(--txt2);display:flex;align-items:center;gap:6px}
.fund-right{text-align:right;flex:0 0 auto;display:flex;flex-direction:column;gap:4px}
.sig-row{display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:center;padding:10px 4px;border-bottom:1px solid var(--bdr);cursor:pointer;border-radius:6px;transition:background .15s}
.sig-row:last-child{border:none}
.sig-row:active{background:var(--bg3)}
.sig-code{font-family:var(--mono);font-size:13px;font-weight:600}
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
.school-title{font-size:12px;font-weight:700;flex:1}
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
</style>
</head>"""

BODY = open(r"P:\NGCG\Vibe Coding\Fund Tracker Pro\telegram-bot\miniapp\web_body.html", encoding='utf-8').read()

with open(OUT, 'w', encoding='utf-8') as f:
    f.write(HEAD + BODY)
print(f'Done: {len(HEAD)+len(BODY)} chars')
