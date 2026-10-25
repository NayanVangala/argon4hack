import Foundation

/// Backend + recording configuration. Fill in the token before running.
/// Token provisioning (QR pairing) is a later step; for the hackathon
/// scaffold, paste a dev token here.
enum Config {
    /// Replace with the hackathon deploy URL. Paths and shapes do not change.
    /// The trailing slash is load-bearing: URL(string:path, relativeTo:)
    /// treats a slash-less last segment as a file and replaces it, so without
    /// it every request would drop "v1" and hit /api/... instead of /api/v1/...
    static let baseURL = URL(string: "https://api.helloscene.xyz/api/v1/")!

    // TODO: paste a dev Bearer token. Never commit a real token to a public repo.
    static var bearerToken: String = "PASTE_DEV_TOKEN_HERE"

    /// Processing slice size from the API contract. Recording itself is continuous.
    static let chunkDurationSeconds: TimeInterval = 30

    /// Upload retries before a chunk goes to the offline buffer.
    static let uploadRetryCount = 1

    /// How long the app keeps retrying a chunked move before giving up (safety).
    static let pendingUploadsDirectoryName = "PendingUploads"
}
