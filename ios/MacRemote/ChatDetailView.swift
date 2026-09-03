import SwiftUI

/// Read a chat's recent transcript and reply into it. Polls while on screen so
/// the agent's replies show up without a manual refresh.
struct ChatDetailView: View {
    let session: Session
    @EnvironmentObject var model: AppModel

    @State private var messages: [ChatMessage] = []
    @State private var liveTitle: String?   // current name from the server (survives branch renames)
    @State private var draft = ""
    @State private var loading = true
    @State private var sending = false
    @State private var error: String?
    @State private var toast: String?
    @FocusState private var composerFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            transcript
            composer
        }
        .background(AppBackground())
        .navigationTitle(liveTitle ?? session.displayName)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .task { await startPolling() }
    }

    // MARK: Transcript

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    if loading && messages.isEmpty {
                        ProgressView().tint(Theme.accent).padding(.top, 60)
                    } else if messages.isEmpty {
                        EmptyState(icon: "text.bubble", title: "No messages yet",
                                   subtitle: error ?? "Say something to get started.")
                    } else {
                        ForEach(messages) { Bubble(message: $0) }
                        Color.clear.frame(height: 1).id("bottom")
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 16)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: messages) { _, _ in
                withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo("bottom", anchor: .bottom) }
            }
        }
    }

    // MARK: Composer

    private var composer: some View {
        VStack(spacing: 8) {
            if let toast {
                Text(toast)
                    .font(.caption)
                    .foregroundStyle(Theme.textDim)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .transition(.opacity)
            }
            HStack(alignment: .bottom, spacing: 10) {
                TextField("", text: $draft, prompt: Text("Message the agent…").foregroundColor(Theme.textFaint), axis: .vertical)
                    .foregroundStyle(Theme.text)
                    .lineLimit(1...5)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .background(Theme.surfaceHi, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Theme.hairline, lineWidth: 1))
                    .focused($composerFocused)

                Button { Task { await sendDraft() } } label: {
                    Group {
                        if sending {
                            ProgressView().tint(.white).scaleEffect(0.8)
                        } else {
                            Image(systemName: "arrow.up")
                                .font(.system(size: 18, weight: .bold))
                                .foregroundStyle(.white)
                        }
                    }
                    .frame(width: 44, height: 44)
                    .background(Theme.accentGradient, in: Circle())
                    .opacity(canSend ? 1 : 0.45)
                    .shadow(color: Theme.accent.opacity(0.4), radius: 12, y: 4)
                }
                .buttonStyle(PressStyle())
                .disabled(!canSend)
            }
        }
        .padding(.horizontal, 14)
        .padding(.top, 10)
        .padding(.bottom, 8)
        .background(.ultraThinMaterial)
        .overlay(Rectangle().fill(Theme.hairline).frame(height: 1), alignment: .top)
        .animation(.easeInOut, value: toast)
    }

    private var canSend: Bool {
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !sending
    }

    // MARK: Actions

    private func sendDraft() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        sending = true
        // Optimistically show the outgoing message.
        messages.append(ChatMessage(role: "user", text: text, at: nil))
        draft = ""
        do {
            let result = try await model.send(sessionId: session.id, text: text)
            if let note = result.note { flash(note) }
            else if result.ok == false { flash(result.error ?? "Send failed.") }
        } catch {
            flash((error as? LocalizedError)?.errorDescription ?? "Send failed.")
        }
        sending = false
        await reload()
    }

    private func flash(_ message: String) {
        toast = message
        Task {
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            if toast == message { toast = nil }
        }
    }

    private func reload() async {
        do {
            let resp = try await model.fetchMessages(session.id)
            // Refresh the header from the chat's CURRENT identity, so a Conductor
            // branch rename updates the name in place instead of going stale.
            if let name = [resp.workspaceName, resp.title, resp.directoryName]
                .compactMap({ $0?.trimmingCharacters(in: .whitespaces) })
                .first(where: { !$0.isEmpty }) {
                liveTitle = name
            }
            // Keep any optimistic tail the server hasn't caught up to yet.
            if resp.items.count >= messages.count || !resp.items.isEmpty {
                messages = resp.items
            }
            error = nil
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
        loading = false
    }

    /// Poll every 3s while the view is on screen; the task is cancelled on exit.
    private func startPolling() async {
        while !Task.isCancelled {
            await reload()
            try? await Task.sleep(nanoseconds: 3_000_000_000)
        }
    }
}

// MARK: - Message bubble

private struct Bubble: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.isUser { Spacer(minLength: 40) }
            VStack(alignment: message.isUser ? .trailing : .leading, spacing: 4) {
                if !message.isUser {
                    Text(roleLabel)
                        .font(.system(size: 10, weight: .bold))
                        .tracking(0.8)
                        .foregroundStyle(Theme.textFaint)
                }
                Group {
                    if message.isUser {
                        Text(message.text)
                            .font(.system(size: 15))
                            .foregroundStyle(.white)
                            .textSelection(.enabled)
                    } else {
                        MarkdownMessage(text: message.text)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(bubbleBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .strokeBorder(message.isUser ? Color.clear : Theme.hairline, lineWidth: 1))
            }
            if !message.isUser { Spacer(minLength: 40) }
        }
    }

    private var roleLabel: String { message.isAssistant ? "AGENT" : message.role.uppercased() }

    @ViewBuilder private var bubbleBackground: some View {
        if message.isUser {
            Theme.accentGradient.clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        } else {
            Theme.surface.clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
    }
}
