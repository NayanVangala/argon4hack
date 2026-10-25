import Foundation
import MWDATCore

/// Owns DAT registration, device discovery, and camera permission.
/// API verified against the official DAT docs + integration cookbook:
/// Wearables.configure() (in App init), startRegistration/startUnregistration
/// (throwing), handleUrl, registrationStateStream(), devicesStream(),
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
                self.devices = found
            }
        })
    }

    func register() {
        do {
            try wearables.startRegistration()
        } catch {
            lastError = "Registration failed: \(error)"
        }
    }

    func unregister() {
        do {
            try wearables.startUnregistration()
        } catch {
            lastError = "Unregistration failed: \(error)"
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

    /// Starts a device session for link management.
    /// VERIFY: whether StreamSession needs this device session or manages its
    /// own link. The CameraAccess sample creates StreamSession with an
    /// AutoDeviceSelector directly; this session exists so link state is
    /// observable even when not streaming.
    func startDeviceSession() {
        Task {
            do {
                let selector = AutoDeviceSelector(wearables: wearables)
                let session = try wearables.createSession(deviceSelector: selector)
                try session.start()
                for await state in session.stateStream() {
                    print("Device session state: \(state)")
                }
            } catch {
                lastError = "Device session failed: \(error)"
            }
        }
    }

}
