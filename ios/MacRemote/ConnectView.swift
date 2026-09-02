import SwiftUI

/// Connect + authenticate. Enter the Mac's Tailscale IP and the 6-digit code
/// the server emailed / posted to Discord.
struct ConnectView: View {
    @EnvironmentObject var model: AppModel
    @State private var code = ""
    @FocusState private var focus: Field?

    enum Field { case host, code }

    private var connecting: Bool { model.phase == .connecting }
    private var canConnect: Bool {
        !model.serverHost.trimmingCharacters(in: .whitespaces).isEmpty && code.count >= 4
    }

    var body: some View {
        VStack(spacing: 0) {
            Spacer()
            logo
            Spacer()

            VStack(spacing: 14) {
                FieldRow(icon: "network", placeholder: "Mac Tailscale IP  ·  100.x.x.x",
                         text: $model.serverHost, keyboard: .numbersAndPunctuation, mono: true)
                    .focused($focus, equals: .host)

                FieldRow(icon: "key.fill", placeholder: "6-digit auth code",
                         text: $code, keyboard: .numberPad)
                    .focused($focus, equals: .code)

                if !model.statusMessage.isEmpty {
                    Label(model.statusMessage, systemImage: "exclamationmark.triangle.fill")
                        .font(.footnote)
                        .foregroundStyle(Theme.red)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .transition(.opacity)
                }

                PrimaryButton(title: connecting ? "Connecting…" : "Connect",
                              systemImage: "bolt.horizontal.fill",
                              loading: connecting, enabled: canConnect) {
                    dismissKeyboard()
                    Task { await model.connect(code: code) }
                }
                .padding(.top, 4)
            }
            .padding(20)
            .background(Theme.surface.opacity(0.6),
                        in: RoundedRectangle(cornerRadius: Theme.radius + 4, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.radius + 4, style: .continuous)
                    .strokeBorder(Theme.hairline, lineWidth: 1)
            )

            Text("Runs over your Tailnet. Nothing is exposed publicly.")
                .font(.caption)
                .foregroundStyle(Theme.textFaint)
                .padding(.top, 18)

            Spacer()
        }
        .padding(.horizontal, 22)
        .animation(.easeInOut, value: model.statusMessage)
    }

    private var logo: some View {
        VStack(spacing: 18) {
            ZStack {
                RoundedRectangle(cornerRadius: 26, style: .continuous)
                    .fill(Theme.glowGradient)
                    .frame(width: 92, height: 92)
                    .shadow(color: Theme.accent.opacity(0.5), radius: 28, y: 10)
                Image(systemName: "macbook.and.iphone")
                    .font(.system(size: 40, weight: .medium))
                    .foregroundStyle(.white)
            }
            VStack(spacing: 6) {
                Text("Mac Remote")
                    .font(.system(size: 32, weight: .bold, design: .rounded))
                    .foregroundStyle(Theme.text)
                Text("Drive Conductor from your pocket")
                    .font(.subheadline)
                    .foregroundStyle(Theme.textDim)
            }
        }
    }
}
