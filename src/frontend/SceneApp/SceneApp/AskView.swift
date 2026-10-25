import SwiftUI

struct AskView: View {
    @Environment(AppStore.self) private var store
    var bottomPadding: CGFloat = 92
    var autoFocus = false   // room for the nav pill; smaller when shown as a sheet
    @State private var query = ""
    // History lives in store.askHistory (shared, above the tabs), NOT here:
    // this view is recreated on every tab switch, so local @State history
    // would vanish. Only the in-progress draft input stays local.
    @FocusState private var focused: Bool

    private var loading: Bool { store.askHistory.last?.isLoading == true }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    // Day stays visible as a slim strip (Ask floats over the memory)
                    HStack {
                        Text("TODAY").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
                        Spacer()
                        Text("\(store.scenes.count) BLOCKS").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
                    }
                    MiniStrip(scenes: store.scenes)

                    if store.askHistory.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Ask anything.").font(Theme.display(36)).foregroundStyle(Theme.ink)
                            Text("Every answer comes with the video to prove it.")
                                .font(Theme.body(17)).foregroundStyle(Theme.secondary)
                        }
                        .padding(.top, 12)
                    }

                    // Full shared history, oldest first: every past turn stays
                    // visible when you come back from another tab.
                    ForEach(store.askHistory) { turn in
                        VStack(alignment: .leading, spacing: 14) {
                            HStack {
                                Spacer(minLength: 40)
                                Text(turn.question)
                                    .font(Theme.body(17))
                                    .foregroundStyle(Theme.ink)
                                    .padding(.horizontal, 18)
                                    .padding(.vertical, 12)
                                    .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(Theme.pill))
                            }
                            if turn.isLoading {
                                Text("CHECKING THE FOOTAGE…")
                                    .font(Theme.mono())
                                    .foregroundStyle(Theme.secondary)
                                    .transition(.opacity)
                            } else if let r = turn.response {
                                VStack(alignment: .leading, spacing: 14) {
                                    Text("ANSWER").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
                                    Text(r.answer)
                                        .font(Theme.body(17))
                                        .foregroundStyle(Theme.ink)
                                        .fixedSize(horizontal: false, vertical: true)
                                    ForEach(r.receipts) { receipt in
                                        ReceiptCard(receipt: receipt)
                                            .transition(.scale(scale: 0.92).combined(with: .opacity))
                                    }
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 20)
            }
            .scrollDismissesKeyboard(.interactively)

            VStack(spacing: 10) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(MockData.suggestions, id: \.self) { s in
                            Button {
                                query = s
                                submit()
                            } label: { Chip(text: s) }
                            .buttonStyle(SquishStyle())
                        }
                    }
                    .padding(.horizontal, 20)
                }
                HStack(alignment: .bottom) {
                    // Grows up to 5 lines as you type; Return sends
                    TextField("Ask anything…", text: $query, axis: .vertical)
                        .font(Theme.title(20))
                        .foregroundStyle(Theme.ink)
                        .lineLimit(1...5)
                        .focused($focused)
                        .submitLabel(.send)
                        .padding(.vertical, 17)
                        .onChange(of: query) { _, newValue in
                            if newValue.contains("\n") {
                                query = newValue.replacingOccurrences(of: "\n", with: "")
                                submit()
                            }
                        }
                    Button { submit() } label: { SendBlock() }
                        .buttonStyle(SquishStyle())
                        .disabled(loading)
                        .accessibilityLabel("Send")
                        .padding(.bottom, 7)
                }
                .padding(.leading, 22)
                .padding(.trailing, 7)
                .frame(minHeight: 60)
                .background(RoundedRectangle(cornerRadius: 30, style: .continuous).fill(Theme.pill))
                .padding(.horizontal, 20)
            }
            .padding(.bottom, bottomPadding)
        }
        .onAppear {
            if let q = store.pendingQuery {
                store.pendingQuery = nil
                query = q
                submit()
            } else if autoFocus {
                // Open the keyboard right away so one tap is enough
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { focused = true }
            }
        }
    }

    private func submit() {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !loading else { return }
        query = ""
        focused = false
        // The turn (and its loading state) lives in the store, so it
        // survives this view being torn down on a tab switch.
        Task { await store.submitAsk(q) }
    }
}

struct MiniStrip: View {
    let scenes: [SceneItem]
    var body: some View {
        HStack(spacing: 4) {
            ForEach(scenes.suffix(24)) { s in   // most recent part of the day
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(s.blockColor)
                    .frame(width: max(8, s.blockWidth / 6), height: 30)
            }
            Spacer(minLength: 0)
        }
        .padding(8)
        .frame(height: 48)
        .background(Capsule().fill(Theme.trueBlack))
    }
}
