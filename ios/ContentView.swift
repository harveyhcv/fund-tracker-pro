import SwiftUI
import Charts

// MARK: - Root (TabView)
struct ContentView: View {
    @StateObject var manager = FundAppManager()
    @State private var selectedTab = 0
    @State private var selectedFund: String? = nil

    var body: some View {
        TabView(selection: $selectedTab) {
            DashboardView(manager: manager, selectedFund: $selectedFund, selectedTab: $selectedTab)
                .tabItem { Label("Trang Chủ", systemImage: "house.fill") }
                .tag(0)
            MarketView(manager: manager, selectedFund: $selectedFund, selectedTab: $selectedTab)
                .tabItem { Label("Thị Trường", systemImage: "chart.bar.fill") }
                .tag(1)
            AnalysisView(manager: manager, fundCode: selectedFund)
                .tabItem { Label("Phân Tích", systemImage: "waveform.path.ecg") }
                .tag(2)
            SettingsView(manager: manager)
                .tabItem { Label("Cài Đặt", systemImage: "gearshape.fill") }
                .tag(3)
        }
        .onAppear { manager.fetchData() }
        .sheet(item: $selectedFund.asFundSheet) { wrapper in
            FundDetailSheet(manager: manager, code: wrapper.code)
        }
    }
}

// Helper to bridge String? → Identifiable for .sheet
private struct FundWrapper: Identifiable { let code: String; var id: String { code } }
private extension Binding where Value == String? {
    var asFundSheet: Binding<FundWrapper?> {
        Binding<FundWrapper?>(
            get: { wrappedValue.map { FundWrapper(code: $0) } },
            set: { wrappedValue = $0?.code }
        )
    }
}

// MARK: - Dashboard (Portfolio)
struct DashboardView: View {
    @ObservedObject var manager: FundAppManager
    @Binding var selectedFund: String?
    @Binding var selectedTab: Int

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    PortfolioBannerCard(manager: manager)
                    AllocationBar(manager: manager)
                    if manager.apiPortfolio.isEmpty && manager.isLoading {
                        ProgressView("Đang tải danh mục...").padding(32)
                    } else if manager.apiPortfolio.isEmpty {
                        EmptyPortfolioCard()
                    } else {
                        ForEach(manager.apiPortfolio) { item in
                            PortfolioItemRow(item: item, t2: manager.signals[item.code]?.t2Prediction)
                                .onTapGesture { selectedFund = item.code; selectedTab = 2 }
                        }
                    }
                }
                .padding()
            }
            .navigationTitle("Danh Mục")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { manager.fetchData() } label: {
                        Image(systemName: manager.isLoading ? "arrow.clockwise.circle" : "arrow.clockwise")
                    }
                    .disabled(manager.isLoading)
                }
            }
        }
    }
}

struct PortfolioBannerCard: View {
    @ObservedObject var manager: FundAppManager

    var body: some View {
        let summary = manager.getSummary()
        let pnl = summary.currentVal - summary.totalInv
        let pnlPct = summary.totalInv > 0 ? pnl / summary.totalInv * 100 : 0

        VStack(spacing: 6) {
            Text("TỔNG TÀI SẢN").font(.caption).foregroundStyle(.secondary)
            Text(summary.currentVal.toVND()).font(.title.bold())
            HStack(spacing: 6) {
                Image(systemName: pnl >= 0 ? "arrow.up.right" : "arrow.down.right")
                Text(pnlPct.toPct())
                Text("(\(pnl >= 0 ? "+" : "")\(pnl.toVND()))").foregroundStyle(.secondary)
            }
            .font(.subheadline.bold())
            .foregroundStyle(pnl >= 0 ? Color.green : Color.red)
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 14))
    }
}

struct AllocationBar: View {
    @ObservedObject var manager: FundAppManager

    var body: some View {
        let total = manager.apiPortfolio.reduce(0.0) { $0 + $1.value }
        guard total > 0 else { return AnyView(EmptyView()) }
        return AnyView(
            VStack(alignment: .leading, spacing: 6) {
                Text("Phân Bổ Danh Mục").font(.caption).foregroundStyle(.secondary)
                GeometryReader { geo in
                    HStack(spacing: 2) {
                        ForEach(manager.apiPortfolio, id: \.code) { item in
                            let pct = item.value / total
                            RoundedRectangle(cornerRadius: 3)
                                .fill(colorForCode(item.code))
                                .frame(width: geo.size.width * CGFloat(pct))
                        }
                    }
                }
                .frame(height: 10)
                .clipShape(RoundedRectangle(cornerRadius: 5))
                FlowLayout(spacing: 6) {
                    ForEach(manager.apiPortfolio, id: \.code) { item in
                        let pct = item.value / total * 100
                        HStack(spacing: 3) {
                            Circle().fill(colorForCode(item.code)).frame(width: 7, height: 7)
                            Text("\(item.code) \(String(format: "%.0f", pct))%").font(.caption2)
                        }
                    }
                }
            }
            .padding()
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
        )
    }

    func colorForCode(_ code: String) -> Color {
        let palette: [Color] = [.cyan, .mint, .blue, .indigo, .purple, .teal]
        let idx = abs(code.hashValue) % palette.count
        return palette[idx]
    }
}

struct PortfolioItemRow: View {
    let item: PortfolioItem
    let t2: T2Prediction?

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(item.code).font(.subheadline.bold()).foregroundStyle(.cyan)
                    SignalBadge(signal: item.signal)
                }
                Text("\(String(format: "%.0f", item.units)) CCQ · Giá vốn \(item.avgCost.toNAV())")
                    .font(.caption).foregroundStyle(.secondary)
                if let t2 = t2 {
                    HStack(spacing: 3) {
                        Image(systemName: t2.pct >= 0 ? "arrow.up.forward" : "arrow.down.forward")
                            .imageScale(.small)
                        Text("T+2 \(t2.pct.toPct(decimals: 2))")
                            .font(.caption2.monospaced())
                    }
                    .foregroundStyle(t2.pct >= 0 ? .green : .red)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                Text(item.nav.toNAV()).font(.subheadline.bold())
                Text(item.pnlPct.toPct()).font(.caption.bold())
                    .foregroundStyle(item.pnlPct >= 0 ? .green : .red)
                Text(item.value.toVND()).font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
        .contentShape(RoundedRectangle(cornerRadius: 12))
    }
}

struct EmptyPortfolioCard: View {
    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "tray").font(.largeTitle).foregroundStyle(.secondary)
            Text("Chưa có danh mục").font(.headline).foregroundStyle(.secondary)
            Text("Kết nối server để xem danh mục từ API").font(.caption).foregroundStyle(.tertiary)
        }
        .frame(maxWidth: .infinity).padding(40)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 14))
    }
}

// MARK: - Market View (Signal Board)
struct MarketView: View {
    @ObservedObject var manager: FundAppManager
    @Binding var selectedFund: String?
    @Binding var selectedTab: Int
    @State private var searchText = ""
    @State private var filter: SignalFilter = .all

    enum SignalFilter: String, CaseIterable {
        case all = "Tất Cả"
        case buy = "Mua"
        case hold = "Hold"
        case sell = "Bán"
        case held = "Đang Nắm"
    }

    var sortedSignals: [FundSignal] {
        manager.signals.values
            .filter { s in
                let matchesSearch = searchText.isEmpty || s.code.localizedCaseInsensitiveContains(searchText)
                let matchesFilter: Bool
                switch filter {
                case .all:  matchesFilter = true
                case .buy:  matchesFilter = s.signal.contains("MUA")
                case .sell: matchesFilter = s.signal.contains("BÁN") || s.signal.contains("BAN")
                case .hold: matchesFilter = s.signal.contains("TRUNG") || s.signal == "HOLD"
                case .held: matchesFilter = s.hasPosition
                }
                return matchesSearch && matchesFilter
            }
            .sorted {
                if $0.hasPosition != $1.hasPosition { return $0.hasPosition }
                return $0.score > $1.score
            }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                SearchBar(text: $searchText)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(SignalFilter.allCases, id: \.self) { f in
                            FilterChip(title: f.rawValue, isSelected: filter == f) {
                                filter = f
                            }
                        }
                    }
                    .padding(.horizontal).padding(.vertical, 8)
                }
                if manager.isLoading && manager.signals.isEmpty {
                    Spacer()
                    ProgressView("Đang tải tín hiệu...").padding()
                    Spacer()
                } else {
                    List(sortedSignals) { signal in
                        SignalRow(signal: signal)
                            .listRowInsets(EdgeInsets(top: 4, leading: 12, bottom: 4, trailing: 12))
                            .listRowBackground(Color.clear)
                            .onTapGesture { selectedFund = signal.code; selectedTab = 2 }
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle("Thị Trường")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { manager.fetchData() } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .disabled(manager.isLoading)
                }
            }
        }
    }
}

struct SignalRow: View {
    let signal: FundSignal

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(signal.code).font(.subheadline.bold()).foregroundStyle(.cyan)
                    if signal.hasPosition {
                        Text("●").font(.caption2).foregroundStyle(.cyan)
                    }
                    if signal.navStale {
                        Image(systemName: "exclamationmark.triangle.fill").imageScale(.small).foregroundStyle(.yellow)
                    }
                }
                Text(signal.nav.toNAV()).font(.caption).foregroundStyle(.secondary)
                if let t2 = signal.t2Prediction {
                    Text("T+2 \(t2.pct.toPct(decimals: 2))")
                        .font(.caption2.monospaced())
                        .foregroundStyle(t2.pct >= 0 ? .green : .red)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 6) {
                SignalBadge(signal: signal.signal)
                ScoreBar(score: signal.score)
                HStack(spacing: 8) {
                    MeterBar(label: "RSI", value: signal.rsi / 100, color: signal.rsi < 35 ? .green : signal.rsi > 65 ? .red : .blue)
                    MeterBar(label: "BB", value: signal.bbPct / 100, color: signal.bbPct < 20 ? .green : signal.bbPct > 80 ? .red : .blue)
                }
            }
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
    }
}

struct MeterBar: View {
    let label: String
    let value: Double
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.system(size: 8)).foregroundStyle(.secondary)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2).fill(Color.white.opacity(0.1)).frame(height: 5)
                    RoundedRectangle(cornerRadius: 2).fill(color).frame(width: geo.size.width * CGFloat(max(0, min(1, value))), height: 5)
                }
            }
            .frame(width: 44, height: 5)
            Text(String(format: "%.0f", value * 100)).font(.system(size: 9).monospaced()).foregroundStyle(.secondary)
        }
    }
}

struct ScoreBar: View {
    let score: Int

    var body: some View {
        HStack(spacing: 2) {
            Text("SCR").font(.system(size: 8)).foregroundStyle(.secondary)
            Text(score >= 0 ? "+\(score)" : "\(score)")
                .font(.caption2.bold().monospaced())
                .foregroundStyle(score >= 3 ? .green : score <= -3 ? .red : .secondary)
        }
    }
}

// MARK: - Analysis View
struct AnalysisView: View {
    @ObservedObject var manager: FundAppManager
    var fundCode: String?

    var body: some View {
        NavigationStack {
            if let code = fundCode, let history = manager.cachedNav[code], !history.isEmpty {
                FundAnalysisView(manager: manager, code: code, history: history)
            } else {
                VStack(spacing: 16) {
                    Image(systemName: "chart.xyaxis.line").font(.largeTitle).foregroundStyle(.secondary)
                    Text(fundCode == nil ? "Chọn quỹ từ tab Thị Trường" : "Đang tải dữ liệu \(fundCode ?? "")...")
                        .foregroundStyle(.secondary)
                    if manager.isLoading { ProgressView() }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .navigationTitle("Phân Tích")
            }
        }
    }
}

struct FundAnalysisView: View {
    @ObservedObject var manager: FundAppManager
    let code: String
    let history: [NavPoint]
    @State private var range: ChartRange = .oneYear

    enum ChartRange: String, CaseIterable {
        case oneMonth = "1T"; case threeMonths = "3T"; case sixMonths = "6T"
        case oneYear = "1N"; case all = "All"
    }

    var displayedHistory: [NavPoint] {
        guard let cutoff = cutoffDate else { return history }
        return history.filter { $0.navDate >= cutoff }
    }

    var cutoffDate: String? {
        let cal = Calendar.current; let now = Date()
        let fmt = DateFormatter(); fmt.dateFormat = "yyyy-MM-dd"
        switch range {
        case .oneMonth:    return fmt.string(from: cal.date(byAdding: .month, value: -1, to: now)!)
        case .threeMonths: return fmt.string(from: cal.date(byAdding: .month, value: -3, to: now)!)
        case .sixMonths:   return fmt.string(from: cal.date(byAdding: .month, value: -6, to: now)!)
        case .oneYear:     return fmt.string(from: cal.date(byAdding: .year,  value: -1, to: now)!)
        case .all:         return nil
        }
    }

    var rsi:  Double? { MathEngine.calculateRSI(navHistory: history) }
    var macd: (macd: Double, signal: Double, histogram: Double)? { MathEngine.calculateMACD(navHistory: history) }
    var bb:   (upper: Double, middle: Double, lower: Double, percent: Double)? { MathEngine.calculateBollingerBands(navHistory: history) }
    var t2:   (nav: Double, pct: Double)? { MathEngine.ensemblePredict(navHistory: history, horizon: 2) }
    var score: Int { MathEngine.compositeScore(rsi: rsi, macd: macd, bb: bb) }
    var signal: String { MathEngine.compositeSignal(rsi: rsi, macd: macd, bb: bb) }
    var vol:  Double? { MathEngine.annualizedVolatility(navHistory: history) }
    var dd:   Double? { MathEngine.maxDrawdown(navHistory: history) }
    var sharpe: Double? { MathEngine.sharpeRatio(navHistory: history) }
    var ret30: Double? { MathEngine.return30d(navHistory: history) }

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                // Fund header
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(code).font(.title2.bold()).foregroundStyle(.cyan)
                        Text(history.last?.navDate ?? "").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 4) {
                        Text((history.last?.nav ?? 0).toNAV()).font(.title3.bold())
                        SignalBadge(signal: signal)
                    }
                }

                // NAV Chart
                if #available(iOS 16, *) {
                    NAVChartCard(history: displayedHistory, range: $range)
                }

                // T+2 Prediction
                if let t2 = t2 {
                    T2PredictionCard(t2: t2, currentNav: history.last?.nav ?? 0)
                }

                // Technical metrics
                TechMetricsCard(rsi: rsi, macd: macd, bb: bb, score: score)

                // Risk & Performance metrics
                RiskMetricsCard(vol: vol, dd: dd, sharpe: sharpe, ret30: ret30)
            }
            .padding()
        }
        .navigationTitle(code)
        .navigationBarTitleDisplayMode(.inline)
    }
}

@available(iOS 16, *)
struct NAVChartCard: View {
    let history: [NavPoint]
    @Binding var range: FundAnalysisView.ChartRange

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Biểu đồ NAV").font(.caption).foregroundStyle(.secondary)
            Chart {
                ForEach(history, id: \.navDate) { pt in
                    LineMark(x: .value("Ngày", pt.navDate), y: .value("NAV", pt.nav))
                        .foregroundStyle(.cyan)
                        .lineStyle(StrokeStyle(lineWidth: 1.5))
                }
            }
            .chartXAxis(.hidden)
            .frame(height: 160)
            .chartYScale(domain: .automatic)

            HStack(spacing: 6) {
                ForEach(FundAnalysisView.ChartRange.allCases, id: \.self) { r in
                    FilterChip(title: r.rawValue, isSelected: range == r) { range = r }
                }
            }
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}

struct T2PredictionCard: View {
    let t2: (nav: Double, pct: Double)
    let currentNav: Double

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("DỰ BÁO T+2").font(.caption.bold()).foregroundStyle(.secondary)
                Text("Ensemble: LinReg 50% + Mom5 30% + Mom3 20%")
                    .font(.caption2).foregroundStyle(.tertiary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                Text(t2.nav.toNAV()).font(.subheadline.bold())
                Text(t2.pct.toPct(decimals: 2)).font(.caption.bold().monospaced())
                    .foregroundStyle(t2.pct >= 0 ? .green : .red)
            }
        }
        .padding()
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(t2.pct >= 0 ? Color.green.opacity(0.08) : Color.red.opacity(0.08))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(t2.pct >= 0 ? Color.green.opacity(0.3) : Color.red.opacity(0.3)))
        )
    }
}

struct TechMetricsCard: View {
    let rsi: Double?
    let macd: (macd: Double, signal: Double, histogram: Double)?
    let bb: (upper: Double, middle: Double, lower: Double, percent: Double)?
    let score: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("TÍN HIỆU KỸ THUẬT").font(.caption.bold()).foregroundStyle(.secondary)
            HStack(spacing: 12) {
                if let rsi = rsi {
                    MetricTile(label: "RSI", value: String(format: "%.0f", rsi),
                               color: rsi < 35 ? .green : rsi > 65 ? .red : .blue)
                }
                if let bb = bb {
                    MetricTile(label: "BB%", value: String(format: "%.0f", bb.percent * 100),
                               color: bb.percent < 0.2 ? .green : bb.percent > 0.8 ? .red : .blue)
                }
                if let macd = macd {
                    MetricTile(label: "MACD", value: macd.histogram > 0 ? "▲" : "▼",
                               color: macd.histogram > 0 ? .green : .red)
                }
                MetricTile(label: "SCORE", value: score >= 0 ? "+\(score)" : "\(score)",
                           color: score >= 3 ? .green : score <= -3 ? .red : .secondary)
            }
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}

struct RiskMetricsCard: View {
    let vol: Double?
    let dd: Double?
    let sharpe: Double?
    let ret30: Double?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("HIỆU SUẤT & RỦI RO").font(.caption.bold()).foregroundStyle(.secondary)
            HStack(spacing: 12) {
                if let r = ret30 {
                    MetricTile(label: "1T", value: r.toPct(), color: r >= 0 ? .green : .red)
                }
                if let v = vol {
                    MetricTile(label: "Biến động", value: String(format: "%.1f%%", v), color: .orange)
                }
                if let d = dd {
                    MetricTile(label: "Max DD", value: String(format: "-%.1f%%", d), color: .red)
                }
                if let s = sharpe {
                    MetricTile(label: "Sharpe", value: String(format: "%.2f", s),
                               color: s >= 1 ? .green : s >= 0 ? .yellow : .red)
                }
            }
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}

struct MetricTile: View {
    let label: String
    let value: String
    let color: Color

    var body: some View {
        VStack(spacing: 3) {
            Text(label).font(.system(size: 9)).foregroundStyle(.secondary)
            Text(value).font(.caption.bold().monospaced()).foregroundStyle(color)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
        .background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Fund Detail Sheet
struct FundDetailSheet: View {
    @ObservedObject var manager: FundAppManager
    let code: String
    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            if let history = manager.cachedNav[code], !history.isEmpty {
                FundAnalysisView(manager: manager, code: code, history: history)
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button("Đóng") { dismiss() }
                        }
                    }
            } else {
                VStack { ProgressView("Đang tải \(code)...") }.frame(maxWidth: .infinity, maxHeight: .infinity)
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) { Button("Đóng") { dismiss() } }
                    }
            }
        }
    }
}

// MARK: - Settings View
struct SettingsView: View {
    @ObservedObject var manager: FundAppManager
    @State private var apiBaseInput: String = ""
    @State private var showSaved = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Kết nối Server") {
                    HStack {
                        Text("API Base").foregroundStyle(.secondary)
                        TextField("http://localhost:8443", text: $apiBaseInput)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .multilineTextAlignment(.trailing)
                    }
                    Button(showSaved ? "Đã lưu ✓" : "Lưu & kết nối lại") {
                        if !apiBaseInput.isEmpty { manager.apiBase = apiBaseInput }
                        manager.fetchData()
                        showSaved = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { showSaved = false }
                    }
                    .foregroundStyle(showSaved ? .green : .cyan)
                }
                Section("Trạng thái") {
                    LabeledContent("API") { Text(manager.apiAvailable ? "Online ✓" : "Offline").foregroundStyle(manager.apiAvailable ? .green : .secondary) }
                    LabeledContent("Tín hiệu") { Text("\(manager.signals.count) quỹ").foregroundStyle(.secondary) }
                    LabeledContent("NAV cache") { Text("\(manager.cachedNav.count) quỹ").foregroundStyle(.secondary) }
                }
            }
            .navigationTitle("Cài Đặt")
            .onAppear { apiBaseInput = manager.apiBase }
        }
    }
}

// MARK: - Shared UI Components
struct SignalBadge: View {
    let signal: String

    var color: Color {
        if signal.contains("MUA MẠNH") { return .green }
        if signal.contains("MUA") { return .mint }
        if signal.contains("BÁN MẠNH") || signal.contains("BAN MANH") { return .red }
        if signal.contains("BÁN") || signal.contains("BAN") { return .orange }
        return .blue
    }

    var body: some View {
        Text(signal)
            .font(.system(size: 9, weight: .bold))
            .padding(.horizontal, 5).padding(.vertical, 2)
            .background(color.opacity(0.18), in: RoundedRectangle(cornerRadius: 4))
            .foregroundStyle(color)
    }
}

struct FilterChip: View {
    let title: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title).font(.caption.bold())
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(isSelected ? Color.cyan.opacity(0.2) : Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 16))
                .foregroundStyle(isSelected ? Color.cyan : Color.secondary)
                .overlay(RoundedRectangle(cornerRadius: 16).stroke(isSelected ? Color.cyan.opacity(0.5) : Color.clear))
        }
        .buttonStyle(.plain)
    }
}

struct SearchBar: View {
    @Binding var text: String

    var body: some View {
        HStack {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
            TextField("Tìm quỹ...", text: $text).autocorrectionDisabled()
            if !text.isEmpty {
                Button { text = "" } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                }
            }
        }
        .padding(8)
        .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 10))
        .padding(.horizontal)
    }
}

// Minimal FlowLayout for allocation bar legend
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxW = proposal.width ?? .infinity
        var x: CGFloat = 0; var y: CGFloat = 0; var rowH: CGFloat = 0; var totalH: CGFloat = 0
        for sv in subviews {
            let size = sv.sizeThatFits(.unspecified)
            if x + size.width > maxW { x = 0; y += rowH + spacing; totalH = y; rowH = 0 }
            x += size.width + spacing; rowH = max(rowH, size.height)
        }
        return CGSize(width: maxW, height: totalH + rowH)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX; var y = bounds.minY; var rowH: CGFloat = 0
        for sv in subviews {
            let size = sv.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX { x = bounds.minX; y += rowH + spacing; rowH = 0 }
            sv.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing; rowH = max(rowH, size.height)
        }
    }
}
