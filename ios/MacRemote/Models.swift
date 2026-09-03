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
    let workspaceId: String?
    let title: String?
    let status: String?
    let unread: Int?
    let updatedAt: String?
    let model: String?
    let workspaceName: String?
    let directoryName: String?
    let branch: String?
    let project: String?
    let projectId: String?

    enum CodingKeys: String, CodingKey {
        case id, title, status, unread, model, branch, project
        case workspaceId = "workspace_id"
        case updatedAt = "updated_at"
        case workspaceName = "workspace_name"
        case directoryName = "directory_name"
        case projectId = "project_id"
    }

    /// What the row shows as its primary label — workspace name, then the chat
    /// title, then the workspace's stable directory/city name. The final
    /// fallback is deliberately the directory name (which never changes) rather
    /// than anything branch-derived, so the label survives a branch rename.
    var displayName: String {
        for candidate in [workspaceName, title, directoryName] {
            if let v = candidate?.trimmingCharacters(in: .whitespaces), !v.isEmpty { return v }
        }
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

/// One agent's available models + effort levels, as returned by CDT:models.
struct AgentModels: Codable, Identifiable, Hashable {
    var id: String { agent }
    let agent: String
    let models: [String]
    let efforts: [String]
    let defaultModel: String?
    let defaultEffort: String?
    let fastModeModels: [String]?

    enum CodingKeys: String, CodingKey {
        case agent, models, efforts
        case defaultModel = "default_model"
        case defaultEffort = "default_effort"
        case fastModeModels = "fast_mode_models"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        agent = try c.decode(String.self, forKey: .agent)
        models = try c.decodeIfPresent([String].self, forKey: .models) ?? []
        efforts = try c.decodeIfPresent([String].self, forKey: .efforts) ?? []
        defaultModel = try c.decodeIfPresent(String.self, forKey: .defaultModel)
        defaultEffort = try c.decodeIfPresent(String.self, forKey: .defaultEffort)
        fastModeModels = try c.decodeIfPresent([String].self, forKey: .fastModeModels)
    }
}

// MARK: - Auth

/// A `{"auth": ...}` reply from the server during the sign-in handshake.
struct AuthReply: Decodable {
    let auth: String?            // "code_sent" | "ok" | "error" | "logged_out"
    let email: String?
    let sessionToken: String?
    let refreshToken: String?
    let expiresAt: String?
    let refreshExpiresAt: String?
    let code: String?           // error code, e.g. "expired", "invalid", "denied"
    let error: String?          // human-readable error
    let debugCode: String?      // present only in server debug mode

    enum CodingKeys: String, CodingKey {
        case auth, email, code, error
        case sessionToken = "session_token"
        case refreshToken = "refresh_token"
        case expiresAt = "expires_at"
        case refreshExpiresAt = "refresh_expires_at"
        case debugCode = "debug_code"
    }
}

// MARK: - Response envelopes

struct ProjectsResponse: Codable { let items: [Project] }
struct SessionsResponse: Codable { let items: [Session] }
struct ModelsResponse: Codable { let agents: [AgentModels]; let error: String? }

struct MessagesResponse: Codable {
    let session: String?
    let workspaceId: String?
    let title: String?
    let branch: String?
    let workspaceName: String?
    let directoryName: String?
    let items: [ChatMessage]
    let hasToken: Bool?

    enum CodingKeys: String, CodingKey {
        case session, title, branch, items
        case workspaceId = "workspace_id"
        case workspaceName = "workspace_name"
        case directoryName = "directory_name"
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
