import SwiftUI

struct SceneDetailView: View {
    @Environment(AppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let scene: SceneItem
    var onAsk: (String) -> Void

    private var isPinned: Bool { store.pinned.contains(scene.id) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text(scene.type.uppercased())
                        .font(Theme.mono(12))
                        .foregroundStyle(Theme.ink)
                        .padding(.horizontal, 10)
                        .frame(height: 26)
                        .background(Capsule().fill(Theme.pill))
                    Spacer()
                    Text(scene.startTs.clock).font(Theme.mono()).foregroundStyle(Theme.secondary)
                }

                Text("“\(scene.quote ?? scene.summary)”")
                    .font(Theme.display(34))
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 8) {
                    ConfidenceBadge(confidence: scene.displayConfidence)
                    Text("\((scene.speaker ?? "UNKNOWN").uppercased()) · VERBATIM")
                        .font(Theme.mono(12))
                        .foregroundStyle(Theme.secondary)
                }

                // Video receipt (real clip URL is an API gap; placeholder for now)
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .fill(Theme.photo)
                    .frame(height: 190)
                    .overlay(
                        Image(systemName: "play.fill")
                            .font(.system(size: 18))
                            .foregroundStyle(Theme.ink)
                            .frame(width: 56, height: 56)
                            .background(Circle().fill(.white))
                    )
                    .overlay(alignment: .bottomTrailing) {
                        Text(durationLabel)
                            .font(Theme.mono(12))
                            .foregroundStyle(.white)
                            .padding(.horizontal, 8)
                            .frame(height: 24)
                            .background(Capsule().fill(.black.opacity(0.6)))
                            .padding(12)
                    }

                Text(scene.summary).font(Theme.body(15)).foregroundStyle(Theme.ink)

                HStack(spacing: 10) {
                    Button {
                        Task { await store.pin(scene) }
                    } label: {
                        Label(isPinned ? "Pinned" : "Pin", systemImage: isPinned ? "checkmark" : "pin")
                            .font(Theme.title(17))
                            .foregroundStyle(isPinned ? Theme.ink : Theme.paper)
                            .frame(maxWidth: .infinity, minHeight: 52)
                            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(isPinned ? Theme.tint : Theme.ink))
                    }
                    .buttonStyle(SquishStyle())
                    .sensoryFeedback(.impact(weight: .medium), trigger: isPinned)

                    Button {
                        onAsk("Tell me more about \(scene.summary.lowercased())")
                    } label: {
                        Text("Ask about this")
                            .font(Theme.title(17))
                            .foregroundStyle(Theme.ink)
                            .frame(maxWidth: .infinity, minHeight: 52)
                            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Theme.pill))
                    }
                    .buttonStyle(SquishStyle())
                }
            }
            .padding(20)
        }
        .background(Theme.paper)
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
    }

    private var durationLabel: String {
        let secs = Int(scene.endTs.timeIntervalSince(scene.startTs))
        return String(format: "%d:%02d", secs / 60, secs % 60)
    }
}
