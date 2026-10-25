import Foundation

/// Talks to the Scene backend. Shapes match SCENE-API-CONTRACT.md exactly.
/// Upload rule: try once, retry once, then buffer to disk for a later flush.
final class APIClient {
    private let session = URLSession.shared
    private let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private func request(path: String) throws -> URLRequest {
        guard let url = URL(string: path, relativeTo: Config.baseURL) else {
            throw APIError.invalidURL
        }
        var req = URLRequest(url: url)
        req.setValue("Bearer \(Config.bearerToken)", forHTTPHeaderField: "Authorization")
        return req
    }

    private func decode<T: Decodable>(_ data: Data, _ response: URLResponse) throws -> T {
        guard let http = response as? HTTPURLResponse else {
            throw APIError.httpStatus(-1, "No HTTP response")
        }
        if http.statusCode == 401 { throw APIError.unauthorized }
        guard (200..<300).contains(http.statusCode) else {
            if let apiErr = try? JSONDecoder().decode(APIErrorResponse.self, from: data) {
                throw APIError.httpStatus(http.statusCode, apiErr.error.message)
            }
            throw APIError.httpStatus(http.statusCode, HTTPURLResponse.localizedString(forStatusCode: http.statusCode))
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }

    /// POST /sessions — empty body, device identified by token.
    func startSession() async throws -> SessionResponse {
        var req = try request(path: "sessions")
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = Data("{}".utf8)
        let (data, response) = try await session.data(for: req)
        return try decode(data, response)
    }

    /// POST /sessions/{id}/end
    func endSession(id: String) async throws -> EndSessionResponse {
        var req = try request(path: "sessions/\(id)/end")
        req.httpMethod = "POST"
        let (data, response) = try await session.data(for: req)
        return try decode(data, response)
    }

    /// POST /chunks — multipart: video (mp4), audio (wav), session_id, start_ts, end_ts.
    /// Retries once, then buffers the files to disk and rethrows.
    /// A 401 is never retried or buffered: the token is expired, so the chunk
    /// would just retry a dead token forever. It throws immediately so the UI
    /// can surface "re-pair".
    func uploadChunk(_ chunk: ChunkFiles, sessionId: String) async throws -> ChunkResponse {
        var lastError: Error?
        for _ in 0...Config.uploadRetryCount {
            do {
                return try await uploadChunkOnce(chunk, sessionId: sessionId)
            } catch APIError.unauthorized {
                throw APIError.unauthorized
            } catch {
                lastError = error
            }
        }
        do {
            try PendingUploadStore.shared.buffer(chunk: chunk, sessionId: sessionId)
        } catch {
            throw APIError.bufferFailed(error)
        }
        throw lastError ?? APIError.httpStatus(-1, "Upload failed")
    }

    private func uploadChunkOnce(_ chunk: ChunkFiles, sessionId: String) async throws -> ChunkResponse {
        let boundary = "SceneBoundary-\(UUID().uuidString)"
        var req = try request(path: "chunks")
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        func field(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
            body.append("\(value)\r\n".data(using: .utf8)!)
        }
        func file(_ name: String, filename: String, mime: String, url: URL) throws {
            let data = try Data(contentsOf: url)
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n\r\n".data(using: .utf8)!)
            body.append("Content-Type: \(mime)\r\n\r\n".data(using: .utf8)!)
            body.append(data)
            body.append("\r\n".data(using: .utf8)!)
        }
        field("session_id", sessionId)
        field("start_ts", iso.string(from: chunk.start))
        field("end_ts", iso.string(from: chunk.end))
        try file("video", filename: "chunk.mp4", mime: "video/mp4", url: chunk.videoURL)
        try file("audio", filename: "chunk.wav", mime: "audio/wav", url: chunk.audioURL)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        req.httpBody = body

        let (data, response) = try await session.data(for: req)
        return try decode(data, response)
    }

    /// Flush buffered chunks from earlier failed uploads. Call on launch + session start.
    /// Items whose files are gone are dropped, not retried forever. On a 401 the
    /// token is dead, so flushing stops at once; items stay buffered for after
    /// re-pair instead of hammering an expired token.
    func flushPending() async -> Int {
        let pending = PendingUploadStore.shared.list()
        var flushed = 0
        for item in pending {
            guard FileManager.default.fileExists(atPath: item.videoURL.path),
                  FileManager.default.fileExists(atPath: item.audioURL.path) else {
                PendingUploadStore.shared.remove(item)
                continue
            }
            do {
                let chunk = ChunkFiles(videoURL: item.videoURL, audioURL: item.audioURL,
                                       start: item.start, end: item.end)
                _ = try await uploadChunkOnce(chunk, sessionId: item.sessionId)
                PendingUploadStore.shared.remove(item)
                flushed += 1
            } catch APIError.unauthorized {
                break
            } catch {
                // Leave it buffered; next flush retries.
                continue
            }
        }
        return flushed
    }
}

/// On-disk buffer for chunks whose upload failed. Manifest is JSON in the app's
/// caches directory; chunk files live alongside it.
final class PendingUploadStore {
    static let shared = PendingUploadStore()

    /// Session id used for chunks recorded before any session exists. These are
    /// reassigned to the real session id on startSession, before flushing,
    /// because the server rejects a non-UUID session id and they would
    /// otherwise stay buffered and retry forever.
    static let unassignedSessionId = "unassigned"

    struct Item: Codable {
        let videoURL: URL
        let audioURL: URL
        let sessionId: String
        let start: Date
        let end: Date
    }

    private var dir: URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(Config.pendingUploadsDirectoryName)
    }

    private var manifestURL: URL { dir.appendingPathComponent("manifest.json") }

    private init() { try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true) }

    func buffer(chunk: ChunkFiles, sessionId: String) throws {
        var items = list()
        let videoDest = dir.appendingPathComponent("video-\(UUID().uuidString).mp4")
        let audioDest = dir.appendingPathComponent("audio-\(UUID().uuidString).wav")
        try FileManager.default.copyItem(at: chunk.videoURL, to: videoDest)
        try FileManager.default.copyItem(at: chunk.audioURL, to: audioDest)
        items.append(Item(videoURL: videoDest, audioURL: audioDest,
                          sessionId: sessionId, start: chunk.start, end: chunk.end))
        try save(items)
    }

    /// Reassigns chunks buffered before a session existed ("unassigned") to
    /// the new session id. Call on startSession, before flushPending.
    func reassignUnassigned(to newId: String) {
        let items = list().map { item in
            item.sessionId == Self.unassignedSessionId
                ? Item(videoURL: item.videoURL, audioURL: item.audioURL,
                       sessionId: newId, start: item.start, end: item.end)
                : item
        }
        try? save(items)
    }

    /// Atomic manifest write: a kill mid-write leaves the old manifest intact
    /// instead of corrupting it and orphaning every buffered chunk.
    private func save(_ items: [Item]) throws {
        try JSONEncoder().encode(items).write(to: manifestURL, options: .atomic)
    }

    func list() -> [Item] {
        guard let data = try? Data(contentsOf: manifestURL),
              let items = try? JSONDecoder().decode([Item].self, from: data) else { return [] }
        return items
    }

    func remove(_ item: Item) {
        try? FileManager.default.removeItem(at: item.videoURL)
        try? FileManager.default.removeItem(at: item.audioURL)
        let items = list().filter { $0.videoURL != item.videoURL }
        try? save(items)
    }
}
