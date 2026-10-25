import SwiftUI

enum AppTab: String, CaseIterable, Identifiable {
    case live, memory, ask, people, session
    var id: String { rawValue }
    var label: String { rawValue.uppercased() }
    var icon: String {
        switch self {
        case .live: return "dot.radiowaves.left.and.right"
        case .memory: return "square.grid.2x2"
        case .ask: return "bubble.left"
        case .people: return "person"
        case .session: return "record.circle"
        }
    }
}

/// Floating nav pill: black segment slides to the active tab.
struct NavPill: View {
    @Binding var tab: AppTab
    @Namespace private var ns

    var body: some View {
        HStack(spacing: 2) {
            ForEach(AppTab.allCases) { t in
                Button {
                    withAnimation(Springs.pop) { tab = t }
                } label: {
                    VStack(spacing: 3) {
                        Image(systemName: t.icon).font(.system(size: 17, weight: .semibold))
                        Text(t.label).font(.system(size: 11, weight: .bold))
                    }
                    .foregroundStyle(tab == t ? Theme.paper : Theme.ink)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .background {
                        if tab == t {
                            RoundedRectangle(cornerRadius: 20, style: .continuous)
                                .fill(Theme.ink)
                                .matchedGeometryEffect(id: "active", in: ns)
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(6)
        .background(RoundedRectangle(cornerRadius: 26, style: .continuous).fill(Theme.pill))
    }
}

/// Squish on press, pop on release.
struct SquishStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(x: configuration.isPressed ? 1.05 : 1, y: configuration.isPressed ? 0.94 : 1)
            .animation(configuration.isPressed ? Springs.press : Springs.pop, value: configuration.isPressed)
    }
}

/// Toy block: rounded squircle with a soft inflated highlight.
struct ToyBlock: View {
    let color: Color
    var cornerRadius: CGFloat = 24

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(color)
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(LinearGradient(colors: [.white.opacity(0.55), .clear], startPoint: .top, endPoint: .center))
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(.white.opacity(0.5), lineWidth: 1)
            )
    }
}

struct ConfidenceBadge: View {
    let confidence: Confidence
    var onDark = false

    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: icon).font(.system(size: 10, weight: .heavy))
            Text(label).font(Theme.mono(12))
        }
        .padding(.horizontal, 10)
        .frame(height: 26)
        .foregroundStyle(confidence == .verified ? Theme.ink : (onDark ? Color.white.opacity(0.8) : Theme.secondary))
        .background(Capsule().fill(background))
    }

    private var label: String {
        switch confidence {
        case .verified: return "VERIFIED"
        case .review: return "REVIEW"
        case .silence: return "NO SPEECH"
        case .unknown: return "COULDN'T CONFIRM"
        }
    }
    private var icon: String {
        switch confidence {
        case .verified: return "checkmark"
        case .review: return "questionmark"
        case .silence: return "speaker.slash"
        case .unknown: return "minus"
        }
    }
    private var background: Color {
        if confidence == .verified { return Theme.tint }
        return onDark ? Color.white.opacity(0.14) : Theme.pill
    }
}

struct Chip: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.system(size: 15))
            .foregroundStyle(Theme.ink)
            .padding(.horizontal, 14)
            .frame(height: 40)
            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.pill))
    }
}

/// Looks like the Ask input; used as a shortcut button on Memory.
struct AskBarLabel: View {
    var placeholder = "Ask about today…"
    var body: some View {
        HStack {
            Text(placeholder)
                .font(Theme.title(20))
                .foregroundStyle(Theme.secondary)
            Spacer()
            SendBlock()
        }
        .padding(.leading, 22)
        .padding(.trailing, 7)
        .frame(height: 60)
        .background(Capsule().fill(Theme.pill))
    }
}

struct SendBlock: View {
    var body: some View {
        Image(systemName: "arrow.up")
            .font(.system(size: 18, weight: .bold))
            .foregroundStyle(Theme.ink)
            .frame(width: 46, height: 46)
            .background(ToyBlock(color: Theme.tint, cornerRadius: 15))
    }
}

/// Dark receipt card: video thumbnail + verbatim quote + receipt line.
struct ReceiptCard: View {
    let receipt: Receipt

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center, spacing: 16) {
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .fill(Theme.photo)
                    .frame(width: 96, height: 96)
                    .overlay(
                        Image(systemName: "play.fill")
                            .font(.system(size: 14))
                            .foregroundStyle(Theme.ink)
                            .frame(width: 36, height: 36)
                            .background(Circle().fill(.white))
                    )
                Text("“\(receipt.quote)”")
                    .font(Theme.title(24))
                    .foregroundStyle(.white)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Rectangle().fill(.white.opacity(0.12)).frame(height: 1)
            HStack(spacing: 8) {
                ConfidenceBadge(confidence: receipt.displayConfidence, onDark: true)
                Text(sourceLabel).font(Theme.mono(12)).foregroundStyle(.white.opacity(0.7))
            }
            Text(receiptLine)
                .font(Theme.mono(12))
                .foregroundStyle(.white.opacity(0.7))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 28, style: .continuous).fill(Theme.ink))
    }

    private var sourceLabel: String {
        receipt.displayConfidence == .verified ? "FACE + VOICE" : "VOICE ONLY"
    }
    private var receiptLine: String {
        if receipt.displayConfidence == .verified {
            if let s = receipt.speaker { return "[\(s.uppercased()) · VERIFIED VERBATIM · \(receipt.displayTime)]" }
            return "[VERIFIED VERBATIM · \(receipt.displayTime)]"
        }
        return "[UNKNOWN SPEAKER · NOT VERIFIED · \(receipt.displayTime)]"
    }
}

extension SceneItem {
    var blockColor: Color {
        switch type {
        case "conversation": return Theme.mist
        case "action": return Theme.soft
        case "quote": return Theme.tint
        case "location": return Theme.greyBlue
        default: return Theme.greyBlue
        }
    }
    /// Longer scenes get wider blocks, but every block is wide enough to tap and to show its time.
    var blockWidth: CGFloat { CGFloat(min(140, max(64, minutes * 9))) }
}
