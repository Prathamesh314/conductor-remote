import SwiftUI

/// List of Conductor chats (workspace-centric, newest first).
struct ChatsView: View {
    @EnvironmentObject var model: AppModel
    @State private var sessions: [Session] = []
    @State private var loading = true
    @State private var error: String?
    @State private var showNewTask = false
    @State private var search = ""

    private var filtered: [Session] {
        let q = search.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return sessions }
        return sessions.filter {
            $0.displayName.lowercased().contains(q)
                || ($0.project?.lowercased().contains(q) ?? false)
        }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 10) {
                    if loading && sessions.isEmpty {
                        loadingRows
                    } else if let error, sessions.isEmpty {
                        EmptyState(icon: "wifi.exclamationmark", title: "Couldn't load chats",
                                   subtitle: error)
                    } else if filtered.isEmpty {
                        EmptyState(icon: "tray", title: "No chats",
                                   subtitle: "Start one with the + button.")
                    } else {
                        ForEach(filtered) { session in
                            NavigationLink(value: session) {
                                ChatRow(session: session)
                            }
                            .buttonStyle(PressStyle())
                        }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 100)
            }
            .background(Color.clear)
            .scrollContentBackground(.hidden)
            .refreshable { await load() }
            .searchable(text: $search, prompt: "Search chats")
            .navigationTitle("Chats")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showNewTask = true } label: {
                        Image(systemName: "square.and.pencil")
                            .font(.system(size: 17, weight: .semibold))
                    }
                }
            }
            .navigationDestination(for: Session.self) { ChatDetailView(session: $0) }
            .sheet(isPresented: $showNewTask) {
                NewTaskView { await load() }
            }
            .toolbarBackground(.hidden, for: .navigationBar)
        }
        .task { await load() }
    }

    private var loadingRows: some View {
        ForEach(0..<6, id: \.self) { _ in
            Card { Color.clear.frame(height: 44) }
                .redacted(reason: .placeholder)
                .opacity(0.5)
        }
    }

    private func load() async {
        error = nil
        do {
            sessions = try await model.fetchSessions()
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
        loading = false
    }
}

/// One chat row card.
private struct ChatRow: View {
    let session: Session

    var body: some View {
        Card(padding: 14) {
            HStack(spacing: 12) {
                monogram
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 8) {
                        Text(session.displayName)
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(Theme.text)
                            .lineLimit(1)
                        if session.hasUnread {
                            Circle().fill(Theme.accent).frame(width: 7, height: 7)
                        }
                        Spacer(minLength: 0)
                        Text(RelativeDate.string(session.updatedAt))
                            .font(.system(size: 12))
                            .foregroundStyle(Theme.textFaint)
                    }
                    HStack(spacing: 8) {
                        if let project = session.project, !project.isEmpty {
                            Label(project, systemImage: "folder.fill")
                                .labelStyle(.titleAndIcon)
                                .font(.system(size: 12))
                                .foregroundStyle(Theme.textDim)
                                .lineLimit(1)
                        }
                        if let status = session.status, !status.isEmpty {
                            StatusPill(text: status, color: StatusColor.of(status))
                        }
                    }
                }
            }
        }
    }

    private var monogram: some View {
        let letter = String(session.displayName.first ?? "•").uppercased()
        return Text(letter)
            .font(.system(size: 17, weight: .bold, design: .rounded))
            .foregroundStyle(.white)
            .frame(width: 42, height: 42)
            .background(Theme.accentGradient, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

enum StatusColor {
    static func of(_ status: String) -> Color {
        switch status.lowercased() {
        case let s where s.contains("run") || s.contains("work") || s.contains("progress"):
            return Theme.cyan
        case let s where s.contains("done") || s.contains("complete") || s.contains("idle"):
            return Theme.green
        case let s where s.contains("wait") || s.contains("review") || s.contains("pause"):
            return Theme.amber
        case let s where s.contains("error") || s.contains("fail"):
            return Theme.red
        default:
            return Theme.accent
        }
    }
}
