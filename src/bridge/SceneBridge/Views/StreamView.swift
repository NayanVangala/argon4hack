import MWDATCore
import SwiftUI

/// Live preview + record + session controls for one pair of glasses.
struct StreamView: View {
    let device: Device
    @StateObject private var stream = StreamViewModel()

    var body: some View {
        VStack(spacing: 16) {
            ZStack {
                RoundedRectangle(cornerRadius: 16)
                    .fill(Color.black)
                    .aspectRatio(4.0 / 3.0, contentMode: .fit)
                if let frame = stream.currentFrame {
                    Image(uiImage: frame)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                } else {
                    Text("No frame yet")
                        .foregroundStyle(.white)
                }
            }

            Text("Glasses: \(device.nameOrId())")
                .font(.headline)
            Text("Stream: \(stream.streamStateDescription)")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            HStack {
                Button(stream.isStreaming ? "Stop stream" : "Start stream") {
                    stream.isStreaming ? stream.stopStream() : stream.startStream()
                }
                .buttonStyle(.borderedProminent)

                Button(stream.isRecording ? "Stop recording" : "Record") {
                    stream.toggleRecording()
                }
                .buttonStyle(.bordered)
                .disabled(!stream.isStreaming)
                .tint(stream.isRecording ? .red : nil)
            }

            HStack {
                Button("Start session") { stream.startSession() }
                    .buttonStyle(.bordered)
                    .disabled(stream.sessionId != nil)
                Button("End session") { stream.endSession() }
                    .buttonStyle(.bordered)
                    .disabled(stream.sessionId == nil)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text("Chunks uploaded: \(stream.chunkCount)")
                Text(stream.uploadStatus)
            }
            .font(.subheadline)
            .foregroundStyle(.secondary)

            if let error = stream.lastError {
                Text(error).font(.subheadline).foregroundStyle(.red)
            }
            Spacer()
        }
        .padding()
        .navigationTitle("Live")
        .onDisappear { stream.stopStream() }
    }
}
