import SwiftUI

struct PeopleView: View {
    @Environment(AppStore.self) private var store
    @State private var note: String?
    @State private var enrollName = ""
    @State private var enrolling = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text("\(store.people.count) enrolled · 1 unknown")
                        .font(Theme.body(15))
                        .foregroundStyle(Theme.secondary)
                    Text("Every voice gets a block.")
                        .font(Theme.display(36))
                        .foregroundStyle(Theme.ink)
                        .padding(.bottom, 8)

                    ForEach(store.people) { p in
                        NavigationLink { PersonDetailView(person: p) } label: {
                            PersonRow(person: p)
                        }
                        .buttonStyle(SquishStyle())
                    }

                    // Unknown speakers are never given a guessed name:
                    // type the real name, then Enroll. Real mode posts it to
                    // POST /people (name-only: the app captures no photo or
                    // voice sample, so no photo/voice parts are sent). Mock
                    // mode adds the person locally, unverified.
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(spacing: 14) {
                            Text("?")
                                .font(Theme.display(26))
                                .foregroundStyle(Theme.secondary)
                                .frame(width: 60, height: 60)
                                .background(ToyBlock(color: Theme.greyBlue, cornerRadius: 18))
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Unknown").font(Theme.title(20)).foregroundStyle(Theme.ink)
                                Text("3 segments · not enrolled").font(Theme.body(15)).foregroundStyle(Theme.secondary)
                            }
                            Spacer()
                            Button {
                                Task {
                                    enrolling = true
                                    let name = enrollName.trimmingCharacters(in: .whitespacesAndNewlines)
                                    let ok = await store.enrollPerson(name: name)
                                    enrolling = false
                                    if ok {
                                        note = "ENROLLED \(name.uppercased())"
                                        enrollName = ""
                                    } else {
                                        note = store.lastError ?? "ENROLL FAILED"
                                    }
                                }
                            } label: {
                                Text(enrolling ? "Enrolling…" : "Enroll")
                                    .font(Theme.title(15))
                                    .foregroundStyle(Theme.paper)
                                    .padding(.horizontal, 16)
                                    .frame(height: 44)
                                    .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.ink))
                            }
                            .buttonStyle(SquishStyle())
                            .disabled(enrollName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || enrolling)
                        }
                        TextField("Name for this speaker", text: $enrollName)
                            .font(Theme.body(17))
                            .autocorrectionDisabled()
                            #if os(iOS)
                            .textInputAutocapitalization(.words)
                            #endif
                            .padding(.horizontal, 14)
                            .frame(height: 48)
                            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.pill))
                        if let note {
                            Text(note).font(Theme.mono(12)).foregroundStyle(Theme.secondary)
                        }
                    }
                    .padding(12)
                    .background(RoundedRectangle(cornerRadius: 26, style: .continuous).fill(Theme.paper))
                    .overlay(RoundedRectangle(cornerRadius: 26, style: .continuous).strokeBorder(Theme.pill, lineWidth: 2))
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 110)
            }
            .background(Theme.paper)
            .navigationTitle("People")
            .navigationBarTitleDisplayMode(.inline)
        }
        .task { await store.loadPeople() }
    }
}

struct PersonRow: View {
    let person: Person
    var body: some View {
        HStack(spacing: 14) {
            Text(String(person.name.prefix(1)))
                .font(Theme.display(24))
                .foregroundStyle(Theme.paper)
                .frame(width: 60, height: 60)
                .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Color(hex: 0x55595D)))
                .overlay(alignment: .bottomTrailing) {
                    if person.verified {
                        Image(systemName: "checkmark")
                            .font(.system(size: 10, weight: .heavy))
                            .foregroundStyle(Theme.ink)
                            .frame(width: 22, height: 22)
                            .background(Circle().fill(Theme.tint))
                            .overlay(Circle().strokeBorder(Theme.paper, lineWidth: 2))
                            .offset(x: 6, y: 6)
                    }
                }
            VStack(alignment: .leading, spacing: 2) {
                Text(person.name).font(Theme.title(22)).foregroundStyle(Theme.ink)
                Text("\(person.quotes) quotes · \(person.scenes) scenes")
                    .font(Theme.body(15))
                    .foregroundStyle(Theme.secondary)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(Theme.secondary)
        }
        .padding(12)
        .background(ToyBlock(color: Theme.greyBlue, cornerRadius: 26))
    }
}

/// Per-person view, built only from loaded data + contract routes:
/// scenes come from store.scenes (speaker match), facts from
/// GET /facts?actor=<name> (real mode) or the person's quoted scenes (mock).
struct PersonDetailView: View {
    @Environment(AppStore.self) private var store
    let person: Person
    @State private var opened: SceneItem?
    @State private var facts: [FactItem]?
    @State private var factsLoaded = false

    private var personScenes: [SceneItem] {
        store.scenes.filter { $0.speaker == person.name }
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 14) {
                    Text(String(person.name.prefix(1)))
                        .font(Theme.display(26))
                        .foregroundStyle(Theme.paper)
                        .frame(width: 72, height: 72)
                        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Color(hex: 0x55595D)))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(person.name).font(Theme.display(32)).foregroundStyle(Theme.ink)
                        Text(person.verified ? "VERIFIED · FACE + VOICE" : "NOT VERIFIED")
                            .font(Theme.mono(12)).foregroundStyle(Theme.secondary)
                        if let last = person.lastSeen {
                            Text("LAST SEEN \(last)").font(Theme.mono(12)).foregroundStyle(Theme.secondary)
                        }
                    }
                }
                Text("\(person.quotes) quotes · \(person.scenes) scenes · \(personScenes.count) blocks today")
                    .font(Theme.body(15)).foregroundStyle(Theme.secondary)

                Text("WHAT THEY SAID").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
                if let facts {
                    if facts.isEmpty {
                        Text("No facts recorded for \(person.name) yet.")
                            .font(Theme.body(15)).foregroundStyle(Theme.secondary)
                    } else {
                        ForEach(facts) { f in
                            VStack(alignment: .leading, spacing: 4) {
                                Text("“\(f.text)”").font(Theme.title(18)).foregroundStyle(Theme.ink)
                                if let sid = f.sceneId, let s = store.scenes.first(where: { $0.id == sid }) {
                                    Button { opened = s } label: {
                                        Text("FROM \(s.startTs.clock) · TAP TO OPEN THE SCENE")
                                            .font(Theme.mono(11)).foregroundStyle(Theme.secondary)
                                    }
                                    .buttonStyle(SquishStyle())
                                }
                            }
                            .padding(14)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(Theme.pill))
                        }
                    }
                } else {
                    Text("LOADING FACTS…").font(Theme.mono(12)).foregroundStyle(Theme.secondary)
                }

                Text("THEIR SCENES").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.secondary)
                if personScenes.isEmpty {
                    Text("No blocks with \(person.name) today.")
                        .font(Theme.body(15)).foregroundStyle(Theme.secondary)
                } else {
                    ForEach(personScenes) { s in
                        Button { opened = s } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(s.quote ?? s.summary)
                                    .font(Theme.title(18)).foregroundStyle(Theme.ink)
                                    .multilineTextAlignment(.leading)
                                Text("\(s.startTs.clock) · \(s.type.uppercased())")
                                    .font(Theme.mono(12)).foregroundStyle(Theme.secondary)
                            }
                            .padding(14)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(Theme.pill))
                        }
                        .buttonStyle(SquishStyle())
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, 40)
        }
        .background(Theme.paper)
        .navigationTitle(person.name)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            // Guard against double-load on reappear; facts are per-person.
            if !factsLoaded {
                facts = await store.loadFacts(for: person.name)
                factsLoaded = true
            }
        }
        .sheet(item: $opened) { scene in
            SceneDetailView(scene: scene) { question in
                // No tab binding here: stash the question in the store and
                // dismiss; tapping the Ask tab consumes it into shared history.
                store.pendingQuery = question
                opened = nil
            }
        }
    }
}
