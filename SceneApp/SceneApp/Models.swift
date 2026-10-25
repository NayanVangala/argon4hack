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
    var displayConfidence: Confidence {
        if let c = confidence, let parsed = Confidence(rawValue: c.lowercased()) { return parsed }
        return .verified
    }
}

nonisolated struct AskResponse: Codable, Hashable {
    let answer: String
    let receipts: [Receipt]
}

nonisolated struct StatusInfo: Codable, Hashable {
    var recording: Bool
    var sceneCount: Int
    var lastSceneTs: Date?
    var spendUsd: Double?   // API gap: spend in /status
}

struct Person: Identifiable, Hashable {
    let id: String
    let name: String
    let quotes: Int
    let scenes: Int
    let verified: Bool
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
