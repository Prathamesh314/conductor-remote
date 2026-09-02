import SwiftUI

/// Top level of the Chats tab: a list of Conductor projects. Tapping a project
/// drills into its chats. Projects are ordered by most recent chat activity, so
/// whatever you're working on floats to the top.
struct ChatsView: View {
    @EnvironmentObject var model: AppModel
    @State private var projects: [Project] = []
    @State private var sessions: [Session] = []
    @State private var loading = true
    @State private var error: String?
    @State private var showNewTask = false
    @State private var search = ""

    private var filtered: [Project] {
        let ordered = orderedProjects
        let q = search.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return ordered }
        return ordered.filter { $0.name.lowercased().contains(q) }
    }

    /// Projects sorted by their most recently updated chat (newest first).
    /// Projects with no chats keep their original order at the bottom.
    private var orderedProjects: [Project] {
        projects.enumerated().sorted { a, b in
            let ta = lastActivity(a.element)
            let tb = lastActivity(b.element)
            if ta != tb { return ta > tb }
            return a.offset < b.offset
        }.map(\.element)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 10) {
                    if loading && projects.isEmpty {
                        loadingRows
                    } else if let error, projects.isEmpty {
                        EmptyState(icon: "wifi.exclamationmark", title: "Couldn't load projects",
                                   subtitle: error)
                    } else if filtered.isEmpty {
                        EmptyState(icon: "folder", title: "No projects",
                                   subtitle: "Start one with the + button.")
                    } else {
                        ForEach(filtered) { project in
                            NavigationLink(value: project) {
                                ProjectRow(project: project,
                                           chatCount: sessionsFor(project).count,
                                           workingCount: workingCount(project))
                            }
                            .buttonStyle(PressStyle())
                        }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 16)
            }
            .background(Color.clear)
            .scrollContentBackground(.hidden)
            .refreshable { await load() }
            .searchable(text: $search, prompt: "Search projects")
            .navigationTitle("Projects")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { MenuButton() }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showNewTask = true } label: {
                        Image(systemName: "square.and.pencil")
                            .font(.system(size: 17, weight: .semibold))
                    }
                }
            }
            .navigationDestination(for: Project.self) { project in
                ProjectChatsView(project: project, initial: sessionsFor(project))
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

    private func sessionsFor(_ project: Project) -> [Session] {
        sessions.filter { $0.projectId == project.id }
    }

    private func workingCount(_ project: Project) -> Int {
        sessionsFor(project).filter { ($0.status ?? "").lowercased().contains("work") }.count
    }

    private func lastActivity(_ project: Project) -> Date {
        sessionsFor(project)
            .compactMap { RelativeDate.date($0.updatedAt) }
            .max() ?? .distantPast
    }

    private func load() async {
        error = nil
        do {
            // Projects give us the list + names; sessions give counts & activity.
            async let p = model.fetchProjects()
            async let s = model.fetchSessions()
            projects = try await p
            sessions = try await s
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
        loading = false
    }
}

/// Chats inside one project.
struct ProjectChatsView: View {
    @EnvironmentObject var model: AppModel
    let project: Project

    @State private var sessions: [Session]
    @State private var loading: Bool
    @State private var error: String?
    @State private var showNewTask = false
    @State private var search = ""

    init(project: Project, initial: [Session]) {
        self.project = project
        _sessions = State(initialValue: initial)
        _loading = State(initialValue: initial.isEmpty)
    }

    private var filtered: [Session] {
        let q = search.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return sessions }
        return sessions.filter { $0.displayName.lowercased().contains(q) }
    }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 10) {
                if loading && sessions.isEmpty {
                    ForEach(0..<5, id: \.self) { _ in
                        Card { Color.clear.frame(height: 44) }
                            .redacted(reason: .placeholder).opacity(0.5)
                    }
                } else if let error, sessions.isEmpty {
                    EmptyState(icon: "wifi.exclamationmark", title: "Couldn't load chats",
                               subtitle: error)
                } else if filtered.isEmpty {
                    EmptyState(icon: "tray", title: "No chats yet",
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
        .background(AppBackground())
        .scrollContentBackground(.hidden)
        .refreshable { await load() }
        .searchable(text: $search, prompt: "Search chats")
        .navigationTitle(project.name)
        .navigationBarTitleDisplayMode(.large)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { showNewTask = true } label: {
                    Image(systemName: "square.and.pencil")
                        .font(.system(size: 17, weight: .semibold))
                }
            }
        }
        .sheet(isPresented: $showNewTask) {
            NewTaskView(preselectedProjectId: project.id) { await load() }
        }
        .toolbarBackground(.hidden, for: .navigationBar)
        .task { await load() }
    }

    private func load() async {
        error = nil
        do {
            let all = try await model.fetchSessions()
            sessions = all.filter { $0.projectId == project.id }
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
        loading = false
    }
}

/// One project card: colored monogram, name, chat count, working indicator.
private struct ProjectRow: View {
    let project: Project
    let chatCount: Int
    let workingCount: Int

    var body: some View {
        Card(padding: 14) {
            HStack(spacing: 12) {
                monogram
                VStack(alignment: .leading, spacing: 4) {
                    Text(project.name)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(Theme.text)
                        .lineLimit(1)
                    Text(subtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.textDim)
                }
                Spacer(minLength: 0)
                if workingCount > 0 {
                    StatusPill(text: "\(workingCount) working", color: Theme.cyan)
                }
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Theme.textFaint)
            }
        }
    }

    private var subtitle: String {
        chatCount == 1 ? "1 chat" : "\(chatCount) chats"
    }

    private var monogram: some View {
        let letter = String(project.name.first ?? "•").uppercased()
        return Text(letter)
            .font(.system(size: 17, weight: .bold, design: .rounded))
            .foregroundStyle(.white)
            .frame(width: 42, height: 42)
            .background(projectColor(project.name),
                       in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

/// Deterministic per-project accent so each project reads distinctly, matching
/// Conductor's colored project avatars.
func projectColor(_ name: String) -> Color {
    let palette: [Color] = [
        Theme.accent, Theme.cyan, Theme.green, Theme.amber, Theme.red,
        Color(hex: 0x4F8BFF), Color(hex: 0xE066C7), Color(hex: 0x38B2AC),
    ]
    var hash: UInt32 = 5381
    for byte in name.utf8 { hash = (hash &* 33) &+ UInt32(byte) }
    return palette[Int(hash % UInt32(palette.count))]
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
                        if let branch = session.branch, !branch.isEmpty {
                            Label(branch, systemImage: "arrow.triangle.branch")
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
