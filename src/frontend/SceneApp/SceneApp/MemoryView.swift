import SwiftUI

struct MemoryView: View {
    @Environment(AppStore.self) private var store
    @Binding var tab: AppTab
    @State private var opened: SceneItem?
    @State private var showAsk = false
    @State private var appeared = false
    @State private var showFollowUps = false

    private var featured: SceneItem? {
        store.scenes.first { $0.speaker == "Maya" && $0.quote != nil }
            ?? store.scenes.first { $0.quote != nil }
    }

    private var statsLine: String {
        let date = Date().formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day()).uppercased()
        let people = Set(store.scenes.compactMap { $0.speaker }).count
        let elapsed = store.elapsed()
        let h = Int(elapsed) / 3600
        let m = (Int(elapsed) % 3600) / 60
        return "\(date) · \(store.scenes.count) BLOCKS · \(people) PEOPLE · \(h)H \(m)M"
    }

    var body: some View {
        ZStack(alignment: .bottom) {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Today").font(Theme.display(40)).foregroundStyle(Theme.ink)
                    Text(statsLine).font(Theme.mono()).foregroundStyle(Theme.secondary)
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)

                if store.scenes.isEmpty {
                    EmptyDay().padding(.horizontal, 20)
                } else {
                    TimelineStrip(scenes: store.scenes, highlighted: featured?.id, pinned: store.pinned, appeared: appeared) { opened = $0 }
                }

                if let f = featured {
                    Button { opened = f } label: { FeaturedQuote(scene: f) }
                        .buttonStyle(SquishStyle())
                        .padding(.horizontal, 20)
                }

                Button { showFollowUps = true } label: { FollowUpsEntry() }
                    .buttonStyle(SquishStyle())
                    .padding(.horizontal, 20)

                if let err = store.lastError {
                    Text(err).font(Theme.mono(12)).foregroundStyle(Theme.danger).padding(.horizontal, 20)
                }

            }
            .padding(.bottom, 240)
        }
        .refreshable { await store.loadToday() }

        // Floating Ask bar, pinned above the nav pill
        VStack(alignment: .leading, spacing: 10) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(MockData.suggestions, id: \.self) { q in
                        Button {
                            store.pendingQuery = q
                            showAsk = true
                        } label: { Chip(text: q) }
                        .buttonStyle(SquishStyle())
                    }
                }
                .padding(.horizontal, 20)
            }
            Button { showAsk = true } label: { AskBarLabel() }
                .buttonStyle(SquishStyle())
                .padding(.horizontal, 20)
        }
        .padding(.top, 14)
        .padding(.bottom, 92)
        .background(
            LinearGradient(colors: [Theme.paper.opacity(0), Theme.paper, Theme.paper],
                           startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
        )
        }
        .onAppear { appeared = true }
        // When connected to a server, pick up new scenes on their own (no pull-to-refresh needed)
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 15_000_000_000)
                if !store.useMock { await store.loadToday() }
            }
        }
        .sensoryFeedback(.impact(weight: .light), trigger: opened)
        .sheet(item: $opened) { scene in
            SceneDetailView(scene: scene) { question in
                store.pendingQuery = question
                opened = nil
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { showAsk = true }
            }
        }
        .sheet(isPresented: $showFollowUps) {
            FollowUpsView()
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showAsk) {
            AskView(bottomPadding: 16, autoFocus: true)
                .padding(.top, 8)
                .background(Theme.paper)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
    }
}

struct TimelineStrip: View {
    let scenes: [SceneItem]
    let highlighted: String?
    let pinned: Set<String>
    var appeared = true
    let onTap: (SceneItem) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .bottom, spacing: 6) {
                ForEach(Array(scenes.enumerated()), id: \.element.id) { index, s in
                    Button { onTap(s) } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(s.startTs.clock)
                                .font(Theme.mono(11))
                                .foregroundStyle(.white.opacity(0.6))
                                .lineLimit(1)
                            ToyBlock(color: s.blockColor, cornerRadius: 22)
                                .frame(width: s.blockWidth, height: 150)
                                .overlay(
                                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                                        .strokeBorder(Theme.accent, lineWidth: s.id == highlighted ? 3 : 0)
                                )
                                .overlay(alignment: .topTrailing) {
                                    if pinned.contains(s.id) {
                                        Image(systemName: "pin.fill")
                                            .font(.system(size: 11, weight: .bold))
                                            .foregroundStyle(Theme.ink)
                                            .padding(8)
                                    }
                                }
                        }
                    }
                    .buttonStyle(SquishStyle())
                    // Blocks cascade in: the memory builds itself (spec §6.2)
                    .offset(y: appeared ? 0 : 16)
                    .opacity(appeared ? 1 : 0)
                    .animation(Springs.jelly.delay(Double(index) * 0.05), value: appeared)
                    .accessibilityLabel("\(s.summary), \(s.startTs.clock)")
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 16)
        }
        .defaultScrollAnchor(.trailing)   // open on the newest scenes
        .background(Theme.trueBlack)
    }
}

struct FeaturedQuote: View {
    let scene: SceneItem

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                ConfidenceBadge(confidence: scene.displayConfidence)
                Text("\((scene.speaker ?? "UNKNOWN").uppercased()) · \(scene.startTs.clock)")
                    .font(Theme.mono())
                    .foregroundStyle(Theme.secondary)
            }
            HStack(alignment: .bottom, spacing: 16) {
                Text("“\(scene.quote ?? scene.summary)”")
                    .font(Theme.title(28))
                    .foregroundStyle(Theme.ink)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
                Image(systemName: "arrow.right")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Theme.paper)
                    .frame(width: 44, height: 44)
                    .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.ink))
            }
        }
    }
}

struct EmptyDay: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                ToyBlock(color: Theme.greyBlue, cornerRadius: 18).frame(width: 56, height: 56).rotationEffect(.degrees(-6))
                ToyBlock(color: Theme.mist, cornerRadius: 14).frame(width: 42, height: 42).rotationEffect(.degrees(5))
                ToyBlock(color: Theme.tint, cornerRadius: 10).frame(width: 30, height: 30)
            }
            Text("No blocks yet.").font(Theme.display(32)).foregroundStyle(Theme.ink)
            Text("Go live a little.").font(Theme.title(20)).foregroundStyle(Theme.secondary)
        }
        .padding(.vertical, 24)
    }
}
