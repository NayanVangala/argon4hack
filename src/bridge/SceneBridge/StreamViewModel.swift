import AVFoundation
import Foundation
import MWDATCamera
import MWDATCore
import UIKit

/// Owns the live camera stream, 30s chunking, and upload.
/// Streaming model verified against the DAT iOS SDK 1.0.1 swiftinterface
/// (2026-10-25): Wearables.shared.createSession(deviceSelector:) throws,
/// DeviceSession.start() throws, addCamera(config:) throws and returns an
/// optional Camera, Camera.stream exposes videoFramePublisher,
/// audioFramePublisher, statePublisher, start() and stop().
/// Config: .raw video + in-stream PCM 16kHz mono, medium resolution
/// (504x896), 24fps. Audio arrives as AVAudioPCMBuffer, converted to Data
/// before ChunkWriter. The old StreamSession model does not exist in 1.0.1.
@MainActor
final class StreamViewModel: ObservableObject {
    @Published var currentFrame: UIImage?
    @Published var isStreaming = false
    @Published var isRecording = false
    @Published var streamStateDescription = "Idle"
    @Published var chunkCount = 0
    @Published var uploadStatus = "Idle"
    @Published var sessionId: String?
    @Published var lastError: String?

    private let api = APIClient()
    private let chunkWriter = ChunkWriter()
    private var deviceSession: DeviceSession?
    private var cameraStream: MWDATCamera.Stream?
    private var videoListenerToken: (any AnyListenerToken)?
    private var audioListenerToken: (any AnyListenerToken)?
    private var stateListenerToken: (any AnyListenerToken)?
    private var recordTask: Task<Void, Never>?
    private var isStartingStream = false
    private var lastSessionStop: Date?

    // MARK: - Stream

    /// .raw video + in-stream PCM 16kHz mono, medium (504x896), 24fps.
    /// BTC ceiling per the DAT issue sweep: 504x896 at 24fps ran ~8 min clean.
    private var streamConfig: StreamConfiguration {
        StreamConfiguration(
            videoCodec: .raw,
            audioCodec: .pcm(sampleRate: .rate16000, numberOfChannels: 1),
            resolution: .medium,
            frameRate: 24
        )
    }

    /// Polls the device session until it reaches .started, 10s bound.
    /// DeviceSessionState has .started; StreamState does not (it has
    /// .streaming), so the session wait and the stream state are separate.
    private func waitForSessionStarted(_ session: DeviceSession) async -> Bool {
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            if session.state == .started { return true }
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
        return session.state == .started
    }

    func startStream() {
        guard !isStreaming else { return }
        guard !isStartingStream else { return }
        isStartingStream = true
        Task {
            do {
                // Session hygiene: >=2s gap between teardown and the next
                // createSession, else the glasses can refuse with
                // sessionAlreadyExists.
                if let lastStop = lastSessionStop {
                    let elapsed = Date().timeIntervalSince(lastStop)
                    if elapsed < 2.0 {
                        try? await Task.sleep(nanoseconds: UInt64((2.0 - elapsed) * 1_000_000_000))
                    }
                }
                let selector = AutoDeviceSelector(wearables: Wearables.shared)
                let session = try Wearables.shared.createSession(deviceSelector: selector)
                self.deviceSession = session
                try session.start()
                guard await waitForSessionStarted(session) else {
                    lastError = "Session did not reach started state in 10s"
                    session.stop()
                    self.deviceSession = nil
                    self.isStartingStream = false
                    return
                }
                guard let camera = try session.addCamera(config: streamConfig) else {
                    lastError = "addCamera returned nil"
                    session.stop()
                    self.deviceSession = nil
                    self.isStartingStream = false
                    return
                }
                let stream = camera.stream
                self.cameraStream = stream
                // Subscribe BEFORE start so no early frames are missed.
                videoListenerToken = stream.videoFramePublisher.listen { [weak self] videoFrame in
                    Task { @MainActor [weak self] in
                        guard let self else { return }
                        if let image = videoFrame.makeUIImage() {
                            self.currentFrame = image
                            if self.isRecording {
                                self.chunkWriter.appendVideoFrame(image, at: Date())
                            }
                        }
                    }
                }
                audioListenerToken = stream.audioFramePublisher.listen { [weak self] audioFrame in
                    Task { @MainActor [weak self] in
                        guard let self else { return }
                        guard self.isRecording else { return }
                        if let data = self.pcmData(from: audioFrame.pcmBuffer) {
                            self.ingestAudioPCM(data)
                        }
                    }
                }
                // Stored as description so a renamed case cannot break the UI.
                stateListenerToken = stream.statePublisher.listen { [weak self] state in
                    Task { @MainActor [weak self] in
                        self?.streamStateDescription = String(describing: state)
                    }
                }
                stream.start()
                isStreaming = true
                isStartingStream = false
            } catch {
                lastError = "Start stream failed: \(error)"
                deviceSession?.stop()
                deviceSession = nil
                cameraStream = nil
                videoListenerToken = nil
                audioListenerToken = nil
                stateListenerToken = nil
                isStartingStream = false
            }
        }
    }

    func stopStream() {
        Task { await stopRecording() }
        // Listener tokens require explicit async cancel(); nil-ing alone
        // can leak the subscription and duplicate frames on restart.
        Task {
            await videoListenerToken?.cancel()
            await audioListenerToken?.cancel()
            await stateListenerToken?.cancel()
            videoListenerToken = nil
            audioListenerToken = nil
            stateListenerToken = nil
            cameraStream?.stop()
            deviceSession?.stop()
            cameraStream = nil
            deviceSession = nil
            isStreaming = false
            isStartingStream = false
            streamStateDescription = "Stopped"
            lastSessionStop = Date()
        }
    }

    // MARK: - Audio (in-stream PCM via Camera Stream, 16kHz mono)

    /// ChunkWriter takes Data; the SDK delivers AVAudioPCMBuffer. Converts
    /// int16 directly, float32 by clamping to int16. Mono expected (the
    /// config requests 1 channel), so only channel 0 is read.
    private func pcmData(from buffer: AVAudioPCMBuffer) -> Data? {
        let frameLength = Int(buffer.frameLength)
        guard frameLength > 0 else { return nil }
        if let int16 = buffer.int16ChannelData {
            return Data(bytes: int16[0], count: frameLength * MemoryLayout<Int16>.size)
        }
        if let float = buffer.floatChannelData {
            let src = float[0]
            var out = Data(capacity: frameLength * 2)
            for i in 0..<frameLength {
                let clamped = max(-1.0, min(1.0, src[i]))
                var sample = Int16(clamped * Float(Int16.max))
                out.append(Data(bytes: &sample, count: 2))
            }
            return out
        }
        return nil
    }

    func ingestAudioPCM(_ data: Data) {
        if isRecording {
            chunkWriter.appendAudioPCM(data)
        }
    }

    // MARK: - Session control (API contract)

    func startSession() {
        Task {
            do {
                let response = try await api.startSession()
                // Reassign pre-session chunks before flushing: flush uploads
                // verbatim, and the server rejects the "unassigned" placeholder.
                PendingUploadStore.shared.reassignUnassigned(to: response.id)
                _ = await api.flushPending()
                sessionId = response.id
                uploadStatus = "Session \(response.id.prefix(8)) live"
            } catch {
                lastError = "Start session failed: \(error)"
            }
        }
    }

    func endSession() {
        guard let id = sessionId else { return }
        Task {
            // Stop recording FIRST and await the final window upload, before
            // POSTing /end. Ending mid-recording used to nil sessionId while
            // chunks were still coming, stranding them as "unassigned".
            await stopRecording()
            do {
                let response = try await api.endSession(id: id)
                uploadStatus = "Session ended: \(response.sceneCount ?? 0) scenes"
                sessionId = nil
            } catch {
                lastError = "End session failed: \(error)"
            }
        }
    }

    // MARK: - Recording: 30s windows -> upload

    func toggleRecording() {
        if isRecording {
            Task { await stopRecording() }
        } else {
            startRecording()
        }
    }

    private func startRecording() {
        guard isStreaming else {
            lastError = "Start the stream before recording."
            return
        }
        isRecording = true
        chunkWriter.startWindow(at: Date())
        recordTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(Config.chunkDurationSeconds * 1_000_000_000))
                if Task.isCancelled { break }
                await self.closeWindow()
            }
        }
    }

    private func stopRecording() async {
        recordTask?.cancel()
        recordTask = nil
        isRecording = false
        // Serialized close (see closeWindow): awaits an in-flight loop close
        // if one is running, then closes anything accumulated since.
        await closeWindow()
    }

    /// Serialized window close. The 30s loop and stopRecording can both call
    /// this, and @MainActor alone does not serialize across awaits: the old
    /// code let a loop close and a stop close run concurrently and drop
    /// frames in the gap. Closes chain FIFO via closeTail, so every caller
    /// eventually runs exactly one close, in order.
    private var closeTail: Task<Void, Never>?
    private var closeTailID = 0

    private func closeWindow() async {
        let previous = closeTail
        closeTailID += 1
        let myID = closeTailID
        let task = Task<Void, Never> {
            await previous?.value
            await self.performCloseWindow()
        }
        closeTail = task
        await task.value
        if closeTailID == myID {
            // No newer close chained after us; safe to clear the tail.
            closeTail = nil
        }
    }

    private func performCloseWindow() async {
        let chunk: ChunkFiles?
        do {
            chunk = try await chunkWriter.finishWindow(end: Date())
        } catch {
            // Encode failure is distinct from an empty window: surface it
            // instead of silently discarding the window as "no frames".
            lastError = "Chunk encode failed: \(error)"
            return
        }
        guard let chunk = chunk else {
            // Empty window: nothing to send. No startWindow call here: the
            // next append auto-starts a window, so frames arriving during an
            // upload are kept instead of being wiped by a restart.
            return
        }
        guard let id = sessionId else {
            // No session yet: buffer locally, reassigned + flushed on session
            // start. A buffer failure here is reported distinctly.
            do {
                try PendingUploadStore.shared.buffer(chunk: chunk, sessionId: PendingUploadStore.unassignedSessionId)
            } catch {
                uploadStatus = "Chunk lost: could not buffer"
                lastError = "Buffer failed for pre-session chunk: \(error)"
            }
            return
        }
        do {
            let response = try await api.uploadChunk(chunk, sessionId: id)
            chunkCount += 1
            uploadStatus = "Chunk \(response.chunkId.prefix(8)) received"
        } catch APIError.bufferFailed(let underlying) {
            // Upload failed AND buffering failed: the chunk is lost, not
            // "buffered offline".
            uploadStatus = "Chunk lost: could not buffer"
            lastError = "Upload failed, buffer failed: \(underlying)"
        } catch {
            uploadStatus = "Chunk buffered offline"
            lastError = "Upload failed (buffered): \(error)"
        }
    }
}
