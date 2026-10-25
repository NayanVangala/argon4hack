import MWDATCore
import SwiftUI

/// Flow: registration -> camera permission -> device list -> live stream.
/// Devices only appear after registration AND camera permission are granted.
struct ContentView: View {
    @EnvironmentObject var wearables: WearablesViewModel
    @State private var selectedDevice: Device?
    @State private var showStream = false

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                Text("Scene Bridge")
                    .font(.largeTitle.bold())

                VStack(alignment: .leading, spacing: 8) {
                    Text("Registration: \(wearables.registrationStateDescription)")
                        .font(.subheadline)
                    HStack {
                        Button("Register glasses") { wearables.register() }
                            .buttonStyle(.borderedProminent)
                        Button("Unregister") { wearables.unregister() }
                            .buttonStyle(.bordered)
                    }
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("Camera permission: \(String(describing: wearables.cameraPermission))")
                        .font(.subheadline)
                    HStack {
                        Button("Check") { wearables.refreshCameraPermission() }
                            .buttonStyle(.bordered)
                        Button("Request") { wearables.requestCameraPermission() }
                            .buttonStyle(.bordered)
                    }
                }

                Divider()

                Text("Glasses").font(.headline)
                if wearables.devices.isEmpty {
                    Text("No glasses found yet. Register, grant camera permission, and make sure the Meta AI app is force-quit (it fights the bridge over the same Bluetooth channel).")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                } else {
                    List(wearables.devices.indices, id: \.self) { index in
                        let device = wearables.devices[index]
                        Button {
                            selectedDevice = device
                            showStream = true
                        } label: {
                            VStack(alignment: .leading) {
                                Text(device.nameOrId()).font(.headline)
                                Text(String(describing: device.deviceType()))
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .listStyle(.plain)
                }

                if let error = wearables.lastError {
                    Text(error).font(.subheadline).foregroundStyle(.red)
                }
                Spacer()
            }
            .padding()
            .navigationDestination(isPresented: $showStream) {
                if let device = selectedDevice {
                    StreamView(device: device)
                }
            }
            .onAppear {
                wearables.refreshCameraPermission()
                Task { await APIClient().flushPending() }
            }
        }
    }
}
