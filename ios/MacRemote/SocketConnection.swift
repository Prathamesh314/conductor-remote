import Foundation

enum SocketError: LocalizedError {
    case notConnected
    case authFailed
    case authLocked
    case badResponse
    case transport(String)

    var errorDescription: String? {
        switch self {
        case .notConnected: return "Not connected."
        case .authFailed:   return "Wrong code — try again."
        case .authLocked:   return "Too many attempts. Restart the Mac server."
        case .badResponse:  return "Unexpected response from server."
        case .transport(let m): return m
        }
    }
}

/// Owns the raw WebSocket and turns the server's stream-of-replies protocol into
/// async request/response calls.
///
/// The server processes each inbound message and sends exactly one reply, in
/// order, so post-auth requests are matched to replies with a simple FIFO of
/// continuations. Auth is handled as a distinct first exchange.
actor SocketConnection {
    private let task: URLSessionWebSocketTask
    private var pending: [CheckedContinuation<String, Error>] = []
    private var authContinuation: CheckedContinuation<Void, Error>?
    private var isAuthed = false
    private var closed = false

    /// Called (on the main actor) when the socket drops unexpectedly.
    private let onClose: @Sendable (String) -> Void

    init(host: String, port: Int, onClose: @escaping @Sendable (String) -> Void) throws {
        guard let url = URL(string: "ws://\(host):\(port)") else {
            throw SocketError.transport("Invalid server address")
        }
        self.onClose = onClose
        let session = URLSession(configuration: .default)
        self.task = session.webSocketTask(with: url)
        self.task.resume()
        Task { await self.receiveLoop() }
    }

    // MARK: Auth

    /// Send the auth code and wait for the server's verdict.
    func authenticate(code: String) async throws {
        task.send(.string(code)) { _ in }
        try await withCheckedThrowingContinuation { cont in
            self.authContinuation = cont
        }
    }

    // MARK: Requests

    /// Send a command and await its single reply. Requires prior auth.
    func request(_ text: String) async throws -> String {
        guard isAuthed, !closed else { throw SocketError.notConnected }
        return try await withCheckedThrowingContinuation { cont in
            pending.append(cont)
            task.send(.string(text)) { [weak self] error in
                guard let error else { return }
                Task { await self?.failNext(error) }
            }
        }
    }

    /// Fire-and-forget — used for commands whose reply we don't consume.
    func send(_ text: String) {
        task.send(.string(text)) { _ in }
    }

    func close() {
        guard !closed else { return }
        closed = true
        task.cancel(with: .goingAway, reason: nil)
        for c in pending { c.resume(throwing: SocketError.notConnected) }
        pending.removeAll()
        authContinuation?.resume(throwing: SocketError.notConnected)
        authContinuation = nil
    }

    // MARK: Internals

    private func failNext(_ error: Error) {
        guard !pending.isEmpty else { return }
        pending.removeFirst().resume(throwing: SocketError.transport(error.localizedDescription))
    }

    private func deliver(_ text: String) {
        if !isAuthed {
            switch text {
            case "AUTH_SUCCESS":
                isAuthed = true
                authContinuation?.resume()
            case "AUTH_FAILED":
                authContinuation?.resume(throwing: SocketError.authFailed)
            case "AUTH_LOCKED":
                authContinuation?.resume(throwing: SocketError.authLocked)
                closed = true
            default:
                break  // ignore stray pre-auth chatter
            }
            authContinuation = nil
            return
        }
        guard !pending.isEmpty else { return }
        pending.removeFirst().resume(returning: text)
    }

    private func handleFailure(_ error: Error) {
        guard !closed else { return }
        closed = true
        let message = error.localizedDescription
        for c in pending { c.resume(throwing: SocketError.transport(message)) }
        pending.removeAll()
        authContinuation?.resume(throwing: SocketError.transport(message))
        authContinuation = nil
        onClose(message)
    }

    private func receiveLoop() async {
        while !closed {
            do {
                let message = try await task.receive()
                switch message {
                case .string(let text): deliver(text)
                case .data(let data):   deliver(String(decoding: data, as: UTF8.self))
                @unknown default: break
                }
            } catch {
                handleFailure(error)
                return
            }
        }
    }
}
