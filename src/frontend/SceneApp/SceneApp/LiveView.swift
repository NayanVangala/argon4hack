import SwiftUI

struct LiveView: View {
    @Environment(AppStore.self) private var store

    @State private var breathe = false
    @State private var showStickers = false

    private var current: SceneItem? { store.scenes.last }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                HStack(spacing: 6) {
                    Circle().fill(store.isRecording ? Theme.tint : Color.gray).frame(width: 8, height: 8)
                        // LIVE dot breathes 1 → 1.18 (spec §6.1)
                        .scaleEffect(breathe && store.isRecording ? 1.18 : 1)
                        .animation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true), value: breathe)
                    Text(store.isRecording ? "LIVE" : "PAUSED").font(Theme.mono(13))
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 12)
                .frame(height: 32)
                .background(Capsule().fill(.white.opacity(0.12)))
                Spacer()
                Text("SCENE \(store.scenes.count)").font(Theme.mono(13)).foregroundStyle(.white.opacity(0.6))
                Spacer()
                Button {
                    Task { await store.setRecording(!store.isRecording) }
                } label: {
                    Text(store.isRecording ? "End" : "Start")
                        .font(Theme.title(15))
                        .foregroundStyle(Theme.ink)
                        .padding(.horizontal, 16)
                        .frame(height: 36)
                        .background(Capsule().fill(Theme.pill))
                }
                .buttonStyle(SquishStyle())
            }

            Text("RECORDING FOR")
                .font(Theme.mono(12))
                .foregroundStyle(.white.opacity(0.6))
                .padding(.bottom, -12)
            HStack(alignment: .lastTextBaseline) {
                TimelineView(.periodic(from: .now, by: 1.0)) { context in
                    Text(elapsed(at: context.date))
                        .font(Theme.display(60))
                        .monospacedDigit()
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)   // never wraps the seconds onto a second line
                        .foregroundStyle(.white)
                }
                Spacer()
                Text("Started \(store.sessionStart.clock)\n\(Date().formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day()))")
                    .font(Theme.body(15))
                    .multilineTextAlignment(.trailing)
                    .foregroundStyle(.white.opacity(0.7))
                    .fixedSize()
            }

            // Camera feed / latest keyframe goes here once capture is wired
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .fill(Theme.photo)
                .overlay(
                    Text("CAMERA FEED")
                        .font(Theme.mono(12))
                        .foregroundStyle(.white.opacity(0.4))
                )
                .overlay(alignment: .bottomLeading) {
                    HStack(spacing: 6) {
                        ForEach(Array(["Maya", "laptop", "meeting"].enumerated()), id: \.offset) { i, label in
                            Sticker(text: label, verified: i == 0)
                                // Stickers pop in with a 0.04 stagger (spec §6.1)
                                .scaleEffect(showStickers ? 1 : 0.4)
                                .opacity(showStickers ? 1 : 0)
                                .animation(Springs.pop.delay(0.3 + Double(i) * 0.04), value: showStickers)
                        }
                    }
                    .padding(14)
                }

            VStack(alignment: .leading, spacing: 6) {
                Text("NOW · \((current?.startTs ?? Date()).clock)")
                    .font(Theme.mono(12))
                    .foregroundStyle(.white.opacity(0.6))
                Text(current?.summary ?? "Waiting for the first scene…")
                    .font(Theme.title(26))
                    .foregroundStyle(.white)
                    .fixedSize(horizontal: false, vertical: true)
                    .contentTransition(.opacity)
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 12)
        .padding(.bottom, 100)
        .background(Theme.trueBlack.ignoresSafeArea())
        .onAppear {
            breathe = true
            showStickers = true
        }
    }

    private func elapsed(at date: Date) -> String {
        let total = Int(store.elapsed(at: date))
        let h = total / 3600, m = (total % 3600) / 60, s = total % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%02d:%02d", m, s)
    }
}

struct Sticker: View {
    let text: String
    var verified = false
    var body: some View {
        HStack(spacing: 4) {
            if verified { Image(systemName: "checkmark").font(.system(size: 11, weight: .heavy)) }
            Text(text).font(.system(size: 15, weight: .bold))
        }
        .foregroundStyle(Theme.ink)
        .padding(.horizontal, 12)
        .frame(height: 34)
        .background(ToyBlock(color: verified ? Theme.tint : Theme.greyBlue, cornerRadius: 12))
    }
}
