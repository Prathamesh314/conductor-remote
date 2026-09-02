import SwiftUI

/// Connection info, keep-awake toggle, and disconnect.
struct SettingsView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    connectionCard
                    awakeCard
                    GhostButton(title: "Disconnect", systemImage: "power", tint: Theme.red) {
                        model.disconnect()
                    }
                    Text("Mac Remote · connected over Tailscale")
                        .font(.caption)
                        .foregroundStyle(Theme.textFaint)
                        .padding(.top, 8)
                }
                .padding(16)
                .padding(.bottom, 100)
            }
            .background(Color.clear)
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(.hidden, for: .navigationBar)
        }
        .task { await model.refreshAwake() }
    }

    private var connectionCard: some View {
        Card {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeader(title: "Connection")
                infoRow(icon: "network", label: "Host", value: model.serverHost)
                Divider().overlay(Theme.hairline)
                infoRow(icon: "checkmark.seal.fill", label: "Status", value: "Connected",
                        valueColor: Theme.green)
                Divider().overlay(Theme.hairline)
                infoRow(icon: "key.fill", label: "API token",
                        value: model.hasApiToken ? "Present · in-chat replies" : "None · new-task fallback",
                        valueColor: model.hasApiToken ? Theme.green : Theme.amber)
            }
        }
    }

    private var awakeCard: some View {
        Card {
            HStack(spacing: 14) {
                Image(systemName: model.awake ? "cup.and.saucer.fill" : "moon.zzz.fill")
                    .font(.system(size: 20))
                    .foregroundStyle(model.awake ? Theme.amber : Theme.textDim)
                    .frame(width: 30)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Keep Mac awake").font(.system(size: 16, weight: .semibold)).foregroundStyle(Theme.text)
                    Text(model.awake ? "caffeinate is running" : "Mac may sleep")
                        .font(.system(size: 13)).foregroundStyle(Theme.textFaint)
                }
                Spacer()
                Toggle("", isOn: Binding(
                    get: { model.awake },
                    set: { on in Task { await model.setAwake(on) } }))
                    .labelsHidden()
                    .tint(Theme.accent)
            }
        }
    }

    private func infoRow(icon: String, label: String, value: String,
                         valueColor: Color = Theme.text) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon).foregroundStyle(Theme.textFaint).frame(width: 22)
            Text(label).foregroundStyle(Theme.textDim)
            Spacer()
            Text(value.isEmpty ? "—" : value)
                .font(.system(size: 14, weight: .medium, design: label == "Host" ? .monospaced : .default))
                .foregroundStyle(valueColor)
                .lineLimit(1).truncationMode(.middle)
        }
    }
}
