import Foundation

class MathEngine {

    // MARK: - Fund Performance
    static func calculateFundPerformance(fundCode: String, transactions: [Transaction], currentNav: Double) -> (invested: Double, currentVal: Double, units: Double, avgCost: Double) {
        let fundTxs = transactions.filter { $0.fund == fundCode }
        var inv = 0.0; var qty = 0.0; var cost = 0.0
        for tx in fundTxs {
            if tx.type == "buy" {
                inv += tx.amount + tx.fee
                let units = tx.qty ?? (tx.nav > 0 ? tx.amount / tx.nav : 0)
                qty += units
                cost += tx.amount
            } else {
                let units = tx.qty ?? 0
                qty -= units
                if qty < 0 { qty = 0 }
            }
        }
        let avgCost = qty > 0 ? cost / qty : 0
        return (inv, qty * currentNav, qty, avgCost)
    }

    // MARK: - RSI (14-day)
    static func calculateRSI(navHistory: [NavPoint], period: Int = 14) -> Double? {
        guard navHistory.count > period else { return nil }
        let navs = navHistory.suffix(period + 1).map { $0.nav }
        var gains = 0.0; var losses = 0.0
        for i in 1..<navs.count {
            let diff = navs[i] - navs[i-1]
            if diff >= 0 { gains += diff } else { losses -= diff }
        }
        if losses == 0 { return 100 }
        let rs = gains / losses
        return 100 - (100 / (1 + rs))
    }

    // MARK: - EMA (helper)
    static func ema(_ values: [Double], period: Int) -> [Double] {
        guard values.count >= period else { return [] }
        let k = 2.0 / Double(period + 1)
        var result = [values.prefix(period).reduce(0, +) / Double(period)]
        for i in period..<values.count {
            result.append(values[i] * k + result.last! * (1 - k))
        }
        return result
    }

    // MARK: - MACD (12, 26, 9)
    static func calculateMACD(navHistory: [NavPoint]) -> (macd: Double, signal: Double, histogram: Double)? {
        let navs = navHistory.map { $0.nav }
        guard navs.count >= 35 else { return nil }

        let ema12 = ema(navs, period: 12)
        let ema26 = ema(navs, period: 26)
        let alignCount = min(ema12.count, ema26.count)
        guard alignCount > 0 else { return nil }

        var macdLine: [Double] = []
        for i in 0..<alignCount {
            macdLine.append(ema12[ema12.count - alignCount + i] - ema26[ema26.count - alignCount + i])
        }

        let signalLine = ema(macdLine, period: 9)
        guard let macdVal = macdLine.last, let signalVal = signalLine.last else { return nil }
        return (macdVal, signalVal, macdVal - signalVal)
    }

    // MARK: - Bollinger Bands (20-day, 2σ)
    static func calculateBollingerBands(navHistory: [NavPoint], period: Int = 20) -> (upper: Double, middle: Double, lower: Double, percent: Double)? {
        guard navHistory.count >= period else { return nil }
        let navs = navHistory.suffix(period).map { $0.nav }
        let mean = navs.reduce(0, +) / Double(period)
        let variance = navs.map { pow($0 - mean, 2) }.reduce(0, +) / Double(period)
        let std = sqrt(variance)
        guard std > 0 else { return nil }
        let upper = mean + 2 * std
        let lower = mean - 2 * std
        let current = navs.last!
        let percent = (current - lower) / (upper - lower)
        return (upper, mean, lower, percent)
    }

    // MARK: - Composite Signal Score (–6…+6)
    static func compositeScore(rsi: Double?, macd: (macd: Double, signal: Double, histogram: Double)?, bb: (upper: Double, middle: Double, lower: Double, percent: Double)?) -> Int {
        var score = 0
        if let rsi = rsi {
            if rsi < 30      { score += 2 }
            else if rsi < 40 { score += 1 }
            else if rsi > 70 { score -= 2 }
            else if rsi > 60 { score -= 1 }
        }
        if let macd = macd {
            score += macd.histogram > 0 ? 1 : -1
            score += macd.macd > macd.signal ? 1 : -1
        }
        if let bb = bb {
            if bb.percent < 0.2       { score += 2 }
            else if bb.percent < 0.35 { score += 1 }
            else if bb.percent > 0.8  { score -= 2 }
            else if bb.percent > 0.65 { score -= 1 }
        }
        return score
    }

    static func compositeSignal(rsi: Double?, macd: (macd: Double, signal: Double, histogram: Double)?, bb: (upper: Double, middle: Double, lower: Double, percent: Double)?) -> String {
        let score = compositeScore(rsi: rsi, macd: macd, bb: bb)
        switch score {
        case 4...:        return "MUA MẠNH"
        case 2...3:       return "MUA"
        case (-1)...1:    return "TRUNG LẬP"
        case (-3)...(-2): return "BÁN"
        default:          return "BÁN MẠNH"
        }
    }

    // MARK: - Ensemble T+N Prediction (LinReg 50% + Mom5 30% + Mom3 20%)
    static func ensemblePredict(navHistory: [NavPoint], horizon: Int = 2) -> (nav: Double, pct: Double)? {
        guard navHistory.count >= 10 else { return nil }
        let tail = Array(navHistory.suffix(30)).map { $0.nav }
        let n = tail.count
        let xs = (0..<n).map { Double($0) }
        let mx = xs.reduce(0, +) / Double(n)
        let my = tail.reduce(0, +) / Double(n)
        let cov = zip(xs, tail).map { ($0 - mx) * ($1 - my) }.reduce(0, +)
        let vx  = xs.map { pow($0 - mx, 2) }.reduce(0, +)
        let slope = vx > 0 ? cov / vx : 0
        let regNav = my + slope * (Double(n - 1 + horizon) - mx)

        let mom5 = n > 5 ? tail.last! + (tail.last! - tail[n-6]) / 5.0 * Double(horizon) : regNav
        let mom3 = n > 3 ? tail.last! + (tail.last! - tail[n-4]) / 3.0 * Double(horizon) : regNav

        let pred = round(regNav * 0.5 + mom5 * 0.3 + mom3 * 0.2)
        let curr = tail.last!
        let pct  = curr > 0 ? (pred - curr) / curr * 100 : 0
        return (pred, pct)
    }

    // MARK: - Annualized Volatility
    static func annualizedVolatility(navHistory: [NavPoint], tradingDays: Int = 252) -> Double? {
        guard navHistory.count > 20 else { return nil }
        let navs = navHistory.suffix(252).map { $0.nav }
        var returns: [Double] = []
        for i in 1..<navs.count {
            if navs[i-1] > 0 { returns.append((navs[i] - navs[i-1]) / navs[i-1]) }
        }
        guard returns.count > 1 else { return nil }
        let mean = returns.reduce(0, +) / Double(returns.count)
        let variance = returns.map { pow($0 - mean, 2) }.reduce(0, +) / Double(returns.count - 1)
        return sqrt(variance * Double(tradingDays)) * 100
    }

    // MARK: - Max Drawdown
    static func maxDrawdown(navHistory: [NavPoint]) -> Double? {
        guard navHistory.count > 10 else { return nil }
        let navs = navHistory.map { $0.nav }
        var peak = navs[0]; var maxDD = 0.0
        for nav in navs {
            if nav > peak { peak = nav }
            let dd = peak > 0 ? (peak - nav) / peak * 100 : 0
            if dd > maxDD { maxDD = dd }
        }
        return maxDD
    }

    // MARK: - Sharpe Ratio (risk-free 3.5% annual)
    static func sharpeRatio(navHistory: [NavPoint], riskFree: Double = 3.5, tradingDays: Int = 252) -> Double? {
        guard let vol = annualizedVolatility(navHistory: navHistory), vol > 0 else { return nil }
        guard navHistory.count > 252 else { return nil }
        let year = Array(navHistory.suffix(252))
        guard let first = year.first?.nav, let last = year.last?.nav, first > 0 else { return nil }
        let annReturn = (last - first) / first * 100
        return (annReturn - riskFree) / vol
    }

    // MARK: - 30-day Return
    static func return30d(navHistory: [NavPoint]) -> Double? {
        guard navHistory.count > 30, let last = navHistory.last?.nav else { return nil }
        let base = navHistory[navHistory.count - 31].nav
        guard base > 0 else { return nil }
        return (last - base) / base * 100
    }
}
