import AVFoundation
import UIKit

/// Collects DAT stream output for one 30s window and writes contract-shaped files:
/// video.mp4 + audio.wav. Recording itself is continuous; this only slices windows.
///
/// DAT delivers video frames as UIImages (videoFramePublisher) and audio as PCM
/// buffers through the Camera Stream (experimental, per the DAT README).
/// Muxing is AVAssetWriter-based. Anything about the exact DAT pixel/PCM format
/// that is not in the official docs is marked VERIFY below.

/// Thrown by finishWindow when a window has frames but writing its files fails.
/// Distinct from an empty window, which returns nil instead of throwing, so a
/// failed encode is never silently mistaken for "nothing to send".
enum ChunkWriterError: Error {
    case encodeFailed(String)
}

final class ChunkWriter {
    private struct Frame {
        let image: UIImage
        let time: Date
    }

    private var frames: [Frame] = []
    private var pcm = Data()
    private var windowStart: Date?
    private let lock = NSLock()

    /// Ingest cap: keep at most one frame per interval (~5fps). A 30s window
    /// at full DAT framerate holds hundreds of full-res images and risks
    /// jetsam; 5fps is plenty for scene understanding. This caps chunk ingest
    /// only; the live preview in StreamViewModel still shows every frame.
    private static let minFrameInterval: TimeInterval = 0.2
    private var lastKeptFrameTime: Date?

    /// VERIFY: DAT PCM sample rate + channel count. The DAT README only says
    /// "synchronized PCM audio through Camera Stream". 16kHz mono is the scaffold
    /// default; confirm against the SDK and change these two constants if wrong.
    static let pcmSampleRate = 16000
    static let pcmChannels = 1

    func startWindow(at date: Date) {
        lock.lock(); defer { lock.unlock() }
        windowStart = date
        frames.removeAll()
        pcm.removeAll()
        lastKeptFrameTime = nil
    }

    func appendVideoFrame(_ image: UIImage, at date: Date) {
        lock.lock(); defer { lock.unlock() }
        if windowStart == nil { windowStart = date }
        if let last = lastKeptFrameTime, date.timeIntervalSince(last) < Self.minFrameInterval {
            return // over the ingest cap; drop, do not buffer
        }
        lastKeptFrameTime = date
        frames.append(Frame(image: image, time: date))
    }

    func appendAudioPCM(_ data: Data) {
        lock.lock(); defer { lock.unlock() }
        pcm.append(data)
    }

    /// Closes the current window and writes chunk files to a temp directory.
    /// Returns nil if the window has no frames (nothing to send).
    /// Throws ChunkWriterError.encodeFailed if writing fails, so a failed
    /// encode is surfaced instead of being mistaken for an empty window.
    /// Encoding runs on a detached task, never on the caller's actor: the old
    /// code ran the AVAssetWriter sleep loop and semaphore wait on @MainActor
    /// and froze the UI at every 30s chunk close.
    func finishWindow(end: Date) async throws -> ChunkFiles? {
        lock.lock()
        let start = windowStart ?? end
        let capturedFrames = frames
        let capturedPCM = pcm
        frames.removeAll()
        pcm.removeAll()
        windowStart = nil
        lock.unlock()

        guard !capturedFrames.isEmpty else { return nil }
        return try await Task.detached {
            let dir = FileManager.default.temporaryDirectory
                .appendingPathComponent("scene-chunk-\(UUID().uuidString)")
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let videoURL = dir.appendingPathComponent("chunk.mp4")
            let audioURL = dir.appendingPathComponent("chunk.wav")
            guard Self.writeMP4(frames: capturedFrames, to: videoURL) else {
                throw ChunkWriterError.encodeFailed("mp4")
            }
            guard Self.writeWAV(pcm: capturedPCM, to: audioURL) else {
                throw ChunkWriterError.encodeFailed("wav")
            }
            return ChunkFiles(videoURL: videoURL, audioURL: audioURL, start: start, end: end)
        }.value
    }

    // MARK: - MP4 via AVAssetWriter

    private static func writeMP4(frames: [Frame], to url: URL) -> Bool {
        guard let firstImage = frames.first?.image,
              let cgImage = firstImage.cgImage else { return false }
        let width = cgImage.width
        let height = cgImage.height

        guard let writer = try? AVAssetWriter(outputURL: url, fileType: .mp4) else { return false }
        let settings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height
        ]
        let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
        input.expectsMediaDataInRealTime = false
        // VERIFY: pixel format the DAT frame pipeline expects downstream.
        // BGRA is the standard AVAssetWriterInputPixelBufferAdaptor format.
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height
            ])
        guard writer.canAdd(input) else { return false }
        writer.add(input)
        writer.startWriting()
        writer.startSession(atSourceTime: .zero)

        let startTime = frames.first?.time ?? Date()
        var ok = true
        for (index, frame) in frames.enumerated() {
            // VERIFY: nominal frame pacing. DAT streams at the session framerate;
            // using wall-clock deltas here keeps the scaffold honest without
            // assuming a fixed fps the SDK did not promise.
            let seconds = frame.time.timeIntervalSince(startTime)
            let pts = CMTime(seconds: seconds, preferredTimescale: 600)
            guard let pixelBuffer = pixelBuffer(from: frame.image, width: width, height: height) else {
                ok = false; break
            }
            while !input.isReadyForMoreMediaData {
                Thread.sleep(forTimeInterval: 0.005)
            }
            if !adaptor.append(pixelBuffer, withPresentationTime: pts) { ok = false; break }
            _ = index
        }
        input.markAsFinished()
        let semaphore = DispatchSemaphore(value: 0)
        writer.finishWriting { semaphore.signal() }
        semaphore.wait()
        return ok && writer.status == .completed
    }

    private static func pixelBuffer(from image: UIImage, width: Int, height: Int) -> CVPixelBuffer? {
        guard let cgImage = image.cgImage else { return nil }
        var buffer: CVPixelBuffer?
        let attrs: [String: Any] = [
            kCVPixelBufferCGImageCompatibilityKey as String: true,
            kCVPixelBufferCGBitmapContextCompatibilityKey as String: true
        ]
        guard CVPixelBufferCreate(kCFAllocatorDefault, width, height,
                                  kCVPixelFormatType_32BGRA, attrs as CFDictionary,
                                  &buffer) == kCVReturnSuccess,
              let px = buffer else { return nil }
        CVPixelBufferLockBaseAddress(px, [])
        defer { CVPixelBufferUnlockBaseAddress(px, []) }
        guard let ctx = CGContext(data: CVPixelBufferGetBaseAddress(px),
                                  width: width, height: height, bitsPerComponent: 8,
                                  bytesPerRow: CVPixelBufferGetBytesPerRow(px),
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue) else { return nil }
        ctx.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))
        return px
    }

    // MARK: - WAV (16-bit PCM, manual header)

    private static func writeWAV(pcm: Data, to url: URL) -> Bool {
        var header = Data()
        func u32(_ v: UInt32) { var x = v.littleEndian; header.append(Data(bytes: &x, count: 4)) }
        func u16(_ v: UInt16) { var x = v.littleEndian; header.append(Data(bytes: &x, count: 2)) }
        func str(_ s: String) { header.append(s.data(using: .ascii)!) }
        let bytesPerSample = 2
        let byteRate = Self.pcmSampleRate * Self.pcmChannels * bytesPerSample
        str("RIFF"); u32(UInt32(36 + pcm.count)); str("WAVE")
        str("fmt "); u32(16); u16(1)
        u16(UInt16(Self.pcmChannels)); u32(UInt32(Self.pcmSampleRate))
        u32(UInt32(byteRate)); u16(UInt16(Self.pcmChannels * bytesPerSample)); u16(16)
        str("data"); u32(UInt32(pcm.count))
        do {
            try (header + pcm).write(to: url)
            return true
        } catch {
            return false
        }
    }
}
