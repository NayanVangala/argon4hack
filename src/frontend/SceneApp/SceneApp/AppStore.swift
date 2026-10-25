import Foundation
import Observation

// One place for app data. Screens read from here.
// When Nayan's backend is up: set useMock = false and baseURL to his URL.
@Observable
final class AppStore {
    // Change these in the app: Session tab → Developer (saved on the phone, not in the repo)
    var useMock = UserDefaults.standard.object(forKey: "useMock") as? Bool ?? true {
        didSet { UserDefaults.standard.set(useMock, forKey: "useMock") }
    }
    var baseURL = UserDefaults.standard.string(forKey: "baseURL") ?? "http://localhost:8000" {
        didSet { UserDefaults.standard.set(baseURL, forKey: "baseURL") }
    }
    var token: String? = nil                // never hard-code a real token here (repo is public)

    var scenes: [SceneItem] = []
    var people: [Person] = MockData.people
    var pinned: Set<String> = []
    var isRecording = true {
        didSet {
            guard oldValue != isRecording else { return }
            if isRecording {
                sessionStart = Date()   // a new recording starts the timer from zero
                stoppedAt = nil
            } else {
                stoppedAt = Date()      // freeze the timer when recording stops
            }
        }
    }
    var sessionStart = Date().addingTimeInterval(-(2 * 3600 + 14 * 60))
    var stoppedAt: Date? = nil

    /// How long this session has been recording (stops counting when recording stops).
    func elapsed(at now: Date = Date()) -> TimeInterval {
        max(0, (stoppedAt ?? now).timeIntervalSince(sessionStart))
    }
    var spendUsd: Double? = nil
    var lastError: String? = nil
    var pendingQuery: String? = nil

    // MARK: Loading

    func loadToday() async {
        if useMock {
            scenes = MockData.scenes
            lastError = nil
            return
        }
        do {
            let page: ScenesPage = try await get("/api/v1/scenes/today")
            // Oldest → newest for the timeline; empty quotes count as no quote
            scenes = page.scenes
                .map { var x = $0; if x.quote?.isEmpty == true { x.quote = nil }; return x }
                .sorted { $0.startTs < $1.startTs }
            let status: StatusInfo = try await get("/api/v1/status")
            isRecording = status.recording
            spendUsd = status.spendUsd
            lastError = nil
        } catch {
            lastError = "Couldn't reach the backend: \(error.localizedDescription)"
        }
    }

    func ask(_ query: String) async -> AskResponse {
        if useMock {
            try? await Task.sleep(nanoseconds: 900_000_000)
            return MockData.answer(for: query)
        }
        do {
            return try await post("/api/v1/ask", body: ["query": query])
        } catch {
            lastError = "Ask failed: \(error.localizedDescription)"
            return AskResponse(answer: "I couldn't reach the memory right now.", receipts: [])
        }
    }

    func pin(_ scene: SceneItem) async {
        pinned.insert(scene.id)
        if useMock { return }
        _ = try? await send("/api/v1/pin", body: ["scene_id": scene.id])
    }

    func wipe() {
        // API gap: no wipe endpoint yet. Clears the local view for now.
        scenes = []
        pinned = []
        isRecording = false
    }

    // MARK: Follow-through agent (POST /followups/generate → poll GET /followups)

    var followups: [FollowUp] = []
    var followupStep = -1          // -1 idle · 0 find promises · 1 check quotes · 2 draft · 3 done
    var followupError: String? = nil

    func runFollowThrough() async {
        followupError = nil
        followups = []
        followupStep = 0
        if useMock {
            for step in 1...3 {
                try? await Task.sleep(nanoseconds: 900_000_000)
                followupStep = step
            }
            followups = MockData.followups
            return
        }
        do {
            let run: FollowUpRun = try await post("/api/v1/followups/generate", body: [:])
            // Poll until the agent's drafts show up (real runs take a while; give it ~90s)
            for attempt in 0..<60 {
                let list: FollowUpList = try await get("/api/v1/followups?run_id=\(run.runId)")
                if !list.followups.isEmpty {
                    // Tick through the remaining steps so the loop is visible, then show results
                    while followupStep < 3 {
                        try? await Task.sleep(nanoseconds: 500_000_000)
                        followupStep += 1
                    }
                    followups = list.followups
                    return
                }
                followupStep = min(2, 1 + attempt / 10)
                try await Task.sleep(nanoseconds: 1_500_000_000)
            }
            followupError = "The agent is still working. Try again in a minute."
            followupStep = -1
        } catch {
            followupError = "Follow-through failed: \(error.localizedDescription)"
            followupStep = -1
        }
    }

    /// Approve or dismiss. Nothing is sent anywhere without this tap.
    func updateFollowUp(id: String, draft: String, approve: Bool) async {
        guard let i = followups.firstIndex(where: { $0.id == id }) else { return }
        followups[i].draft = draft
        if !useMock {
            do {
                try await send("/api/v1/followups/\(id)/\(approve ? "approve" : "dismiss")", body: [:])
            } catch {
                followupError = error.localizedDescription
                return
            }
        }
        if let j = followups.firstIndex(where: { $0.id == id }) {
            followups[j].status = approve ? "approved" : "dismissed"
        }
    }

    // MARK: Networking

    private func request(_ path: String) throws -> URLRequest {
        guard let url = URL(string: baseURL + path) else { throw URLError(.badURL) }
        var req = URLRequest(url: url)
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return req
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let (data, response) = try await URLSession.shared.data(for: try request(path))
        try check(response, data)
        return try JSONCoding.decoder.decode(T.self, from: data)
    }

    private func post<T: Decodable>(_ path: String, body: [String: String]) async throws -> T {
        let data = try await send(path, body: body)
        return try JSONCoding.decoder.decode(T.self, from: data)
    }

    @discardableResult
    private func send(_ path: String, body: [String: String]) async throws -> Data {
        var req = try request(path)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: req)
        try check(response, data)
        return data
    }

    /// Turn the server's error envelope {"error": {"message": ...}} into a readable error.
    private func check(_ response: URLResponse, _ data: Data) throws {
        guard let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) else { return }
        let message = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])
            .flatMap { $0["error"] as? [String: Any] }
            .flatMap { $0["message"] as? String } ?? "HTTP \(http.statusCode)"
        throw NSError(domain: "Scene", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
