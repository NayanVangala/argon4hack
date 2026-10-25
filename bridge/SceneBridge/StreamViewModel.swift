import Foundation
import MWDATCamera
import MWDATCore
import UIKit

/// Owns the live camera stream, 30s chunking, and upload.
/// Stream pattern verified from the CameraAccess sample: StreamSession with a
/// config + device selector, videoFramePublisher + makeUIImage(),
/// statePublisher, start()/stop(). Exact StreamSession initializer and config
/// members are marked VERIFY — confirm against the sample before first build.
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
    private var streamSession: StreamSession?
    private var frameListenerToken: Any?
    private var stateListenerToken: Any?
    private var recordTask: Task<Void, Never>?

    // MARK: - Stream

    func startStream() {
        guard !isStreaming else { return }
        // VERIFY: StreamSession initializer + StreamSessionConfig members
        // (codec, resolution, framerate) against samples/CameraAccess.
        let config = StreamSessionConfig()
        let selector = AutoDeviceSelector(wearables: Wearables.shared)
        let session = StreamSession(config: config, deviceSelector: selector)
        self.streamSession = session

        frameListenerToken = session.videoFramePublisher.listen { [weak self] videoFrame in
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
        // VERIFY: statePublisher event type. Stored as description so a renamed
        // case cannot break the UI.
        stateListenerToken = session.statePublisher.listen { [weak self] state in
            Task { @MainActor [weak self] in
                self?.streamStateDescription = String(describing: state)
            }
        }
        session.start()
        isStreaming = true
    }

    func stopStream() {
        Task { await stopRecording() }
        streamSession?.stop()
        streamSession = nil
        frameListenerToken = nil
        stateListenerToken = nil
        isStreaming = false
        streamStateDescription = "Stopped"
    }

    // MARK: - Audio (PCM via Camera Stream, experimental per DAT README)

    /// VERIFY: audio frame publisher name in MWDATCamera. Wire the SDK's PCM
    /// buffers into this method; ChunkWriter already accepts them.
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
