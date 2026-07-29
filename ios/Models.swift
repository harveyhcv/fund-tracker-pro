import Foundation
import SwiftUI
import Combine

// MARK: - NAV Data Point
struct NavPoint: Codable, Identifiable {
    var id: String { navDate }
    let navDate: String
    let nav: Double
}

// MARK: - VND Formatters
extension Double {
    func toVND() -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = Locale(identifier: "vi_VN")
        formatter.maximumFractionDigits = 0
        return (formatter.string(from: NSNumber(value: self)) ?? "0") + " đ"
    }

    func toNAV() -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = Locale(identifier: "vi_VN")
        formatter.maximumFractionDigits = 2
        formatter.minimumFractionDigits = 2
        return (formatter.string(from: NSNumber(value: self)) ?? "0,00") + " đ"
    }

    func toPct(decimals: Int = 1) -> String {
        let sign = self >= 0 ? "+" : ""
        return "\(sign)\(String(format: "%.\(decimals)f", self))%"
    }
}

// MARK: - Models
struct Transaction: Identifiable, Codable {
    var id = UUID()
    var fund: String
    var date: Date
    var type: String   // "buy" / "sell"
    var price: Double?
    var nav: Double    // NAV at time of transaction (for avg cost calc)
    var qty: Double?
    var amount: Double
    var fee: Double
    var note: String

    init(id: UUID = UUID(), fund: String, date: Date, type: String, price: Double? = nil, nav: Double = 0, qty: Double? = nil, amount: Double, fee: Double = 0, note: String = "") {
        self.id = id; self.fund = fund; self.date = date; self.type = type
        self.price = price; self.nav = nav; self.qty = qty
        self.amount = amount; self.fee = fee; self.note = note
    }
}

struct UserProfile: Identifiable, Codable {
    var id = UUID()
    var name: String
    var transactions: [Transaction] = []
}

struct FundConfig: Identifiable, Codable {
    var id = UUID()
    var code: String
    var fmarketId: Int
}

// MARK: - Signal from API /api/signals
struct FundSignal: Identifiable {
    var id: String { code }
    let code: String
    let nav: Double
    let rsi: Double
    let bbPct: Double
    let score: Int
    let signal: String
    let chgPct: Double
    let chg30: Double?
    let hasPosition: Bool
    let t2Prediction: T2Prediction?
    let navStale: Bool
}

struct T2Prediction {
    let nav: Double
    let pct: Double
    let horizon: Int
}

// MARK: - Portfolio item from /api/me
struct PortfolioItem: Identifiable {
    var id: String { code }
    let code: String
    let units: Double
    let avgCost: Double
    let nav: Double
    let navSource: String
    let pnlPct: Double
    let pnl: Double
    let value: Double
    let signal: String
    let chgPct: Double
}

// MARK: - App Manager
class FundAppManager: ObservableObject {
    @Published var profiles: [UserProfile] = []
    @Published var activeProfileId: UUID?
    @Published var availableFunds: [FundConfig] = []
    @Published var cachedNav: [String: [NavPoint]] = [:]
    @Published var signals: [String: FundSignal] = [:]
    @Published var apiPortfolio: [PortfolioItem] = []
    @Published var isLoading = false
    @Published var apiAvailable = false
    @Published var lastError: String?

    private let profilesKey   = "fund_tracker_profiles"
    private let activeProfileKey = "fund_tracker_active_profile"
    private let apiBaseKey    = "ftp_api_base"

    var apiBase: String {
        get { UserDefaults.standard.string(forKey: apiBaseKey) ?? "http://localhost:8443" }
        set { UserDefaults.standard.set(newValue, forKey: apiBaseKey) }
    }

    static let defaultFunds: [FundConfig] = [
        FundConfig(code: "TCBF",    fmarketId: 23),
        FundConfig(code: "VCBFTBF", fmarketId: 27),
        FundConfig(code: "SSISCA",  fmarketId: 11),
        FundConfig(code: "VCBFBCF", fmarketId: 32),
        FundConfig(code: "TCFF",    fmarketId: 24)
    ]

    init() {
        self.availableFunds = FundAppManager.defaultFunds
        loadFromStorage()
        if profiles.isEmpty {
            let defaultProfile = UserProfile(name: "Danh Mục Chính")
            profiles = [defaultProfile]
            activeProfileId = defaultProfile.id
        }
    }

    // MARK: - Persistence
    func saveToStorage() {
        if let data = try? JSONEncoder().encode(profiles) {
            UserDefaults.standard.set(data, forKey: profilesKey)
        }
        if let id = activeProfileId {
            UserDefaults.standard.set(id.uuidString, forKey: activeProfileKey)
        }
    }

    private func loadFromStorage() {
        guard let data = UserDefaults.standard.data(forKey: profilesKey),
              let saved = try? JSONDecoder().decode([UserProfile].self, from: data) else { return }
        profiles = saved
        if let idStr = UserDefaults.standard.string(forKey: activeProfileKey),
           let uuid = UUID(uuidString: idStr) {
            activeProfileId = uuid
        } else {
            activeProfileId = saved.first?.id
        }
    }

    // MARK: - Summary (local fallback)
    func getSummary() -> (totalInv: Double, currentVal: Double) {
        if !apiPortfolio.isEmpty {
            let val  = apiPortfolio.reduce(0.0) { $0 + $1.value }
            let cost = apiPortfolio.reduce(0.0) { $0 + $1.avgCost * $1.units }
            return (cost, val)
        }
        guard let profile = profiles.first(where: { $0.id == activeProfileId }) else { return (0, 0) }
        var tInv = 0.0; var tVal = 0.0
        for fund in availableFunds {
            let nav = cachedNav[fund.code]?.last?.nav ?? 0
            let perf = MathEngine.calculateFundPerformance(fundCode: fund.code, transactions: profile.transactions, currentNav: nav)
            tInv += perf.invested; tVal += perf.currentVal
        }
        return (tInv, tVal)
    }

    // MARK: - Indicators (local compute)
    func getRSI(for code: String) -> Double? {
        guard let history = cachedNav[code] else { return nil }
        return MathEngine.calculateRSI(navHistory: history)
    }

    func getMACD(for code: String) -> (macd: Double, signal: Double, histogram: Double)? {
        guard let history = cachedNav[code] else { return nil }
        return MathEngine.calculateMACD(navHistory: history)
    }

    func getBB(for code: String) -> (upper: Double, middle: Double, lower: Double, percent: Double)? {
        guard let history = cachedNav[code] else { return nil }
        return MathEngine.calculateBollingerBands(navHistory: history)
    }

    func getT2(for code: String) -> T2Prediction? {
        if let s = signals[code], let t2 = s.t2Prediction { return t2 }
        guard let history = cachedNav[code], let r = MathEngine.ensemblePredict(navHistory: history, horizon: 2) else { return nil }
        return T2Prediction(nav: r.nav, pct: r.pct, horizon: 2)
    }

    // MARK: - Data Fetch (API first, then direct fallback)
    func fetchData(userId: String = "1") {
        self.isLoading = true
        self.lastError = nil
        NetworkManager.shared.fetchSignals(base: apiBase) { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .success(let sigs):
                DispatchQueue.main.async {
                    self.signals = sigs
                    self.apiAvailable = true
                }
            case .failure:
                self.fetchDirect()
            }
        }
        NetworkManager.shared.fetchPortfolio(base: apiBase, userId: userId) { [weak self] items in
            guard let self = self else { return }
            if let items = items {
                DispatchQueue.main.async { self.apiPortfolio = items }
            }
        }
        NetworkManager.shared.fetchNavHistories(funds: availableFunds) { [weak self] results in
            guard let self = self else { return }
            DispatchQueue.main.async {
                for (code, pts) in results { self.cachedNav[code] = pts }
                self.isLoading = false
            }
        }
    }

    private func fetchDirect() {
        NetworkManager.shared.fetchNavHistoriesDirect(funds: availableFunds) { [weak self] results in
            guard let self = self else { return }
            DispatchQueue.main.async {
                for (code, pts) in results { self.cachedNav[code] = pts }
                self.isLoading = false
            }
        }
    }
}
