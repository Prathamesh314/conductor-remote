import Foundation

// MARK: - Domain models
//
// These mirror the JSON the Python server returns for CDT:* commands. Fields the
// server may omit are optional so decoding never fails on a sparse row.

struct Project: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let defaultBranch: String?
    let rootPath: String?

    enum CodingKeys: String, CodingKey {
        case id, name
        case defaultBranch = "default_branch"
        case rootPath = "root_path"
    }
}

struct Session: Codable, Identifiable, Hashable {
    let id: String
    let title: String?
    let status: String?
    let unread: Int?
    let updatedAt: String?
    let model: String?
    let workspaceName: String?
    let branch: String?
    let project: String?
    let projectId: String?

    enum CodingKeys: String, CodingKey {
        case id, title, status, unread, model, branch, project
        case updatedAt = "updated_at"
        case workspaceName = "workspace_name"
        case projectId = "project_id"
    }

    /// What the row shows as its primary label — matches Conductor's
    /// workspace-centric sidebar (workspace name, falling back to title).
    var displayName: String {
        let ws = workspaceName?.trimmingCharacters(in: .whitespaces)
        if let ws, !ws.isEmpty { return ws }
        let t = title?.trimmingCharacters(in: .whitespaces)
        if let t, !t.isEmpty { return t }
        return "Untitled"
    }

    var hasUnread: Bool { (unread ?? 0) > 0 }
}

struct ChatMessage: Codable, Identifiable, Hashable {
    var id: String { "\(role)-\(at ?? "")-\(text.hashValue)" }
    let role: String
    let text: String
    let at: String?

    var isUser: Bool { role.lowercased() == "user" }
    var isAssistant: Bool { role.lowercased() == "assistant" }
}

// MARK: - Response envelopes

struct ProjectsResponse: Codable { let items: [Project] }
struct SessionsResponse: Codable { let items: [Session] }

struct MessagesResponse: Codable {
    let session: String?
    let title: String?
    let items: [ChatMessage]
    let hasToken: Bool?

    enum CodingKeys: String, CodingKey {
        case session, title, items
        case hasToken = "has_token"
    }
}

/// Result of a send / newtask command.
struct SendResult: Codable {
    let ok: Bool?
    let mode: String?
    let note: String?
    let error: String?
    let fallback: Bool?
    let repoMissing: Bool?
    let newSession: String?

    enum CodingKeys: String, CodingKey {
        case ok, mode, note, error, fallback
        case repoMissing = "repo_missing"
        case newSession = "new_session"
    }
}
