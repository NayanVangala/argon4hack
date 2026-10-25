import SwiftUI

// Follow-through agent screens (spec §14.7, API: docs/SCENE-API-CONTRACT.md → /followups).
// The agent finds promises, checks each quote against the transcript, drafts a follow-up.
// Nothing is sent without an Approve tap. Unverified quotes stay under "needs review".

nonisolated struct FollowUp: Identifiable, Codable, Hashable {
    let id: String
    var runId: String?
    let promise: String
    let person: String
    let quote: String
    let quoteVerified: Bool
    var verifiedAt: String?
    var draft: String
    var status: String          // pending | approved | dismissed | sent | needs_review
    var sceneId: String?
    // Real backend extras (optional, so the mock server still decodes)
    var actionType: String? = nil       // email | reply | calendar | todo
    var recipient: String? = nil
    var dueAt: String? = nil
    var actionUrl: String? = nil        // mailto: or calendar link, returned on approve
    var webActionUrl: String? = nil     // Gmail web compose fallback
    var executionStatus: String? = nil

    var actionLabel: String? {
        switch actionType {
        case "email": return "EMAIL"
        case "reply": return "REPLY"
        case "calendar": return "CALENDAR EVENT"
        case "todo": return "TO-DO"
        default: return nil
        }
    }
}

nonisolated struct FollowUpRun: Codable {
    let runId: String
    let status: String
    let steps: [String]?
}

nonisolated struct FollowUpList: Codable {
    let followups: [FollowUp]
}

// MARK: - Entry point on Memory

struct FollowUpsEntry: View {
    @Environment(AppStore.self) private var store

    private var ready: Int { store.followups.filter { $0.status == "pending" }.count }

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: "checklist")
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(Theme.ink)
                .frame(width: 52, height: 52)
                .background(ToyBlock(color: Theme.tint, cornerRadius: 16))
            VStack(alignment: .leading, spacing: 3) {
                Text(store.followups.isEmpty ? "Follow-through" : "\(ready) follow-up\(ready == 1 ? "" : "s") ready")
                    .font(Theme.title(20))
                    .foregroundStyle(Theme.ink)
                Text(store.followups.isEmpty ? "FIND TODAY'S PROMISES" : "CHECKED AGAINST THE FOOTAGE")
                    .font(Theme.mono(12))
                    .foregroundStyle(Theme.secondary)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(Theme.secondary)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 24, style: .continuous).fill(Theme.pill))
    }
}

// MARK: - List

struct FollowUpsView: View {
    @Environment(AppStore.self) private var store
    @State private var opened: FollowUp?

    var body: some View {
        let ready = store.followups.filter { $0.status != "needs_review" }
        let review = store.followups.filter { $0.status == "needs_review" }

        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("FOLLOW-THROUGH").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
                Text("Promises, checked against the footage.")
                    .font(Theme.display(32))
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)

                if store.followupStep >= 0 {
                    AgentSteps(step: store.followupStep)
                }

                if let err = store.followupError {
                    Text(err).font(Theme.mono(12)).foregroundStyle(Theme.danger)
                }

                if store.followupStep < 0 && store.followups.isEmpty {
                    Button {
                        Task { await store.runFollowThrough() }
                    } label: {
                        Text("Find follow-ups")
                            .font(Theme.title(17))
                            .foregroundStyle(Theme.paper)
                            .frame(maxWidth: .infinity, minHeight: 52)
                            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Theme.ink))
                    }
                    .buttonStyle(SquishStyle())
                }

                ForEach(ready) { f in
                    Button { opened = f } label: { FollowUpRow(followup: f) }
                        .buttonStyle(SquishStyle())
                        .transition(.scale(scale: 0.92).combined(with: .opacity))
                }

                if !review.isEmpty {
                    Text("NEEDS REVIEW").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary).padding(.top, 8)
                    ForEach(review) { f in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(f.promise).font(Theme.title(17)).foregroundStyle(Theme.secondary)
                            Text("“\(f.quote)”").font(Theme.body(15)).foregroundStyle(Theme.secondary)
                            Text("COULDN'T MATCH THIS QUOTE TO THE FOOTAGE · NOT OFFERED FOR APPROVAL")
                                .font(Theme.mono(11))
                                .foregroundStyle(Theme.secondary)
                        }
                        .padding(14)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 22, style: .continuous).strokeBorder(Theme.pill, lineWidth: 2))
                    }
                }

                if store.followupStep == 3 {
                    Button {
                        Task { await store.runFollowThrough() }
                    } label: {
                        Text("Run again").font(Theme.title(15)).foregroundStyle(Theme.ink)
                            .padding(.horizontal, 18).frame(height: 44)
                            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.pill))
                    }
                    .buttonStyle(SquishStyle())
                    .padding(.top, 4)
                }
            }
            .padding(20)
            .animation(Springs.pop, value: store.followups)
        }
        .background(Theme.paper)
        .task {
            if store.followupStep < 0 && store.followups.isEmpty {
                await store.runFollowThrough()
            }
        }
        .sheet(item: $opened) { f in
            FollowUpDetailView(followupID: f.id)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
    }
}

/// The agent's three steps, ticking off live: the verification loop made visible.
struct AgentSteps: View {
    let step: Int   // 0, 1, 2 = running that step; 3 = done
    private let labels = ["FIND PROMISES IN TODAY", "CHECK EACH QUOTE AGAINST THE FOOTAGE", "DRAFT FOLLOW-UPS"]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(0..<3, id: \.self) { i in
                HStack(spacing: 10) {
                    ZStack {
                        Circle().fill(i < step ? Theme.tint : Theme.pill).frame(width: 24, height: 24)
                        if i < step {
                            Image(systemName: "checkmark").font(.system(size: 11, weight: .heavy)).foregroundStyle(Theme.ink)
                        } else if i == step {
                            Circle().fill(Theme.accent).frame(width: 8, height: 8)
                        }
                    }
                    Text(labels[i])
                        .font(Theme.mono(12))
                        .foregroundStyle(i <= step ? Theme.ink : Theme.secondary)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(Theme.pill.opacity(0.6)))
        .animation(Springs.snappy, value: step)
    }
}

struct FollowUpRow: View {
    let followup: FollowUp

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Text(String(followup.person.prefix(1)))
                .font(Theme.display(22))
                .foregroundStyle(Theme.paper)
                .frame(width: 52, height: 52)
                .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Color(hex: 0x55595D)))
            VStack(alignment: .leading, spacing: 8) {
                Text(followup.promise)
                    .font(Theme.title(18))
                    .foregroundStyle(Theme.ink)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 8) {
                    switch followup.status {
                    case "approved", "sent":
                        statusChip("APPROVED", icon: "checkmark", fill: Theme.tint)
                    case "dismissed":
                        statusChip("DISMISSED", icon: "xmark", fill: Theme.pill)
                    default:
                        ConfidenceBadge(confidence: followup.quoteVerified ? .verified : .review)
                        Text("QUOTE MATCHED").font(Theme.mono(11)).foregroundStyle(Theme.secondary)
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(ToyBlock(color: Theme.greyBlue, cornerRadius: 24))
    }

    private func statusChip(_ text: String, icon: String, fill: Color) -> some View {
        HStack(spacing: 5) {
            Image(systemName: icon).font(.system(size: 10, weight: .heavy))
            Text(text).font(Theme.mono(12))
        }
        .foregroundStyle(Theme.ink)
        .padding(.horizontal, 10)
        .frame(height: 26)
        .background(Capsule().fill(fill))
    }
}

// MARK: - Detail

struct FollowUpDetailView: View {
    @Environment(AppStore.self) private var store
    let followupID: String
    @State private var draft = ""
    @State private var working = false

    private var followup: FollowUp? { store.followups.first { $0.id == followupID } }

    var body: some View {
        if let f = followup {
            content(f)
        } else {
            Text("This follow-up is no longer available.").font(Theme.body()).padding(20)
        }
    }

    private func content(_ f: FollowUp) -> some View {
        let sceneTime = store.scenes.first { $0.id == f.sceneId }?.startTs.ISO8601Format() ?? (f.verifiedAt ?? "")
        let receipt = Receipt(sceneId: f.sceneId ?? f.id, timestamp: sceneTime, quote: f.quote,
                              confidence: f.quoteVerified ? "verified" : "review",
                              speaker: f.person == "Unknown" ? nil : f.person)
        let isPending = f.status == "pending"

        return ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("\(f.actionLabel ?? "FOLLOW-UP") · \(f.person.uppercased())")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Theme.secondary)
                Text(f.promise)
                    .font(Theme.display(28))
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)

                VStack(alignment: .leading, spacing: 8) {
                    Text("DRAFT").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
                    TextEditor(text: $draft)
                        .font(Theme.body(17))
                        .foregroundStyle(Theme.ink)
                        .scrollContentBackground(.hidden)
                        .frame(minHeight: 110)
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Theme.pill))
                        .disabled(!isPending)
                }

                Text("THE PROOF").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
                ReceiptCard(receipt: receipt)

                VStack(alignment: .leading, spacing: 10) {
                    Text("WHAT THE AGENT CHECKED").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
                    CheckLine(ok: true, text: "FOUND THE PROMISE IN TODAY'S MEMORY")
                    CheckLine(ok: f.quoteVerified, text: f.quoteVerified
                              ? "QUOTE MATCHES THE TRANSCRIPT, SAME SPEAKER, SAME TIME"
                              : "COULDN'T MATCH THE QUOTE TO THE FOOTAGE")
                    CheckLine(ok: true, text: isPending ? "DRAFT WRITTEN · WAITING FOR YOU" : "DRAFT WRITTEN")
                }

                if isPending {
                    HStack(spacing: 10) {
                        Button {
                            act(approve: true)
                        } label: {
                            Text("Approve")
                                .font(Theme.title(17))
                                .foregroundStyle(Theme.paper)
                                .frame(maxWidth: .infinity, minHeight: 52)
                                .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Theme.ink))
                        }
                        .buttonStyle(SquishStyle())
                        Button {
                            act(approve: false)
                        } label: {
                            Text("Dismiss")
                                .font(Theme.title(17))
                                .foregroundStyle(Theme.ink)
                                .frame(maxWidth: .infinity, minHeight: 52)
                                .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Theme.pill))
                        }
                        .buttonStyle(SquishStyle())
                    }
                    .disabled(working)
                    Text("NOTHING IS SENT UNTIL YOU APPROVE")
                        .font(Theme.mono(11))
                        .foregroundStyle(Theme.secondary)
                        .frame(maxWidth: .infinity)
                } else if f.status == "approved" || f.status == "sent" {
                    HStack(spacing: 10) {
                        Label("Approved", systemImage: "checkmark")
                            .font(Theme.title(17))
                            .foregroundStyle(Theme.ink)
                            .frame(maxWidth: .infinity, minHeight: 52)
                            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Theme.tint))
                        if let link = f.actionUrl.flatMap({ URL(string: $0) }) {
                            // The backend prepared it; you still press Send / Save yourself
                            Link(destination: link) {
                                Label(f.actionType == "calendar" ? "Open calendar" : "Open email",
                                      systemImage: f.actionType == "calendar" ? "calendar" : "envelope")
                                    .font(Theme.title(17))
                                    .foregroundStyle(Theme.paper)
                                    .frame(maxWidth: .infinity, minHeight: 52)
                                    .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Theme.ink))
                            }
                        } else if f.executionStatus != "added_to_todo_list" {
                            ShareLink(item: draft) {
                                Label("Send…", systemImage: "square.and.arrow.up")
                                    .font(Theme.title(17))
                                    .foregroundStyle(Theme.paper)
                                    .frame(maxWidth: .infinity, minHeight: 52)
                                    .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Theme.ink))
                            }
                        }
                    }
                    if f.executionStatus == "added_to_todo_list" {
                        Text("ADDED TO YOUR TO-DO LIST").font(Theme.mono(12)).foregroundStyle(Theme.secondary)
                    } else if f.actionUrl != nil {
                        Text("NOTHING IS SENT UNTIL YOU PRESS SEND IN YOUR EMAIL OR CALENDAR APP")
                            .font(Theme.mono(11)).foregroundStyle(Theme.secondary)
                    }
                } else {
                    Text("DISMISSED").font(Theme.mono(13)).foregroundStyle(Theme.secondary)
                }
            }
            .padding(20)
        }
        .background(Theme.paper)
        .onAppear { if draft.isEmpty { draft = f.draft } }
        .sensoryFeedback(.impact(weight: .medium), trigger: f.status)
    }

    private func act(approve: Bool) {
        working = true
        Task {
            await store.updateFollowUp(id: followupID, draft: draft, approve: approve)
            working = false
        }
    }
}

struct CheckLine: View {
    let ok: Bool
    let text: String
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: ok ? "checkmark" : "xmark")
                .font(.system(size: 10, weight: .heavy))
                .foregroundStyle(ok ? Theme.ink : Theme.secondary)
                .frame(width: 22, height: 22)
                .background(Circle().fill(ok ? Theme.tint : Theme.pill))
            Text(text)
                .font(Theme.mono(12))
                .foregroundStyle(ok ? Theme.ink : Theme.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
