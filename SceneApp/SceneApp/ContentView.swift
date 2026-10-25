import SwiftUI

struct ContentView: View {
    @State private var store = AppStore()
    @State private var tab: AppTab = .memory

    var body: some View {
        ZStack(alignment: .bottom) {
            Group {
                switch tab {
                case .live: LiveView()
                case .memory: MemoryView(tab: $tab)
                case .ask: AskView()
                case .people: PeopleView()
                case .session: SessionView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            NavPill(tab: $tab)
                .padding(.horizontal, 20)
                .padding(.bottom, 8)
        }
        .background(Theme.paper.ignoresSafeArea())
        .environment(store)
        // App is designed light; Live is dark so its status bar turns white
        .preferredColorScheme(tab == .live ? .dark : .light)
        .task { await store.loadToday() }
    }
}

#Preview {
    ContentView()
}
