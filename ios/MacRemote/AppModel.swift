import SwiftUI

/// App-wide state + the typed API the views call. Wraps `SocketConnection` and
/// keeps the connection lifecycle, persisted host, and keep-awake state.
@MainActor
final class AppModel: ObservableObject {
    enum Phase: Equatable {
        case disconnected
        case connecting
        case connected
    }

    @Published var phase: Phase = .disconnected
    @Published var statusMessage = ""
    @Published var serverHost: String {
        didSet { UserDefaults.standard.set(serverHost, forKey: "serverHost") }
    }
    @Published var awake = false
    /// Whether the server was started with a Conductor API token (enables true
    /// in-chat replies vs. a new-task fallback).
    @Published var hasApiToken = false

    let port = 8765
    private var socket: SocketConnection?
    private let decoder = JSONDecoder()

    init() {
        self.serverHost = UserDefaults.standard.string(forKey: "serverHost") ?? ""
    }

    // MARK: Connection

    func connect(code: String) async {
        phase = .connecting
        statusMessage = "Connecting…"
        do {
            let sock = try SocketConnection(host: serverHost, port: port) { [weak self] message in
                Task { @MainActor in self?.handleDrop(message) }
            }
            socket = sock
            try await sock.authenticate(code: code)
            phase = .connected
            statusMessage = ""
            await refreshAwake()
        } catch {
            phase = .disconnected
            socket = nil
            statusMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    func disconnect() {
        Task { await socket?.close() }
        socket = nil
        phase = .disconnected
        statusMessage = ""
    }

    private func handleDrop(_ message: String) {
        guard phase != .disconnected else { return }
        socket = nil
        phase = .disconnected
        statusMessage = "Connection lost. \(message)"
    }

    // MARK: Typed requests

    func fetchProjects() async throws -> [Project] {
        try await decode(ProjectsResponse.self, from: "CDT:projects").items
    }

    func fetchSessions() async throws -> [Session] {
        try await decode(SessionsResponse.self, from: "CDT:sessions").items
    }

    func fetchMessages(_ sessionId: String) async throws -> MessagesResponse {
        let resp = try await decode(MessagesResponse.self, from: "CDT:messages:\(sessionId)")
        hasApiToken = resp.hasToken ?? hasApiToken
        return resp
    }

    func send(sessionId: String, text: String) async throws -> SendResult {
        try await decode(SendResult.self, from: "CDT:send:\(sessionId):\(text)")
    }

    func newTask(path: String?, text: String) async throws -> SendResult {
        try await decode(SendResult.self, from: "CDT:newtask:\(path ?? ""):\(text)")
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
