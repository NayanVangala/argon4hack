import MWDATCore
import SwiftUI

/// App entry. Wearables.configure() runs exactly once here, before any view
/// touches the SDK (CameraAccess sample pattern).
@main
struct SceneBridgeApp: App {
    @StateObject private var wearables = WearablesViewModel()

    init() {
        do {
            try Wearables.configure()
        } catch {
            assertionFailure("Failed to configure Wearables SDK: \(error)")
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(wearables)
                .onOpenURL { url in
                    // Meta AI registration callback. Only forward Meta Wearables URLs.
                    guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
                          components.queryItems?.contains(where: { $0.name == "metaWearablesAction" }) == true else {
                        return
                    }
                    wearables.handleCallbackURL(url)
                }
        }
    }
}
