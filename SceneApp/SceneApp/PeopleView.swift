import SwiftUI

struct PeopleView: View {
    @Environment(AppStore.self) private var store
    @State private var note: String?

    var body: some View {
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
                    PersonRow(person: p)
                }

                // Unknown speakers are never given a guessed name
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
                    Button { note = "ENROLLMENT ISN'T CONNECTED YET" } label: {
                        Text("Enroll")
                            .font(Theme.title(15))
                            .foregroundStyle(Theme.paper)
                            .padding(.horizontal, 16)
                            .frame(height: 44)
                            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.ink))
                    }
                    .buttonStyle(SquishStyle())
                }
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 26, style: .continuous).fill(Theme.paper))
                .overlay(RoundedRectangle(cornerRadius: 26, style: .continuous).strokeBorder(Theme.pill, lineWidth: 2))

                if let note {
                    Text(note).font(Theme.mono(12)).foregroundStyle(Theme.secondary)
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, 110)
        }
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
        }
        .padding(12)
        .background(ToyBlock(color: Theme.greyBlue, cornerRadius: 26))
    }
}
