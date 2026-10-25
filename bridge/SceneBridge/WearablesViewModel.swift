import Foundation
import MWDATCore

/// Owns DAT registration, device discovery, and camera permission.
/// API verified against the DAT iOS SDK 1.0.1 swiftinterface:
/// Wearables.configure() (in App init), startRegistration/startUnregistration
/// (async throws), handleUrl, registrationStateStream(),
/// devicesStream() (yields [DeviceIdentifier], resolved via deviceForIdentifier),
/// checkPermissionStatus(.camera) / requestPermission(.camera).
/// Registration-state enum cases are intentionally NOT named here: the view
/// model publishes a description string so a renamed case cannot break the UI.
@MainActor
final class WearablesViewModel: ObservableObject {
    @Published var registrationStateDescription = "Unknown"
    @Published var devices: [Device] = []
    @Published var cameraPermission: PermissionStatus = .denied
    @Published var lastError: String?

    private let wearables = Wearables.shared
    private var observationTasks: [Task<Void, Never>] = []

    init() {
        startObserving()
    }

    private func startObserving() {
        observationTasks.append(Task {
            for await state in wearables.registrationStateStream() {
                self.registrationStateDescription = String(describing: state)
            }
        })
        observationTasks.append(Task {
            for await found in wearables.devicesStream() {
                // 1.0.1: devicesStream yields [DeviceIdentifier], not
                // [Device]. Resolve each identifier to its Device object.
                self.devices = found.compactMap { wearables.deviceForIdentifier($0) }
            }
        })
    }

    func register() {
        // 1.0.1: startRegistration is async throws.
        Task {
            do {
                try await wearables.startRegistration()
            } catch {
                lastError = "Registration failed: \(error)"
            }
        }
    }

    func unregister() {
        // 1.0.1: startUnregistration is async throws.
        Task {
            do {
                try await wearables.startUnregistration()
            } catch {
                lastError = "Unregistration failed: \(error)"
            }
        }
    }

    func handleCallbackURL(_ url: URL) {
        Task {
            do {
                _ = try await wearables.handleUrl(url)
            } catch {
                lastError = "Callback failed: \(error)"
            }
        }
    }

    func refreshCameraPermission() {
        Task {
            do {
                cameraPermission = try await wearables.checkPermissionStatus(.camera)
            } catch {
                lastError = "Permission check failed: \(error)"
            }
        }
    }

    func requestCameraPermission() {
        Task {
            do {
                cameraPermission = try await wearables.requestPermission(.camera)
            } catch {
                lastError = "Permission request failed: \(error)"
            }
        }
    }

}
