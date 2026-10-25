import Foundation

/// Response shapes from SCENE-API-CONTRACT.md. Field-for-field with the contract.
struct SessionResponse: Decodable {
    let id: String
    let startedAt: String
    let status: String
    let wsUrl: String?

    enum CodingKeys: String, CodingKey {
        case id, status
        case startedAt = "started_at"
        case wsUrl = "ws_url"
    }
}

struct EndSessionResponse: Decodable {
    let id: String
    let endedAt: String?
    let status: String
    let sceneCount: Int?

    enum CodingKeys: String, CodingKey {
        case id, status
        case endedAt = "ended_at"
        case sceneCount = "scene_count"
    }
}

struct ChunkResponse: Decodable {
    let chunkId: String
    let sessionId: String
    let startTs: String
    let endTs: String
    let status: String

    enum CodingKeys: String, CodingKey {
        case chunkId = "chunk_id"
        case sessionId = "session_id"
        case startTs = "start_ts"
        case endTs = "end_ts"
        case status
    }
}

struct APIErrorResponse: Decodable {
    struct Detail: Decodable {
        let code: String
        let message: String
    }
    let error: Detail
}

enum APIError: Error, LocalizedError {
    case invalidURL
    case httpStatus(Int, String)
    case decoding(Error)
    case unauthorized
    /// Upload failed AND the offline buffer also failed, so the chunk is lost.
    /// Distinct from a plain upload failure, where the chunk is safely buffered.
    case bufferFailed(Error)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid API URL"
        case .httpStatus(let code, let msg): return "HTTP \(code): \(msg)"
        case .decoding(let e): return "Decode failed: \(e)"
        case .unauthorized: return "Token expired (401). Re-pair."
        case .bufferFailed(let e): return "Could not buffer chunk offline: \(e)"
        }
    }
}

/// One finished 30s window, ready to upload.
struct ChunkFiles {
    let videoURL: URL
    let audioURL: URL
    let start: Date
    let end: Date
}
