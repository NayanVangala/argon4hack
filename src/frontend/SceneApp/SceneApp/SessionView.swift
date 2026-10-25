import SwiftUI

struct SessionView: View {
    @Environment(AppStore.self) private var store
    @State private var confirmWipe = false
    @State private var wipeCount = 0
    @State private var glow = false

    private var statsLine: String {
        let elapsed = store.elapsed()
        let h = Int(elapsed) / 3600
        let m = (Int(elapsed) % 3600) / 60
        return "\(h)H \(m)M · \(store.scenes.count) BLOCKS · 0 GAPS"
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("SESSION").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
                Text("Press record. Be present. We'll remember.")
                    .font(Theme.display(36))
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)

                VStack(spacing: 14) {
                    Button {
                        Task {
                            if store.isRecording {
                                await store.endSession()
                            } else {
                                await store.startSession()
                            }
                        }
                    } label: {
                        ZStack {
                            // Breathing ring while recording (spec §6.5)
                            RoundedRectangle(cornerRadius: 70, style: .continuous)
                                .stroke(Theme.soft, lineWidth: 6)
                                .frame(width: 220, height: 220)
                                .scaleEffect(glow && store.isRecording ? 1.04 : 0.98)
                                .opacity(store.isRecording ? (glow ? 0.25 : 0.7) : 0)
                                .animation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true), value: glow)
                            ToyBlock(color: Theme.greyBlue, cornerRadius: 60).frame(width: 200, height: 200)
                            RoundedRectangle(cornerRadius: 40, style: .continuous)
                                .fill(Theme.ink)
                                .frame(width: 128, height: 128)
                            if store.isRecording {
                                RoundedRectangle(cornerRadius: 10, style: .continuous)
                                    .fill(Theme.paper)
                                    .frame(width: 38, height: 38)
                            } else {
                                Circle().fill(Theme.danger).frame(width: 44, height: 44)
                            }
                        }
                    }
                    .buttonStyle(SquishStyle())
                    .animation(Springs.pop, value: store.isRecording)
                    .sensoryFeedback(.impact(weight: .heavy), trigger: store.isRecording)
                    .accessibilityLabel(store.isRecording ? "Stop recording" : "Start recording")

                    HStack(spacing: 8) {
                        Circle().fill(store.isRecording ? Theme.danger : Theme.secondary).frame(width: 10, height: 10)
                        Text(store.isRecording ? "Recording" : "Not recording").font(Theme.title(20))
                    }
                    .foregroundStyle(Theme.ink)
                    Text(statsLine).font(Theme.mono()).foregroundStyle(Theme.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)

                HStack {
                    Text("ARGON SPEND TODAY").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
                    Spacer()
                    Text(store.spendUsd.map { String(format: "$%.2f", $0) } ?? "$—")
                        .font(Theme.mono(20))
                        .foregroundStyle(Theme.ink)
                }
                .padding(.horizontal, 18)
                .frame(height: 60)
                .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(Theme.pill))

                Button { confirmWipe = true } label: {
                    HStack(spacing: 14) {
                        Image(systemName: "trash")
                            .font(.system(size: 22, weight: .semibold))
                            .foregroundStyle(Theme.danger)
                            .frame(width: 60, height: 60)
                            .background(ToyBlock(color: Theme.paper, cornerRadius: 20))
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Wipe the day").font(Theme.title(20)).foregroundStyle(Theme.ink)
                            Text("Erase today's blocks, transcripts and pins").font(Theme.body(15)).foregroundStyle(Theme.secondary)
                        }
                        Spacer()
                    }
                    .padding(8)
                    .background(RoundedRectangle(cornerRadius: 28, style: .continuous).fill(Theme.pill))
                }
                .buttonStyle(SquishStyle())

                if let note = store.wipeNote {
                    Text(note).font(Theme.mono(12)).foregroundStyle(Theme.secondary)
                }

                DeveloperSection()
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, 110)
        }
        .confirmationDialog("Wipe the day. No blocks left behind.", isPresented: $confirmWipe, titleVisibility: .visible) {
            Button("Wipe it", role: .destructive) {
                Task { await store.wipe() }
                wipeCount += 1
            }
            Button("Keep", role: .cancel) {}
        } message: {
            Text("Deletes today's \(store.scenes.count) blocks, transcripts and pins. This can't be undone.")
        }
        .sensoryFeedback(.impact(weight: .heavy), trigger: wipeCount)
        .onAppear {
            glow = true
            // Real mode only (refreshStatus no-ops under mock): pull GET /status
            // so the spend row shows real spend_usd, not "$—".
            Task { await store.refreshStatus() }
        }
    }
}

/// Switch between fake data and a real server without rebuilding the app.
struct DeveloperSection: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        @Bindable var store = store
        VStack(alignment: .leading, spacing: 12) {
            Text("DEVELOPER").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
            Toggle(isOn: $store.useMock) {
                Text("Use mock data").font(Theme.body(17)).foregroundStyle(Theme.ink)
            }
            .tint(Theme.accent)
            if !store.useMock {
                TextField("http://localhost:8000", text: $store.baseURL)
                    .font(Theme.mono(15))
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    #endif
                    .padding(.horizontal, 14)
                    .frame(height: 48)
                    .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.pill))
                SecureField("Token (if the server needs one)", text: Binding(
                    get: { store.token ?? "" },
                    set: { store.token = $0.isEmpty ? nil : $0 }))
                    .font(Theme.mono(15))
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .padding(.horizontal, 14)
                    .frame(height: 48)
                    .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.pill))
            }
            Button {
                Task { await store.loadToday() }
            } label: {
                Text("Reload")
                    .font(Theme.title(15))
                    .foregroundStyle(Theme.paper)
                    .padding(.horizontal, 18)
                    .frame(height: 44)
                    .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.ink))
            }
            .buttonStyle(SquishStyle())
            if let err = store.lastError {
                Text(err).font(Theme.mono(12)).foregroundStyle(Theme.danger)
            } else if !store.useMock {
                Text("CONNECTED · \(store.scenes.count) SCENES").font(Theme.mono(12)).foregroundStyle(Theme.secondary)
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 22, style: .continuous).strokeBorder(Theme.pill, lineWidth: 2))
        .padding(.top, 12)
    }
}
