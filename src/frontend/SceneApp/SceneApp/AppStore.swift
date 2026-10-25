import Foundation
import Observation

// One place for app data. Screens read from here.
// When Nayan's backend is up: set useMock = false and baseURL to his URL.
@Observable
final class AppStore {
    // Change these in the app: Session tab → Developer (saved on the phone, not in the repo)
    var useMock = UserDefaults.standard.object(forKey: "useMock") as? Bool ?? true {
        didSet {
            UserDefaults.standard.set(useMock, forKey: "useMock")
            // Switching data sources: never show the other source's leftovers
            scenes = []
            pinned = []
            followups = []
            followupStep = -1
            lastError = nil
            wipedBefore = nil
            // The live socket is real-mode only; flipping back to mock kills it.
            if useMock { disconnectLive() }
        }
    }
    var baseURL = UserDefaults.standard.string(forKey: "baseURL") ?? "http://localhost:8000" {
        didSet {
            UserDefaults.standard.set(baseURL, forKey: "baseURL")
            // A socket is tied to its origin; a new base URL reconnects on
            // next appear (Live/Memory) instead of streaming the old backend.
            disconnectLive()
        }
    }
    // Typed in the app (Session → Developer). Saved on this phone only, never in the repo.
    var token: String? = UserDefaults.standard.string(forKey: "apiToken").flatMap { $0.isEmpty ? nil : $0 } {
        didSet { UserDefaults.standard.set(token ?? "", forKey: "apiToken") }
    }
    /// What the last wipe actually did, shown on the Session screen so we never overclaim.
    var wipeNote: String? = nil

    var scenes: [SceneItem] = []
    var people: [Person] = MockData.people
    var pinned: Set<String> = []
    /// Shared Ask history, owned here (above the tabs) so switching tabs
    /// never drops it and Memory's Ask shortcut shows the same conversation.
    var askHistory: [AskExchange] = []
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
    var sessionId: String? = nil
    /// API gap: there is no delete endpoint yet, so a wipe hides everything before this time.
    var wipedBefore: Date? = nil
    var lastError: String? = nil
    var pendingQuery: String? = nil

    /// Suggestion chips: practice questions on mock data, general ones on a real backend.
    var suggestions: [String] { useMock ? MockData.suggestions : MockData.liveSuggestions }

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
                .filter { scene in wipedBefore.map { scene.startTs > $0 } ?? true }
                .sorted { $0.startTs < $1.startTs }
            let status: StatusInfo = try await get("/api/v1/status")
            isRecording = status.recording
            sessionId = status.recording ? status.sessionId : nil
            spendUsd = status.spendUsd
            if let id = status.sessionId { sessionId = id }
            lastError = nil
        } catch {
            // A refresh that got cancelled (tab switch, overlapping refresh) isn't a real error
            if Self.isCancellation(error) { return }
            lastError = "Couldn't reach the backend: \(error.localizedDescription)"
        }
    }

    func ask(_ query: String) async -> AskResponse {
        if useMock {
            try? await Task.sleep(nanoseconds: 900_000_000)
            return MockData.answer(for: query)
        }
        do {
            let response: AskResponse = try await post("/api/v1/ask", body: ["query": query])
            // Receipts arrive without a confidence field. Use the confidence the server gave
            // the receipt's own scene (a real server field), never an invented one.
            let receipts = response.receipts.map { receipt -> Receipt in
                var r = receipt
                if r.confidence == nil, let scene = scenes.first(where: { $0.id == r.sceneId }) {
                    r.confidence = scene.displayConfidence.rawValue
                }
                return r
            }
            return AskResponse(answer: response.answer, receipts: receipts)
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

    /// Start or stop recording. On a server this starts/ends a real session (POST /sessions, /sessions/{id}/end).
    func setRecording(_ on: Bool) async {
        if useMock {
            isRecording = on
            return
        }
        // Flip the button right away (no waiting on the network), then tell the server
        let previous = isRecording
        isRecording = on
        do {
            if on {
                let session: SessionInfo = try await post("/api/v1/sessions", body: [:])
                sessionId = session.id
            } else if let id = sessionId {
                try await send("/api/v1/sessions/\(id)/end", body: [:])
            }
            lastError = nil
        } catch {
            isRecording = previous   // server said no: put the button back
            lastError = "Couldn't \(on ? "start" : "stop") recording: \(error.localizedDescription)"
        }
    }


    /// No unpin/delete route exists in the API contract (only POST /pin),
    /// so this is honestly client-side only: the pin disappears from this
    /// phone's pinned list, but the server pin row remains until a route
    /// exists. Never invent a DELETE endpoint for it.
    func unpin(_ scene: SceneItem) {
        pinned.remove(scene.id)
    }

    /// One shared Ask turn: appends to askHistory, then fills in the answer.
    /// AskView renders askHistory, so history survives tab switches.
    func submitAsk(_ query: String) async {
        askHistory.append(AskExchange(question: query))
        let index = askHistory.count - 1
        let result = await ask(query)
        guard index < askHistory.count else { return }
        askHistory[index].response = result
        askHistory[index].isLoading = false
    }

    // MARK: People (contract: GET /people, GET /facts?actor=...)

    func loadPeople() async {
        if useMock { people = MockData.people; return }
        do {
            let page: PeoplePage = try await get("/api/v1/people")
            people = page.people.map {
                Person(id: $0.id, name: $0.name,
                       quotes: $0.quoteCount ?? 0, scenes: $0.sceneCount ?? 0,
                       verified: $0.verified ?? false,
                       photoThumb: $0.photoThumb, lastSeen: $0.lastSeen)
            }
            lastError = nil
        } catch {
            lastError = "Couldn't reach the backend: \(error.localizedDescription)"
        }
    }

    /// Facts about one person. Real mode: GET /facts?actor=<name> (contract).
    /// Mock mode: derived from the already-loaded scenes (their quotes), since
    /// there is no separate mock facts feed.
    func loadFacts(for name: String) async -> [FactItem] {
        if useMock {
            return scenes
                .filter { $0.speaker == name && $0.quote != nil }
                .map { FactItem(id: $0.id, text: $0.quote ?? $0.summary,
                                sceneId: $0.id, actors: [name], extractedAt: nil) }
        }
        do {
            let encoded = name.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? name
            let page: FactsPage = try await get("/api/v1/facts?actor=\(encoded)&limit=20")
            return page.facts
        } catch {
            lastError = "Couldn't reach the backend: \(error.localizedDescription)"
            return []
        }
    }

    // MARK: Enroll (contract: POST /people, multipart)

    /// Enrolls a speaker. The People UI collects a name only (no photo or
    /// voice capture exists in the app), so real mode sends a name-only
    /// multipart body: `name` as a text part, no `photo` / `voice_sample`
    /// parts. If the backend requires photo/voice, it answers 4xx and that
    /// error surfaces in lastError instead of a fake success. Mock mode
    /// appends locally, unverified, so the demo still works offline.
    @discardableResult
    func enrollPerson(name: String) async -> Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        if useMock {
            people.append(Person(id: UUID().uuidString, name: trimmed,
                                 quotes: 0, scenes: 0, verified: false))
            lastError = nil
            return true
        }
        do {
            let created: PersonEnrollResponse = try await postMultipart(
                "/api/v1/people", fields: ["name": trimmed])
            people.append(Person(id: created.id, name: created.name,
                                 quotes: 0, scenes: 0,
                                 verified: created.verified ?? false))
            lastError = nil
            return true
        } catch {
            lastError = "Couldn't enroll \(trimmed): \(error.localizedDescription)"
            return false
        }
    }

    // MARK: Live socket (contract: WS /live)

    /// True while a live socket task exists. No auto-reconnect: when the
    /// socket drops, this flips false and the app degrades to the existing
    /// pull-to-refresh (Memory) / Reload (Session) instead of spinning.
    var liveConnected = false
    private var liveTask: URLSessionWebSocketTask?

    /// WS origin derived from the same apiBase normalizer as REST:
    /// http -> ws, https -> wss, trailing /api/v1 stripped exactly once.
    /// Contract connect shape: <ws(s) origin>/api/v1/live?token=<token>.
    func liveURL() -> URL? {
        var origin = apiBase
        if origin.hasPrefix("https://") {
            origin = "wss://" + origin.dropFirst("https://".count)
        } else if origin.hasPrefix("http://") {
            origin = "ws://" + origin.dropFirst("http://".count)
        } else {
            return nil
        }
        var components = URLComponents(string: origin + "/api/v1/live")
        if let token {
            components?.queryItems = [URLQueryItem(name: "token", value: token)]
        }
        return components?.url
    }

    /// Idempotent: safe to call from LiveView/MemoryView onAppear on every
    /// tab switch. Never connects in mock mode, never opens a second socket.
    func connectLive() {
        guard !useMock else { return }
        guard liveTask == nil else { return }
        guard let url = liveURL() else { return }
        let task = URLSession.shared.webSocketTask(with: url)
        liveTask = task
        liveConnected = true
        task.resume()
        // Contract client message: {"event": "ping"} (keepalive).
        task.send(.string("{\"event\":\"ping\"}")) { _ in }
        Task { await receiveLive(task) }
    }

    func disconnectLive() {
        liveTask?.cancel(with: .goingAway, reason: nil)
        liveTask = nil
        liveConnected = false
    }

    private func receiveLive(_ task: URLSessionWebSocketTask) async {
        while !Task.isCancelled {
            do {
                let message = try await task.receive()
                switch message {
                case .string(let text):
                    handleLiveMessage(text)
                case .data(let data):
                    handleLiveMessage(String(decoding: data, as: UTF8.self))
                @unknown default:
                    break
                }
            } catch {
                break
            }
        }
        // Dropped socket: clear state only if this is still the live task.
        // No retry loop, no crash, no spinner; Memory pull-to-refresh and
        // Session Reload still fetch everything.
        if liveTask === task {
            liveTask = nil
            liveConnected = false
        }
    }

    /// Contract server messages: scene / status / error (+ pong, ignored).
    private func handleLiveMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let event = try? JSONCoding.decoder.decode(LiveMessage.self, from: data)
        else { return }
        switch event.event {
        case "scene":
            guard var scene = event.scene else { return }
            if scene.quote?.isEmpty == true { scene.quote = nil }
            if let i = scenes.firstIndex(where: { $0.id == scene.id }) {
                scenes[i] = scene
            } else {
                scenes.append(scene)
                scenes.sort { $0.startTs < $1.startTs }
            }
        case "status":
            // Contract status carries recording + scene_count only: no
            // spend_usd, no session id. Update recording state only; never
            // invent spend or a session id from a scene count.
            if let recording = event.recording { isRecording = recording }
        case "error":
            lastError = "Live: \(event.message ?? event.code ?? "stream error")"
        default:
            break // pong and anything unknown: ignore
        }
    }

    func wipe() async {
        await endSession()
        scenes = []
        pinned = []
        if useMock {
            wipeNote = "WIPED (MOCK DATA)"
            return
        }
        do {
            // Real delete when the server has it (DELETE /api/v1/data)
            try await delete("/api/v1/data")
            wipedBefore = nil
            wipeNote = "WIPED ON THE SERVER"
            lastError = nil
        } catch {
            // No delete endpoint on this server: hide everything up to now in the app only
            wipedBefore = Date()
            wipeNote = "HIDDEN IN THE APP · THIS SERVER CAN'T DELETE YET"
        }
    }

    // MARK: Sessions (contract: POST /sessions → POST /sessions/{id}/end)

    func startSession() async {
        if isRecording { return }
        if useMock { isRecording = true; return }
        isRecording = true   // flip the button instantly; put it back if the server says no
        do {
            let started: SessionStartResponse = try await post("/api/v1/sessions", body: [:])
            sessionId = started.id
            lastError = nil
            connectLive()
        } catch {
            isRecording = false
            lastError = "Couldn't start session: \(error.localizedDescription)"
        }
    }

    func endSession() async {
        if !isRecording { return }
        if useMock { isRecording = false; return }
        guard let id = sessionId else {
            // No id to end (e.g. the backend's /status omitted it): stop locally
            // so the demo never strands in a recording state.
            isRecording = false
            disconnectLive()
            lastError = "Stopped locally: no session id to end."
            return
        }
        isRecording = false   // flip the button instantly; put it back if the server says no
        do {
            let _: SessionEndResponse = try await post("/api/v1/sessions/\(id)/end", body: [:])
            sessionId = nil
            disconnectLive()
            lastError = nil
        } catch {
            isRecording = true
            lastError = "Couldn't end session: \(error.localizedDescription)"
        }
    }

    /// Re-fetch GET /status only (spend ticker + recording state + session id)
    /// without reloading the timeline. SessionView calls this on appear so the
    /// spend row shows the real spend_usd instead of "$—".
    func refreshStatus() async {
        if useMock { return }
        do {
            let status: StatusInfo = try await get("/api/v1/status")
            isRecording = status.recording
            sessionId = status.recording ? status.sessionId : nil
            spendUsd = status.spendUsd
            lastError = nil
        } catch {
            lastError = "Couldn't reach the backend: \(error.localizedDescription)"
        }
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
        var updated: FollowUp? = nil
        if !useMock {
            do {
                // Your edits to the draft go with the approval
                let data = try await send("/api/v1/followups/\(id)/\(approve ? "approve" : "dismiss")",
                                          body: approve && !draft.isEmpty ? ["draft": draft] : [:])
                // Real backend returns the full follow-up with its email / calendar link
                updated = try? JSONCoding.decoder.decode(FollowUp.self, from: data)
            } catch {
                followupError = error.localizedDescription
                return
            }
        }
        if let j = followups.firstIndex(where: { $0.id == id }) {
            if let updated { followups[j] = updated }
            followups[j].status = approve ? "approved" : "dismissed"
        }
    }

    // MARK: Networking

    private static func isCancellation(_ error: Error) -> Bool {
        if error is CancellationError { return true }
        if let urlError = error as? URLError, urlError.code == .cancelled { return true }
        return false
    }

    /// Normalize whatever the user pastes into Developer → base URL so every
    /// call site's "/api/v1/..." path is appended exactly once:
    /// "http://10.1.63.33:8000" and "http://10.1.63.33:8000/api/v1", with or
    /// without a trailing slash, all resolve to the same origin.
    var apiBase: String {
        var base = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        while base.hasSuffix("/") { base.removeLast() }
        if base.hasSuffix("/api/v1") { base.removeLast("/api/v1".count) }
        return base
    }

    private func request(_ path: String) throws -> URLRequest {
        guard let url = URL(string: apiBase + path) else { throw URLError(.badURL) }
        var req = URLRequest(url: url)
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return req
    }

    private func delete(_ path: String) async throws {
        var req = try request(path)
        req.httpMethod = "DELETE"
        let (data, response) = try await URLSession.shared.data(for: req)
        try check(response, data)
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

    /// Multipart POST for contract routes that take form parts, not JSON
    /// (POST /people: name text part + photo/voice_sample file parts).
    /// Only text fields are sent here: the app has no photo/voice capture,
    /// so callers pass exactly what the UI collected and nothing invented.
    private func postMultipart<T: Decodable>(_ path: String, fields: [String: String]) async throws -> T {
        let boundary = "Scene-\(UUID().uuidString)"
        var body = Data()
        for (key, value) in fields {
            body.append(Data("--\(boundary)\r\n".utf8))
            body.append(Data("Content-Disposition: form-data; name=\"\(key)\"\r\n\r\n".utf8))
            body.append(Data("\(value)\r\n".utf8))
        }
        body.append(Data("--\(boundary)--\r\n".utf8))
        var req = try request(path)
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        let (data, response) = try await URLSession.shared.data(for: req)
        try check(response, data)
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
