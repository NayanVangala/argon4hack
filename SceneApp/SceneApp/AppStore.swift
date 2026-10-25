import Foundation
import Observation

// One place for app data. Screens read from here.
// When Nayan's backend is up: set useMock = false and baseURL to his URL.
@Observable
final class AppStore {
    var useMock = true
    var baseURL = "http://localhost:8000"   // TODO: Nayan's backend URL
    var token: String? = nil                // TODO: never hard-code a real token here (repo is public)

    var scenes: [SceneItem] = []
    var people: [Person] = MockData.people
    var pinned: Set<String> = []
    var isRecording = true
    var sessionStart = Date().addingTimeInterval(-(2 * 3600 + 14 * 60))
    var spendUsd: Double? = nil
    var lastError: String? = nil
    var pendingQuery: String? = nil

    // MARK: Loading

    func loadToday() async {
        if useMock {
            scenes = MockData.scenes
            return
        }
        do {
            scenes = try await get("/api/v1/scenes/today")
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
        let _: [String: Bool]? = try? await post("/api/v1/pin", body: ["scene_id": scene.id])
    }

    func wipe() {
        // API gap: no wipe endpoint yet. Clears the local view for now.
        scenes = []
        pinned = []
        isRecording = false
    }

    // MARK: Networking

    private func request(_ path: String) throws -> URLRequest {
        guard let url = URL(string: baseURL + path) else { throw URLError(.badURL) }
        var req = URLRequest(url: url)
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return req
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let (data, _) = try await URLSession.shared.data(for: try request(path))
        return try JSONCoding.decoder.decode(T.self, from: data)
    }

    private func post<T: Decodable>(_ path: String, body: [String: String]) async throws -> T {
        var req = try request(path)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, _) = try await URLSession.shared.data(for: req)
        return try JSONCoding.decoder.decode(T.self, from: data)
    }
}
