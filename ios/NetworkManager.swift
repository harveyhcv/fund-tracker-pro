import Foundation

class NetworkManager {
    static let shared = NetworkManager()

    private var todayString: String {
        let fmt = DateFormatter(); fmt.dateFormat = "yyyy-MM-dd"
        return fmt.string(from: Date())
    }

    // MARK: - API: /api/signals
    func fetchSignals(base: String, completion: @escaping (Result<[String: FundSignal], Error>) -> Void) {
        guard let url = URL(string: "\(base)/api/signals") else {
            completion(.failure(URLError(.badURL))); return
        }
        URLSession.shared.dataTask(with: url) { data, _, error in
            if let error = error { completion(.failure(error)); return }
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                completion(.failure(URLError(.cannotParseResponse))); return
            }
            let raw = json["signals"] as? [String: Any] ?? json as? [String: Any] ?? [:]
            var result: [String: FundSignal] = [:]
            for (code, val) in raw {
                guard let s = val as? [String: Any] else { continue }
                var t2: T2Prediction? = nil
                if let t2Raw = s["t2_prediction"] as? [String: Any],
                   let nav = t2Raw["nav"] as? Double, let pct = t2Raw["pct"] as? Double {
                    t2 = T2Prediction(nav: nav, pct: pct, horizon: t2Raw["horizon"] as? Int ?? 2)
                }
                result[code] = FundSignal(
                    code: code,
                    nav: s["nav"] as? Double ?? 0,
                    rsi: s["rsi"] as? Double ?? 50,
                    bbPct: s["bb_pct"] as? Double ?? 50,
                    score: s["score"] as? Int ?? 0,
                    signal: s["signal"] as? String ?? "TRUNG LẬP",
                    chgPct: s["chg_pct"] as? Double ?? 0,
                    chg30: s["chg30"] as? Double,
                    hasPosition: s["has_position"] as? Bool ?? false,
                    t2Prediction: t2,
                    navStale: s["nav_stale"] as? Bool ?? false
                )
            }
            completion(.success(result))
        }.resume()
    }

    // MARK: - API: /api/me (portfolio)
    func fetchPortfolio(base: String, userId: String, completion: @escaping ([PortfolioItem]?) -> Void) {
        guard let url = URL(string: "\(base)/api/me?user_id=\(userId)") else {
            completion(nil); return
        }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let pf = json["portfolio"] as? [String: Any],
                  let items = pf["items"] as? [[String: Any]] else {
                completion(nil); return
            }
            let result: [PortfolioItem] = items.compactMap { h in
                guard let code = h["code"] as? String else { return nil }
                return PortfolioItem(
                    code: code,
                    units: h["units"] as? Double ?? 0,
                    avgCost: h["avg_cost"] as? Double ?? 0,
                    nav: h["nav"] as? Double ?? 0,
                    navSource: h["nav_source"] as? String ?? "",
                    pnlPct: h["pnl_pct"] as? Double ?? 0,
                    pnl: h["pnl"] as? Double ?? 0,
                    value: h["value"] as? Double ?? 0,
                    signal: h["signal"] as? String ?? "TRUNG LẬP",
                    chgPct: h["chg_pct"] as? Double ?? 0
                )
            }
            completion(result)
        }.resume()
    }

    // MARK: - API: /api/nav_history/<code> (chart data)
    func fetchNavHistoryFromAPI(base: String, code: String, completion: @escaping ([NavPoint]?) -> Void) {
        guard let url = URL(string: "\(base)/api/nav_history/\(code)") else {
            completion(nil); return
        }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                completion(nil); return
            }
            let rows = json["history"] as? [[String: Any]] ?? (json["data"] as? [[String: Any]]) ?? []
            let pts = rows.compactMap { r -> NavPoint? in
                guard let d = r["date"] as? String, let v = r["nav"] as? Double else { return nil }
                return NavPoint(navDate: d, nav: v)
            }.sorted { $0.navDate < $1.navDate }
            completion(pts.isEmpty ? nil : pts)
        }.resume()
    }

    // MARK: - Batch fetch from API
    func fetchNavHistories(funds: [FundConfig], completion: @escaping ([String: [NavPoint]]) -> Void) {
        let group = DispatchGroup()
        var results: [String: [NavPoint]] = [:]
        let lock = NSLock()
        for fund in funds {
            group.enter()
            fetchNavHistoryFromAPI(base: "http://localhost:8443", code: fund.code) { pts in
                if let pts = pts { lock.lock(); results[fund.code] = pts; lock.unlock() }
                group.leave()
            }
        }
        group.notify(queue: .global()) { completion(results) }
    }

    // MARK: - Direct fallback (fmarket/TCBS)
    func fetchNavHistoriesDirect(funds: [FundConfig], completion: @escaping ([String: [NavPoint]]) -> Void) {
        let group = DispatchGroup()
        var results: [String: [NavPoint]] = [:]
        let lock = NSLock()
        for fund in funds {
            group.enter()
            fetchNavHistoryDirect(fundCode: fund.code, fundId: fund.fmarketId) { pts in
                if let pts = pts { lock.lock(); results[fund.code] = pts; lock.unlock() }
                group.leave()
            }
        }
        group.notify(queue: .global()) { completion(results) }
    }

    private func fetchNavHistoryDirect(fundCode: String, fundId: Int, completion: @escaping ([NavPoint]?) -> Void) {
        if fundCode.hasPrefix("TC") || fundCode.hasPrefix("VC") {
            fetchFromTCBSPublic(fundCode: fundCode, completion: completion)
        } else {
            fetchFromFmarket(fundId: fundId, completion: completion)
        }
    }

    private func fetchFromFmarket(fundId: Int, completion: @escaping ([NavPoint]?) -> Void) {
        let url = URL(string: "https://api.fmarket.vn/res/product/get-nav-history")!
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 15
        let body: [String: Any] = ["isAllData": 1, "productId": fundId, "fromDate": nil as Any?, "toDate": todayString]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req) { data, _, _ in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let inner = json["data"] as? [String: Any],
                  let arr = inner["navHistories"] as? [[String: Any]] else {
                completion(nil); return
            }
            let pts = arr.compactMap { d -> NavPoint? in
                guard let date = d["navDate"] as? String, let val = d["nav"] as? Double else { return nil }
                return NavPoint(navDate: date, nav: val)
            }.sorted { $0.navDate < $1.navDate }
            completion(pts.isEmpty ? nil : pts)
        }.resume()
    }

    private func fetchFromTCBSPublic(fundCode: String, completion: @escaping ([NavPoint]?) -> Void) {
        guard let url = URL(string: "https://apipubaws.tcbs.com.vn/fund/v1/nav-history/\(fundCode)?page=0&size=3000") else {
            completion(nil); return
        }
        var req = URLRequest(url: url)
        req.timeoutInterval = 15
        URLSession.shared.dataTask(with: req) { data, _, _ in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let arr = json["data"] as? [[String: Any]] else {
                completion(nil); return
            }
            let pts = arr.compactMap { d -> NavPoint? in
                guard let date = d["navDate"] as? String ?? d["date"] as? String,
                      let val = d["nav"] as? Double ?? d["navValue"] as? Double else { return nil }
                return NavPoint(navDate: String(date.prefix(10)), nav: val)
            }.sorted { $0.navDate < $1.navDate }
            completion(pts.isEmpty ? nil : pts)
        }.resume()
    }
}
