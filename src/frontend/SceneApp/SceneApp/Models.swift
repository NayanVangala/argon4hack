import Foundation

// Shapes match the API contract in the spec (§4.5). Keys arrive in snake_case.

nonisolated enum Confidence: String, Sendable {
    case verified, review, silence, unknown
}

nonisolated struct SceneItem: Identifiable, Codable, Hashable {
    let id: String
    let startTs: Date
    let endTs: Date
    let summary: String
    var quote: String?
    var thumbUrl: String?
    var type: String
    var verified: Bool
    // Not in the API yet (asked Nayan): confidence + speaker
    var confidence: String?
    var speaker: String?

    var displayConfidence: Confidence {
        if let c = confidence, let parsed = Confidence(rawValue: c.lowercased()) { return parsed }
        // Scene fallback only: `verified` is a real server field on SceneSummary,
        // not an invented default. (Receipts have no such field, so Receipt
        // defaults to .review instead. See Receipt.displayConfidence.)
        return verified ? .verified : .review
    }
    var minutes: Double { max(0.5, endTs.timeIntervalSince(startTs) / 60) }
}

nonisolated struct Receipt: Identifiable, Codable, Hashable {
    let sceneId: String
    let timestamp: String
    let quote: String
    var thumbUrl: String?
    // Not in the API yet (asked Nayan)
    var confidence: String?
    var speaker: String?

    var id: String { sceneId + timestamp }

    /// Server sends ISO timestamps ("2026-10-25T09:15:00-07:00"); show them as "9:15 AM".
    var displayTime: String {
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = ISO8601DateFormatter().date(from: timestamp) ?? withFraction.date(from: timestamp) {
            return d.formatted(date: .omitted, time: .shortened)
        }
        return timestamp
    }
    var displayConfidence: Confidence {
        if let c = confidence, let parsed = Confidence(rawValue: c.lowercased()) { return parsed }
        // The contract's Receipt has NO confidence field, so every real-backend
        // receipt arrives without one. Never treat that absence as verified.
        return .review
    }
}

/// GET /scenes/today returns { "scenes": [...], "next_before": ... }
nonisolated struct ScenesPage: Codable {
    let scenes: [SceneItem]
    let nextBefore: String?
}

nonisolated struct AskResponse: Codable, Hashable {
    let answer: String
    let receipts: [Receipt]
}

nonisolated struct StatusInfo: Codable, Hashable {
    var recording: Bool
    var sessionId: String?
    var sceneCount: Int
    var lastSceneTs: Date?
    var spendUsd: Double?   // GET /status spend_usd, the live Argon burn
}

/// Isabella's session shape (id + Date startedAt + status), used by
/// setRecording. SessionStartResponse is the gapfill shape (String
/// timestamps + wsUrl), used by startSession. Both decode the same
/// POST /sessions response; keep both so either call site works.
nonisolated struct SessionInfo: Codable {
    let id: String
    var startedAt: Date?
    var status: String?
}

/// POST /sessions → 201. Only id is used; timestamps kept as strings so a
/// format surprise can never break session start.
nonisolated struct SessionStartResponse: Codable {
    let id: String
    let startedAt: String?
    let status: String?
    let wsUrl: String?
}

/// POST /sessions/{id}/end → 200
nonisolated struct SessionEndResponse: Codable {
    let id: String
    let endedAt: String?
    let status: String?
    let sceneCount: Int?
}

struct Person: Identifiable, Hashable {
    let id: String
    let name: String
    let quotes: Int
    let scenes: Int
    let verified: Bool
    // From GET /people when the real backend is up; nil under mock data.
    var photoThumb: String? = nil
    var lastSeen: String? = nil
}

/// One Ask turn. Lives in AppStore (not in AskView) so the conversation
/// survives tab switches and so the Ask tab and Ask opened from Memory
/// are the same conversation, not two separate histories.
nonisolated struct AskExchange: Identifiable, Hashable {
    let id = UUID()
    let question: String
    var response: AskResponse?
    var isLoading: Bool = true
}

/// GET /people → { "people": [...] } (contract field names, snake_case).
nonisolated struct PeoplePage: Codable {
    let people: [PersonDTO]
}

nonisolated struct PersonDTO: Codable {
    let id: String
    let name: String
    let photoThumb: String?
    let lastSeen: String?
    let sceneCount: Int?
    let quoteCount: Int?
    let verified: Bool?
}

/// POST /people → 201 { "id", "name", "verified" } (contract).
nonisolated struct PersonEnrollResponse: Codable {
    let id: String
    let name: String
    let verified: Bool?
}

/// WS /live server messages (contract): scene / status / error (+ pong).
/// Status carries recording + scene_count only; spend_usd is NOT in it.
nonisolated struct LiveMessage: Codable {
    let event: String
    let scene: SceneItem?
    let recording: Bool?
    let sceneCount: Int?
    let code: String?
    let message: String?
}

/// GET /facts?actor=... → { "facts": [...] } (contract field names).
nonisolated struct FactsPage: Codable {
    let facts: [FactItem]
}

nonisolated struct FactItem: Identifiable, Codable, Hashable {
    let id: String
    let text: String
    let sceneId: String?
    let actors: [String]?
    let extractedAt: String?
}

nonisolated enum JSONCoding {
    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        d.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let s = try container.decode(String.self)
            let withFraction = ISO8601DateFormatter()
            withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = withFraction.date(from: s) { return date }
            if let date = ISO8601DateFormatter().date(from: s) { return date }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Bad date: \(s)")
        }
        return d
    }()
}

extension Date {
    var clock: String { formatted(date: .omitted, time: .shortened) }
}
