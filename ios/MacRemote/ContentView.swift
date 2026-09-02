import SwiftUI

class WebSocketManager: ObservableObject {
    private var webSocketTask: URLSessionWebSocketTask?

    @Published var isConnected = false
    @Published var isAuthenticated = false
    @Published var statusMessage = "Disconnected"

    /// The Mac's Tailscale IP, persisted so you don't retype it each launch.
    @Published var serverHost: String {
        didSet { UserDefaults.standard.set(serverHost, forKey: "serverHost") }
    }
    let port = 8765

    init() {
        self.serverHost = UserDefaults.standard.string(forKey: "serverHost") ?? "100.0.0.0"
    }

    func connect() {
        guard let url = URL(string: "ws://\(serverHost):\(port)") else {
            statusMessage = "Invalid server address"
            return
        }
        let session = URLSession(configuration: .default)
        webSocketTask = session.webSocketTask(with: url)
        webSocketTask?.resume()
        isConnected = true
        statusMessage = "Connected. Awaiting code."
        receiveMessage()
    }

    func disconnect() {
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        isConnected = false
        isAuthenticated = false
        statusMessage = "Disconnected"
    }

    func sendMessage(_ text: String) {
        webSocketTask?.send(.string(text)) { error in
            if let error = error {
                DispatchQueue.main.async {
                    self.statusMessage = "Send error: \(error.localizedDescription)"
                }
            }
        }
    }

    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self else { return }
                switch result {
                case .success(let message):
                    if case .string(let text) = message {
                        self.handle(text)
                    }
                    self.receiveMessage()  // keep listening
                case .failure(let error):
                    self.statusMessage = "Error: \(error.localizedDescription)"
                    self.isConnected = false
                    self.isAuthenticated = false
                }
            }
        }
    }

    private func handle(_ text: String) {
        switch text {
        case "AUTH_SUCCESS":
            isAuthenticated = true
            statusMessage = "Authenticated!"
        case "AUTH_FAILED":
            statusMessage = "Wrong code — try again."
        case "AUTH_LOCKED":
            statusMessage = "Too many attempts. Restart the Mac server."
            disconnect()
        default:
            statusMessage = text
        }
    }
}

struct ContentView: View {
    @StateObject private var ws = WebSocketManager()
    @State private var authCode = ""
    @State private var commandText = ""

    var body: some View {
        VStack(spacing: 20) {
            Text("Mac Remote")
                .font(.largeTitle).bold()

            Text(ws.statusMessage)
                .foregroundColor(.gray)
                .multilineTextAlignment(.center)

            if !ws.isAuthenticated {
                authView
            } else {
                controlView
            }
        }
        .padding()
    }

    private var authView: some View {
        VStack(spacing: 16) {
            TextField("Mac Tailscale IP (e.g. 100.x.x.x)", text: $ws.serverHost)
                .textFieldStyle(.roundedBorder)
                .keyboardType(.numbersAndPunctuation)
                .autocorrectionDisabled()

            TextField("Enter auth code from email", text: $authCode)
                .textFieldStyle(.roundedBorder)
                .keyboardType(.numberPad)

            Button("Connect & Authenticate") {
                ws.connect()
                // Give the socket a moment to open before sending the code.
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                    ws.sendMessage(authCode)
                }
            }
            .buttonStyle(.borderedProminent)
        }
    }

    private var controlView: some View {
        VStack(spacing: 16) {
            Button("Start New Chat") { ws.sendMessage("NEW_CHAT") }
                .buttonStyle(.borderedProminent)
                .tint(.green)

            HStack {
                Button("◀ Prev") { ws.sendMessage("PREV_CHAT") }
                Button("Next ▶") { ws.sendMessage("NEXT_CHAT") }
            }
            .buttonStyle(.bordered)

            HStack {
                TextField("Type prompt here...", text: $commandText, axis: .vertical)
                    .textFieldStyle(.roundedBorder)

                Button("Send") {
                    guard !commandText.isEmpty else { return }
                    ws.sendMessage("TYPE:\(commandText)")
                    commandText = ""
                }
                .buttonStyle(.borderedProminent)
            }

            Button("Disconnect") { ws.disconnect() }
                .foregroundColor(.red)
                .padding(.top)
        }
    }
}

#Preview {
    ContentView()
}
