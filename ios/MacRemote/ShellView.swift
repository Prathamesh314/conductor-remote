import SwiftUI

/// A minimal terminal: run shell commands on the Mac and read the output. The
/// server keeps a persistent working directory per socket.
struct ShellView: View {
    @EnvironmentObject var model: AppModel
    @State private var command = ""
    @State private var lines: [ShellLine] = []
    @State private var running = false
    @State private var cwd = "~"
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                output
                inputBar
            }
            .background(AppBackground())
            .navigationTitle("Shell")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { MenuButton() }
                ToolbarItem(placement: .topBarTrailing) {
                    Text(cwd)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(Theme.textFaint)
                        .lineLimit(1).truncationMode(.head).frame(maxWidth: 180)
                }
            }
            .toolbarBackground(.hidden, for: .navigationBar)
        }
        .task { cwd = (try? await model.pwd()) ?? "~" }
    }

    private var output: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    if lines.isEmpty {
                        EmptyState(icon: "terminal", title: "Run a command",
                                   subtitle: "Output appears here. cd persists between commands.")
                    }
                    ForEach(lines) { line in
                        VStack(alignment: .leading, spacing: 3) {
                            HStack(spacing: 6) {
                                Text("❯").foregroundStyle(Theme.cyan)
                                Text(line.command).foregroundStyle(Theme.text)
                            }
                            .font(.system(size: 13, weight: .medium, design: .monospaced))
                            if !line.output.isEmpty {
                                Text(line.output)
                                    .font(.system(size: 12.5, design: .monospaced))
                                    .foregroundStyle(line.isError ? Theme.red : Theme.textDim)
                                    .textSelection(.enabled)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .id(line.id)
                    }
                    Color.clear.frame(height: 1).id("tail")
                }
                .padding(16)
            }
            .onChange(of: lines) { _, _ in
                withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("tail", anchor: .bottom) }
            }
        }
    }

    private var inputBar: some View {
        HStack(spacing: 10) {
            FieldRow(icon: "chevron.right", placeholder: "command", text: $command, mono: true)
                .focused($focused)
                .onSubmit { Task { await run() } }
            Button { Task { await run() } } label: {
                Group {
                    if running { ProgressView().tint(.white).scaleEffect(0.8) }
                    else { Image(systemName: "play.fill").font(.system(size: 15, weight: .bold)) }
                }
                .foregroundStyle(.white)
                .frame(width: 52, height: 52)
                .background(Theme.accentGradient, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                .opacity(canRun ? 1 : 0.45)
            }
            .buttonStyle(PressStyle())
            .disabled(!canRun)
        }
        .padding(.horizontal, 14)
        .padding(.top, 8)
        .padding(.bottom, 6)
        .background(.ultraThinMaterial)
        .overlay(Rectangle().fill(Theme.hairline).frame(height: 1), alignment: .top)
    }

    private var canRun: Bool {
        !command.trimmingCharacters(in: .whitespaces).isEmpty && !running
    }

    private func run() async {
        let cmd = command.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cmd.isEmpty else { return }
        running = true
        command = ""
        var line = ShellLine(command: cmd, output: "", isError: false)
        do {
            let out = try await model.runShell(cmd)
            line.output = out.trimmingCharacters(in: .whitespacesAndNewlines)
        } catch {
            line.output = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            line.isError = true
        }
        lines.append(line)
        running = false
        // Refresh cwd in case the command changed directory.
        if cmd.hasPrefix("cd") || cmd.contains("&& cd") {
            cwd = (try? await model.pwd()) ?? cwd
        }
    }
}

private struct ShellLine: Identifiable, Equatable {
    let id = UUID()
    let command: String
    var output: String
    var isError: Bool
}
