import SwiftUI

/// Start a fresh Conductor task: pick a project, write a prompt, send.
struct NewTaskView: View {
    var preselectedProjectId: String? = nil
    var onCreated: () async -> Void
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss

    @State private var projects: [Project] = []
    @State private var selected: Project?
    @State private var prompt = ""
    @State private var loadingProjects = true
    @State private var sending = false
    @State private var error: String?

    @State private var agents: [AgentModels] = []
    @State private var selectedAgent: String?
    @State private var selectedModel: String?

    var body: some View {
        NavigationStack {
            ZStack {
                AppBackground()
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        projectPicker
                        if !agents.isEmpty { modelPicker }
                        promptEditor
                        if let error {
                            Label(error, systemImage: "exclamationmark.triangle.fill")
                                .font(.footnote).foregroundStyle(Theme.red)
                        }
                        PrimaryButton(title: "Start Task", systemImage: "paperplane.fill",
                                      loading: sending, enabled: canSend) {
                            Task { await start() }
                        }
                    }
                    .padding(20)
                }
                .scrollDismissesKeyboard(.interactively)
            }
            .navigationTitle("New Task")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }.foregroundStyle(Theme.textDim)
                }
            }
            .toolbarBackground(.hidden, for: .navigationBar)
        }
        .task { await loadProjects() }
    }

    private var canSend: Bool {
        selected != nil && !prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !sending
    }

    private var projectPicker: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Project")
            if loadingProjects {
                ProgressView().tint(Theme.accent).frame(maxWidth: .infinity).padding()
            } else if projects.isEmpty {
                Text("No projects found.").font(.subheadline).foregroundStyle(Theme.textFaint)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(projects) { project in
                            ProjectChip(project: project, selected: selected?.id == project.id) {
                                withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                                    selected = project
                                }
                            }
                        }
                    }
                    .padding(.vertical, 2)
                }
            }
        }
    }

    private var modelPicker: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Model")
            VStack(alignment: .leading, spacing: 12) {
                ForEach(agents) { agent in
                    VStack(alignment: .leading, spacing: 8) {
                        // Only label the agent when more than one is available.
                        if agents.count > 1 {
                            Text(agent.agent)
                                .font(.system(size: 12, weight: .semibold))
                                .foregroundStyle(Theme.textDim)
                        }
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 10) {
                                ForEach(agent.models, id: \.self) { modelId in
                                    ModelChip(name: modelId,
                                              selected: selectedAgent == agent.agent && selectedModel == modelId) {
                                        withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                                            selectedAgent = agent.agent
                                            selectedModel = modelId
                                        }
                                    }
                                }
                            }
                            .padding(.vertical, 2)
                        }
                    }
                }
            }
        }
    }

    private var promptEditor: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Prompt")
            ZStack(alignment: .topLeading) {
                if prompt.isEmpty {
                    Text("Describe what the agent should do…")
                        .foregroundStyle(Theme.textFaint)
                        .padding(.horizontal, 16).padding(.vertical, 14)
                }
                TextEditor(text: $prompt)
                    .foregroundStyle(Theme.text)
                    .scrollContentBackground(.hidden)
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .frame(minHeight: 160)
            }
            .background(Theme.surfaceHi, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Theme.hairline, lineWidth: 1))
        }
    }

    private func loadProjects() async {
        do {
            projects = try await model.fetchProjects()
            let preselected = preselectedProjectId.flatMap { id in projects.first { $0.id == id } }
            selected = selected ?? preselected ?? projects.first
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
        loadingProjects = false
        await loadModels()
    }

    private func loadModels() async {
        // The model picker is optional — if this fails or is empty we just hide
        // it and the task still creates with the server's defaults.
        guard let resp = try? await model.fetchModels(), resp.error == nil else { return }
        let usable = resp.agents.filter { !$0.models.isEmpty }
        guard !usable.isEmpty else { return }
        agents = usable
        // Default to the "claude" agent's default model, then the first agent's
        // default, then just the first model we can find.
        let preferred = usable.first { $0.agent == "claude" } ?? usable[0]
        selectedAgent = preferred.agent
        selectedModel = preferred.defaultModel ?? preferred.models.first
    }

    private func start() async {
        guard let selected else { return }
        sending = true; error = nil
        do {
            let result = try await model.newTask(path: selected.rootPath,
                                                  text: prompt.trimmingCharacters(in: .whitespacesAndNewlines),
                                                  agent: selectedAgent,
                                                  model: selectedModel)
            if result.ok == false {
                error = result.error ?? "Couldn't start the task."
            } else {
                await onCreated()
                dismiss()
            }
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
        sending = false
    }
}

private struct ProjectChip: View {
    let project: Project
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 7) {
                Image(systemName: "folder.fill").font(.system(size: 12))
                Text(project.name).font(.system(size: 14, weight: .semibold)).lineLimit(1)
            }
            .foregroundStyle(selected ? .white : Theme.textDim)
            .padding(.horizontal, 14).padding(.vertical, 10)
            .background {
                if selected {
                    Capsule().fill(Theme.accentGradient)
                } else {
                    Capsule().fill(Theme.surfaceHi).overlay(Capsule().strokeBorder(Theme.hairline, lineWidth: 1))
                }
            }
        }
        .buttonStyle(PressStyle())
    }
}

private struct ModelChip: View {
    let name: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 7) {
                Image(systemName: "cpu").font(.system(size: 12))
                Text(name).font(.system(size: 14, weight: .semibold)).lineLimit(1)
            }
            .foregroundStyle(selected ? .white : Theme.textDim)
            .padding(.horizontal, 14).padding(.vertical, 10)
            .background {
                if selected {
                    Capsule().fill(Theme.accentGradient)
                } else {
                    Capsule().fill(Theme.surfaceHi).overlay(Capsule().strokeBorder(Theme.hairline, lineWidth: 1))
                }
            }
        }
        .buttonStyle(PressStyle())
    }
}
