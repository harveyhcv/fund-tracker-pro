"""Patch miniapp_server.py: improve _api_admin_fetch_nav
- Support skip_tcbs param
- Quick token pre-validation before background start
- Fix: fetch fmarket AND tcbs independently (not if/else)
- Better error reporting
"""
import os
ROOT = os.path.join(os.path.dirname(__file__), '..')
SRV = os.path.join(ROOT, 'telegram-bot', 'miniapp_server.py')
c = open(SRV, encoding='utf-8').read()

OLD = '''    def _api_admin_fetch_nav(self, data: dict):
        """POST /api/admin/fetch-nav — trigger fresh NAV fetch for all funds (fmarket + TCBS)."""
        if not _BOT_IMPORTED:
            _json(self, {"error": "bot module not available"}, 503)
            return
        cfg = _load_cfg()
        import bot as _bot
        import threading

        def _do_fetch():
            try:
                token = cfg.get("tcbs_token", "")
                db_url = os.environ.get("DATABASE_URL", cfg.get("database_url", ""))
                funds_cfg = cfg.get("funds", {})
                results = {}
                for code, fc in funds_cfg.items():
                    pts = []
                    if fc.get("fmarket_id"):
                        try:
                            pts = _bot.fetch_fmarket(fc["fmarket_id"])
                        except Exception as ex:
                            log.warning(f"fmarket {code}: {ex}")
                    if not pts and fc.get("tcbs") and token:
                        try:
                            pts = _bot.fetch_tcbs(code, token)
                        except Exception as ex:
                            log.warning(f"tcbs {code}: {ex}")
                    if pts and db_url:
                        try:
                            saved = _bot.save_nav_to_db(db_url, code, pts)
                            results[code] = saved
                            log.info(f"[fetch-nav] {code}: +{saved} records")
                        except Exception as ex:
                            log.warning(f"save {code}: {ex}")
                log.info(f"[fetch-nav] done: {results}")
            except Exception as ex:
                log.error(f"[fetch-nav] error: {ex}")

        threading.Thread(target=_do_fetch, daemon=True, name="admin-fetch-nav").start()
        _json(self, {"ok": True, "msg": "NAV fetch started for all funds in background"})'''

NEW = '''    def _api_admin_fetch_nav(self, data: dict):
        """POST /api/admin/fetch-nav — trigger fresh NAV fetch for all funds.
        Params: skip_tcbs (bool) — bỏ qua các quỹ TCBS nếu True
        Returns token_expired error nếu token không hợp lệ (sync check trước khi background).
        """
        if not _BOT_IMPORTED:
            _json(self, {"error": "bot module not available"}, 503)
            return
        cfg = _load_cfg()
        skip_tcbs = bool(data.get("skip_tcbs", False))
        import bot as _bot
        import threading

        # ── Quick token validation (sync, không fetch) ──────────────────────
        token = cfg.get("tcbs_token", "")
        if not skip_tcbs and token:
            try:
                import requests as _req
                hdr = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
                probe = _req.get(
                    "https://apipubaws.tcbs.com.vn/stock-insight/v1/fund/top-funds",
                    headers=hdr, timeout=6
                )
                if probe.status_code in (401, 403):
                    log.warning("[fetch-nav] TCBS token expired/invalid → returning token_expired")
                    _json(self, {"ok": False, "error": "token_expired",
                                 "tcbs_error": f"HTTP {probe.status_code}"})
                    return
            except Exception as ex:
                log.warning(f"[fetch-nav] token probe lỗi (bỏ qua): {ex}")

        db_url = os.environ.get("DATABASE_URL", cfg.get("database_url", ""))
        funds_cfg = cfg.get("funds", {})

        def _do_fetch():
            results, errors = {}, {}
            try:
                for code, fc in funds_cfg.items():
                    pts_all = []
                    # 1. fmarket (luôn thử nếu có)
                    if fc.get("fmarket_id"):
                        try:
                            fpts = _bot.fetch_fmarket(fc["fmarket_id"])
                            if fpts:
                                pts_all.extend(fpts)
                                log.info(f"[fetch-nav] fmarket {code}: {len(fpts)} pts")
                        except Exception as ex:
                            errors[f"fmarket_{code}"] = str(ex)
                            log.warning(f"fmarket {code}: {ex}")
                    # 2. TCBS (thử thêm nếu không skip và có config)
                    if not skip_tcbs and fc.get("tcbs") and token:
                        try:
                            tpts = _bot.fetch_tcbs(code, token)
                            if tpts:
                                # Merge: dùng TCBS data cho ngày trùng (source of truth)
                                existing_dates = {p["date"] for p in pts_all}
                                new_pts = [p for p in tpts if p["date"] not in existing_dates]
                                pts_all.extend(new_pts)
                                log.info(f"[fetch-nav] tcbs {code}: {len(tpts)} pts (+{len(new_pts)} new)")
                        except Exception as ex:
                            errors[f"tcbs_{code}"] = str(ex)
                            log.warning(f"tcbs {code}: {ex}")
                    # 3. Save merged points
                    if pts_all and db_url:
                        try:
                            saved = _bot.save_nav_to_db(db_url, code, pts_all)
                            results[code] = saved
                            log.info(f"[fetch-nav] saved {code}: +{saved}")
                        except Exception as ex:
                            errors[f"save_{code}"] = str(ex)
                            log.warning(f"save {code}: {ex}")
                log.info(f"[fetch-nav] done — results: {results}, errors: {errors}")
            except Exception as ex:
                log.error(f"[fetch-nav] fatal: {ex}")

        threading.Thread(target=_do_fetch, daemon=True, name="admin-fetch-nav").start()
        _json(self, {"ok": True, "msg": "NAV fetch started",
                     "skip_tcbs": skip_tcbs, "funds": list(funds_cfg.keys())})'''

if OLD in c:
    c = c.replace(OLD, NEW, 1)
    open(SRV, 'w', encoding='utf-8').write(c)
    print('OK: _api_admin_fetch_nav updated')
else:
    print('FAIL: function not found exactly')
    # Try to find partial
    idx = c.find('def _api_admin_fetch_nav')
    print(f'  Found at index: {idx}')
    if idx > 0:
        print(c[idx:idx+200])
