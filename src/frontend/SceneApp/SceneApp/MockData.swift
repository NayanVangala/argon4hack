import Foundation

// Fake day for building screens before the backend is ready.
// Same shapes as the real API, so swapping is just flipping AppStore.useMock.
enum MockData {
    static func at(_ hour: Int, _ minute: Int) -> Date {
        Calendar.current.date(bySettingHour: hour, minute: minute, second: 0, of: Date()) ?? Date()
    }

    static let scenes: [SceneItem] = [
        SceneItem(id: "s1", startTs: at(12, 2), endTs: at(12, 6), summary: "Walking to the office",
                  quote: nil, type: "location", verified: false, confidence: "silence"),
        SceneItem(id: "s2", startTs: at(12, 40), endTs: at(12, 55), summary: "Lunch at the Ferry Building",
                  quote: "Let's do this again next week.", type: "location", verified: true, speaker: "Jordan"),
        SceneItem(id: "s3", startTs: at(13, 30), endTs: at(13, 34), summary: "Standup with Jordan and Priya",
                  quote: "I'll take the onboarding bug.", type: "conversation", verified: true, speaker: "Priya"),
        SceneItem(id: "s4", startTs: at(14, 14), endTs: at(14, 26), summary: "Maya explaining the Q3 numbers at the whiteboard",
                  quote: "I'll send the Q3 numbers by Friday.", type: "conversation", verified: true, speaker: "Maya"),
        SceneItem(id: "s5", startTs: at(14, 31), endTs: at(14, 34), summary: "Whiteboard session",
                  quote: nil, type: "action", verified: false, confidence: "silence"),
        SceneItem(id: "s6", startTs: at(15, 10), endTs: at(15, 18), summary: "Pricing discussion",
                  quote: "What if we drop the price to 49?", type: "conversation", verified: true, speaker: "Jordan"),
        SceneItem(id: "s7", startTs: at(15, 40), endTs: at(15, 43), summary: "Someone suggests keeping the price",
                  quote: "Let's keep it at forty-nine.", type: "quote", verified: false, confidence: "review"),
        SceneItem(id: "s8", startTs: at(16, 5), endTs: at(16, 20), summary: "Coffee with Priya",
                  quote: "Send me the deck when it's ready.", type: "conversation", verified: true, speaker: "Priya"),
    ]

    static let people: [Person] = [
        Person(id: "p1", name: "Maya", quotes: 14, scenes: 6, verified: true),
        Person(id: "p2", name: "Jordan", quotes: 8, scenes: 4, verified: true),
        Person(id: "p3", name: "Priya", quotes: 5, scenes: 3, verified: true),
    ]

    /// Chips for a real backend: general questions that work on any recorded day.
    static let liveSuggestions = [
        "What did I promise today?",
        "Who did I talk to today?",
        "What decisions did we make?",
        "What did Maya promise me?",
    ]

    static let suggestions = [
        "What did Maya promise me?",
        "When did we discuss pricing?",
        "Who said to keep the price at 49?",
        "What did I promise today?",
    ]

    static let followups: [FollowUp] = [
        FollowUp(id: "f1", runId: "mock", promise: "Maya promised the Q3 numbers by Friday", person: "Maya",
                 quote: "I'll send the Q3 numbers by Friday.", quoteVerified: true, verifiedAt: nil,
                 draft: "Hi Maya, following up on the Q3 numbers you mentioned today. Could you send them over by Friday?",
                 status: "pending", sceneId: "s4"),
        FollowUp(id: "f2", runId: "mock", promise: "You told Priya you'd send her the deck", person: "Priya",
                 quote: "Send me the deck when it's ready.", quoteVerified: true, verifiedAt: nil,
                 draft: "Hi Priya, here's the deck we talked about over coffee.",
                 status: "pending", sceneId: "s8"),
        FollowUp(id: "f3", runId: "mock", promise: "Someone said to keep the price at 49", person: "Unknown",
                 quote: "Let's keep it at forty-nine.", quoteVerified: false, verifiedAt: nil,
                 draft: "", status: "needs_review", sceneId: "s7"),
    ]

    static func answer(for query: String) -> AskResponse {
        let q = query.lowercased()
        if q.contains("maya") || (q.contains("promise") && !q.contains(" i ")) {
            return AskResponse(
                answer: "She promised to send you the Q3 numbers by Friday. She said it at the whiteboard, right after 2 PM.",
                receipts: [Receipt(sceneId: "s4", timestamp: "2:14 PM", quote: "I'll send the Q3 numbers by Friday.",
                                   confidence: "verified", speaker: "Maya")])
        }
        if q.contains("49") || q.contains("forty") || q.contains("keep the price") {
            return AskResponse(
                answer: "Someone said it at 3:40 PM, but I can't confirm who. The voice didn't match anyone enrolled, so I won't put a name on it.",
                receipts: [Receipt(sceneId: "s7", timestamp: "3:40 PM", quote: "Let's keep it at forty-nine.",
                                   confidence: "review", speaker: nil)])
        }
        if q.contains("pricing") || q.contains("price") {
            return AskResponse(
                answer: "At 3:10 PM, Jordan suggested dropping the price to 49. At 3:40 PM, someone pushed back and said to keep it.",
                receipts: [
                    Receipt(sceneId: "s6", timestamp: "3:10 PM", quote: "What if we drop the price to 49?",
                            confidence: "verified", speaker: "Jordan"),
                    Receipt(sceneId: "s7", timestamp: "3:40 PM", quote: "Let's keep it at forty-nine.",
                            confidence: "review", speaker: nil),
                ])
        }
        if q.contains("promise") {
            return AskResponse(
                answer: "You told Priya you'd send her the deck when it's ready. That's still open.",
                receipts: [Receipt(sceneId: "s8", timestamp: "4:05 PM", quote: "Send me the deck when it's ready.",
                                   confidence: "verified", speaker: "Priya")])
        }
        return AskResponse(answer: "I don't have a record of that.", receipts: [])
    }
}
