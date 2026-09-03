import SwiftUI

/// App-wide state + the typed API the views call. Wraps `SocketConnection` and
/// keeps the connection lifecycle, persisted host, and keep-awake state.
@MainActor
final class AppModel: ObservableObject {
    enum Phase: Equatable {
        case signedOut        // show the email sign-in
        case connecting       // an auth exchange is in flight
        case codeSent         // waiting for the user to enter the emailed code
        case connected
    }

    @Published var phase: Phase = .signedOut
    @Published var statusMessage = ""
    @Published var serverHost: String {
        didSet { UserDefaults.standard.set(serverHost, forKey: "serverHost") }
    }
    /// The signed-in user's email (empty when signed out).
    @Published var email = ""
    @Published var awake = false
    /// Whether the server was started with a Conductor API token (enables true
    /// in-chat replies vs. a new-task fallback).
    @Published var hasApiToken = false

    let port = 8765
    private var socket: SocketConnection?
    private let decoder = JSONDecoder()
    private var pendingEmail = ""     // email awaiting code verification

    // Persisted auth (session survives launches for days; see auth.py TTLs).
    private var sessionToken: String { UserDefaults.standard.string(forKey: "auth.session") ?? "" }
    private var refreshToken: String { UserDefaults.standard.string(forKey: "auth.refresh") ?? "" }
    var hasSavedSession: Bool { !sessionToken.isEmpty }

    init() {
        self.serverHost = UserDefaults.standard.string(forKey: "serverHost") ?? ""
        self.email = UserDefaults.standard.string(forKey: "auth.email") ?? ""
    }

    // MARK: - Token storage

    private func saveTokens(_ reply: AuthReply) {
        let d = UserDefaults.standard
        if let s = reply.sessionToken { d.set(s, forKey: "auth.session") }
        if let r = reply.refreshToken { d.set(r, forKey: "auth.refresh") }
        if let e = reply.email { d.set(e, forKey: "auth.email"); email = e }
    }

    private func clearTokens() {
        let d = UserDefaults.standard
        d.removeObject(forKey: "auth.session")
        d.removeObject(forKey: "auth.refresh")
        d.removeObject(forKey: "auth.email")
        email = ""
    }

    // MARK: - Socket lifecycle

    /// Open a fresh socket (closing any prior one). Throws on a bad address.
    private func openSocket() throws {
        Task { [socket] in await socket?.close() }
        socket = try SocketConnection(host: serverHost, port: port) { [weak self] message in
            Task { @MainActor in self?.handleDrop(message) }
        }
    }

    /// Parse a raw auth reply string into AuthReply (nil if it isn't JSON auth).
    private func parseAuth(_ raw: String) -> AuthReply? {
        guard let data = raw.data(using: .utf8),
              let reply = try? decoder.decode(AuthReply.self, from: data),
              reply.auth != nil else { return nil }
        return reply
    }

    // MARK: - Sign in: request a code

    func sendCode(email address: String) async {
        let addr = address.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !serverHost.trimmingCharacters(in: .whitespaces).isEmpty else {
            statusMessage = "Enter the Mac's address first."; return
        }
        guard addr.contains("@") else { statusMessage = "Enter a valid email."; return }
        phase = .connecting
        statusMessage = "Sending code…"
        do {
            try openSocket()
            let raw = try await socket!.authExchange(jsonAuth(["auth": "request", "email": addr]))
            guard let reply = parseAuth(raw) else { throw SocketError.badResponse }
            switch reply.auth {
            case "code_sent":
                pendingEmail = addr
                phase = .codeSent
                statusMessage = reply.debugCode.map { "Code sent. (debug: \($0))" } ?? "Code sent to \(addr)."
            default:
                phase = .signedOut
                statusMessage = reply.error ?? "Couldn't send the code."
            }
        } catch {
            phase = .signedOut
            socket = nil
            statusMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    // MARK: - Sign in: verify the code

    func verifyCode(_ code: String) async {
        let c = code.trimmingCharacters(in: .whitespacesAndNewlines)
        guard socket != nil else { phase = .signedOut; statusMessage = "Request a new code."; return }
        phase = .connecting
        statusMessage = "Verifying…"
        do {
            let raw = try await socket!.authExchange(
                jsonAuth(["auth": "verify", "email": pendingEmail, "code": c]))
            guard let reply = parseAuth(raw) else { throw SocketError.badResponse }
            if reply.auth == "ok" {
                saveTokens(reply)
                await finishSignIn()
            } else {
                phase = .codeSent
                statusMessage = reply.error ?? "Wrong code."
            }
        } catch {
            phase = .signedOut
            socket = nil
            statusMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    // MARK: - Resume a saved session on launch / reconnect

    func resumeSession() async {
        guard hasSavedSession,
              !serverHost.trimmingCharacters(in: .whitespaces).isEmpty else {
            phase = .signedOut; return
        }
        phase = .connecting
        statusMessage = "Reconnecting…"
        do {
            try openSocket()
            var raw = try await socket!.authExchange(jsonAuth(["auth": "session", "token": sessionToken]))
            var reply = parseAuth(raw)
            // Session expired but the refresh token may still be good → swap it.
            if reply?.auth == "error", reply?.code == "expired", !refreshToken.isEmpty {
                raw = try await socket!.authExchange(jsonAuth(["auth": "refresh", "token": refreshToken]))
                reply = parseAuth(raw)
            }
            guard let reply else { throw SocketError.badResponse }
            if reply.auth == "ok" {
                saveTokens(reply)           // refresh returns rotated tokens
                await finishSignIn()
            } else {
                clearTokens()
                phase = .signedOut
                statusMessage = ""          // silent: just show sign-in
            }
        } catch {
            socket = nil
            phase = .signedOut
            statusMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    private func finishSignIn() async {
        await socket?.markAuthenticated()
        phase = .connected
        statusMessage = ""
        await refreshAwake()
    }

    // MARK: - Logout / disconnect

    func logout() {
        let logoutMsg = jsonAuth(["auth": "logout"])
        Task { [socket] in
            await socket?.sendControl(logoutMsg)   // tell the server to drop the session
            await socket?.close()
        }
        socket = nil
        clearTokens()
        phase = .signedOut
        statusMessage = ""
    }

    /// Drop the connection but keep the saved session (so we can reconnect).
    func disconnect() {
        Task { [socket] in await socket?.close() }
        socket = nil
        phase = .signedOut
        statusMessage = ""
    }

    private func handleDrop(_ message: String) {
        guard phase != .signedOut else { return }
        socket = nil
        phase = .signedOut
        statusMessage = "Connection lost. \(message)"
    }

    private func jsonAuth(_ fields: [String: String]) -> String {
        (try? String(decoding: JSONSerialization.data(withJSONObject: fields), as: UTF8.self)) ?? "{}"
    }

    // MARK: Typed requests

    func fetchProjects() async throws -> [Project] {
        try await decode(ProjectsResponse.self, from: "CDT:projects").items
    }

    func fetchSessions() async throws -> [Session] {
        try await decode(SessionsResponse.self, from: "CDT:sessions").items
    }

    func fetchModels() async throws -> ModelsResponse {
        try await decode(ModelsResponse.self, from: "CDT:models")
    }

    func fetchMessages(_ sessionId: String) async throws -> MessagesResponse {
        let resp = try await decode(MessagesResponse.self, from: "CDT:messages:\(sessionId)")
        hasApiToken = resp.hasToken ?? hasApiToken
        return resp
    }

    func send(sessionId: String, text: String) async throws -> SendResult {
        try await decode(SendResult.self, from: "CDT:send:\(sessionId):\(text)")
    }

    func newTask(path: String?, text: String, agent: String?, model: String?) async throws -> SendResult {
        // The server expects: "CDT:newtask:" + a JSON string starting with "{".
        let payload = NewTaskPayload(path: path ?? "", prompt: text, agent: agent, model: model)
        let data = try JSONEncoder().encode(payload)
        let json = String(decoding: data, as: UTF8.self)
        return try await decode(SendResult.self, from: "CDT:newtask:" + json)
    }

    private struct NewTaskPayload: Encodable {
        let path: String
        let prompt: String
        let agent: String?
        let model: String?
    }

    // MARK: Shell + system

    func runShell(_ command: String) async throws -> String {
        try await raw("CMD:\(command)")
    }

    func pwd() async throws -> String {
        try await raw("PWD")
    }

    func setAwake(_ on: Bool) async {
        guard let socket else { return }
        let reply = try? await socket.request(on ? "AWAKE_ON" : "AWAKE_OFF")
        awake = (reply == "AWAKE_ON")
    }

    func refreshAwake() async {
        guard let socket else { return }
        let reply = try? await socket.request("AWAKE_STATUS")
        awake = (reply == "AWAKE_ON")
    }

    // MARK: Plumbing

    private func raw(_ command: String) async throws -> String {
        guard let socket else { throw SocketError.notConnected }
        return try await socket.request(command)
    }

    private func decode<T: Decodable>(_ type: T.Type, from command: String) async throws -> T {
        let text = try await raw(command)
        guard let data = text.data(using: .utf8) else { throw SocketError.badResponse }
        // Surface server-side {"cdt":"error", ...} as a thrown error.
        if let err = try? decoder.decode(ServerError.self, from: data), let message = err.error {
            throw SocketError.transport(message)
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw SocketError.badResponse
        }
    }

    private struct ServerError: Decodable {
        let cdt: String?
        let error: String?
    }
}
